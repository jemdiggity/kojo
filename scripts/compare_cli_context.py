"""Compare installed unsandboxed CLI and factory context without model inference.

Both CLIs send the same initial prompt to a local HTTP endpoint that returns 400.
No model executes, so no unsandboxed model tools run. Raw requests stay ignored.
"""
import difflib
import hashlib
import http.server
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src'))
from kojo.execution import command,save
from kojo.transcripts import capture,records


def sha(x):return hashlib.sha256(x.encode()).hexdigest()

def main():
    root=BASE/'intermediate/cli-parity-v1';root.mkdir(parents=True,exist_ok=True)
    workspace=root/'workspace';workspace.mkdir(exist_ok=True)
    if list(workspace.iterdir()):raise RuntimeError('Comparison workspace must be empty')
    prompt='Reply with exactly OK. Do not inspect files or call tools.'
    requests=queue.Queue()
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            requests.put(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(400);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(b'{"error":{"message":"Offline context comparison; no inference","type":"invalid_request_error"}}')
    server=http.server.HTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    extra=['-c','model_provider="audit"','-c','model_providers.audit.name="Offline"',
           '-c','model_providers.audit.base_url='+json.dumps(f'http://127.0.0.1:{server.server_port}/v1'),
           '-c','model_providers.audit.wire_api="responses"','-c','model_providers.audit.requires_openai_auth=false',
           '-c','model_catalog_json='+json.dumps(str(Path.home()/'.codex/models_cache.json')),
           '-c','features.enable_request_compression=false']
    results={}
    try:
        for label in ['unsandboxed','harness']:
            run=root/label
            if run.exists():raise RuntimeError('Comparison ID already used; preserve evidence')
            run.mkdir()
            if label=='unsandboxed':
                cmd=['codex','exec','--dangerously-bypass-approvals-and-sandbox',
                     '--skip-git-repo-check','--json','-m','gpt-6-luna','-c','model_reasoning_effort="low"',
                     '-C',str(workspace),'-o',str(run/'answer.txt'),'-']
            else:
                cmd=command(run,None,BASE/'intermediate/solver-venv',isolated_src=True,persist=True,work_path=workspace)
            # Endpoint transport is the only common non-product override.
            cmd=cmd[:-1]+extra+['-']
            save(run/'command.json',cmd)
            env={k:v for k,v in os.environ.items() if k not in ['OPENAI_API_KEY','CODEX_API_KEY','OPENAI_BASE_URL','OPENAI_ORG_ID','OPENAI_PROJECT_ID']}
            with (run/'audit-events.jsonl').open('w') as out,(run/'stderr.log').open('w') as err:
                process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=out,stderr=err,text=True,env=env)
                try:
                    process.stdin.write(prompt);process.stdin.close()
                    payload=requests.get(timeout=60)
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
                finally:
                    if process.poll() is None:process.kill();process.wait()
            save(run/'request.json',payload)
            events=records(run/'audit-events.jsonl')
            tid=next(x['thread_id'] for x in events if x.get('type')=='thread.started')
            home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
            paths=list((home/'sessions').glob(f'*/*/*/*{tid}*.jsonl'))
            if len(paths)!=1:raise RuntimeError('Native transcript ambiguous')
            meta=next(x['payload'] for x in records(paths[0]) if x.get('type')=='session_meta')
            base=meta['base_instructions']['text']
            capture(run,base,prompt,audit=True)
            messages=[{'role':m['role'],'text':'\n'.join(c.get('text','') for c in m.get('content',[]) if isinstance(c,dict))} for m in payload['input'] if m.get('type')=='message']
            tools=payload.get('tools',[])+[t for item in payload['input'] if item.get('type')=='additional_tools' for t in item.get('tools',[])]
            results[label]={'base':base,'provenance':meta['base_instructions'].get('provenance'),
                            'messages':messages,'tools':tools,'reasoning':payload.get('reasoning'),'model':payload.get('model')}
            save(run/'context.json',results[label])
            print(label,'captured',len(messages),'messages;',len(tools),'top-level tools',flush=True)
    finally:server.shutdown();server.server_close()
    a,b=results['unsandboxed'],results['harness']
    def toolnames(tools,prefix=''):
        out=[]
        for t in tools:
            name=prefix+t.get('name',t.get('type','?'));out.append(name)
            out+=toolnames(t.get('tools',[]),name+'.')
        return out
    an,bn=set(toolnames(a['tools'])),set(toolnames(b['tools']))
    report={'inference_calls':0,'model_equal':a['model']==b['model'],
            'reasoning_equal':a['reasoning']==b['reasoning'],'base_instructions_equal':a['base']==b['base'],
            'base_provenance':{k:v['provenance'] for k,v in results.items()},
            'base_sha256':{k:sha(v['base']) for k,v in results.items()},
            'tools_equal':a['tools']==b['tools'],'tools_only_unsandboxed':sorted(an-bn),'tools_only_harness':sorted(bn-an),
            'messages_equal':a['messages']==b['messages'],
            'messages':{k:[{'role':m['role'],'chars':len(m['text']),'sha256':sha(m['text']), 'first_line':m['text'].splitlines()[0] if m['text'] else ''} for m in v['messages']] for k,v in results.items()}}
    save(root/'comparison.json',report)
    for field in ['base','messages','tools']:
        text=lambda x:x if isinstance(x,str) else json.dumps(x,indent=2,ensure_ascii=False)
        diff=''.join(difflib.unified_diff(text(a[field]).splitlines(True),text(b[field]).splitlines(True),fromfile='unsandboxed',tofile='harness'))
        (root/(field+'.diff')).write_text(diff)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
