"""Read-only SCB quality analysis of completed snapshots; no model calls."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src'))
from kojo.catalog import DATA_ROOT
from kojo.gauntlet import hashes

VERSION='0.1.3'

def prepare(source, dest, entrypoint, normalize):
    shutil.copytree(source,dest,symlinks=True)
    mapping={}
    entry=dest/entrypoint
    if normalize and entry.is_file() and not entry.is_symlink() and entry.suffix!='.py':
        ast.parse(entry.read_text())
        target=entry.with_name(entry.name+'.py')
        if target.exists():raise RuntimeError('Normalized entrypoint collision')
        entry.rename(target);mapping[entrypoint]=target.name
    return mapping

def frozen_snapshots(run):
    """Checkpoint directories of every code-changing stage (build, fix, refactor, ...), in the order they ran;
    review and qa stages freeze no snapshot."""
    frozen=[c for c in run.glob('*/checkpoint_*') if (c/'snapshot.json').exists()]
    return sorted(frozen,key=lambda c:(int(re.match(r'checkpoint_(\d+)',c.name)[1]),(c/'run.json').stat().st_mtime))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs',nargs='+')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if (out/"quality.json").exists():raise RuntimeError("Completed output already exists")
    scratch=BASE/'intermediate/quality'/out.name;scratch.mkdir(parents=True,exist_ok=True)
    rows=[]
    for rid in args.runs:
        run=DATA_ROOT/'results/runs'/rid
        manifest=json.loads((run/'manifest.json').read_text())
        entry=manifest['problem_metadata']['entry_file']
        for checkpoint in frozen_snapshots(run):
            stage=checkpoint.parent.name
            receipt=json.loads((checkpoint/'run.json').read_text())
            if receipt.get('status')!='complete':continue
            source=checkpoint/'submission';before=hashes(source)
            if before!=json.loads((checkpoint/'snapshot.json').read_text()):raise RuntimeError('Snapshot mismatch')
            for variant in ['upstream','entrypoint-normalized']:
                work=scratch/rid/(checkpoint.name if stage=='build' else f'{stage}-{checkpoint.name}')/variant
                if work.exists():
                    mapping={entry:entry+'.py'} if variant=='entrypoint-normalized' and (source/entry).is_file() and not entry.endswith('.py') else {}
                else:
                    mapping=prepare(source,work,entry,variant=='entrypoint-normalized')
                cmd=['uvx','--python','3.12.8','--constraints',str(BASE/'scripts/quality-requirements.lock'),f'scb-check=={VERSION}','check','--report','--include-all',str(work)]
                cached=work.parent/(variant+'.json')
                if cached.exists() and cached.read_text().strip():
                    result=subprocess.CompletedProcess(cmd,0,cached.read_text(),(work.parent/(variant+'.stderr.log')).read_text())
                else:
                    result=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
                (work.parent/(variant+'.stderr.log')).write_text(result.stderr)
                (work.parent/(variant+'.json')).write_text(result.stdout)
                if result.returncode and 'no Python files found at' not in result.stderr:
                    raise RuntimeError(f'Analyzer failed: {work}')
                report=json.loads(result.stdout) if result.stdout.strip() else {'files_scanned':0,'total_loc':0,'erosion':None,'verbosity':None,'status':'no_python_files'}
                rows.append({'run_id':rid,'problem':manifest['problem'],'stage':stage,'label':checkpoint.name,'checkpoint':int(re.match(r'checkpoint_(\d+)',checkpoint.name)[1]),'variant':variant,'renamed_files':mapping,'source_sha256':hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),'metrics':report,'stderr_present':bool(result.stderr.strip())})
            if hashes(source)!=before:raise RuntimeError('Source changed during analysis')
            print(rid,stage,checkpoint.name,flush=True)
    data={'scb_check_version':VERSION,'python':'3.12.8','runner_pin':'31ceea3add480edb33431e70475c4c70597e6b31','rows':rows,'limitations':['Current pinned benchmark analyzer, not verified March paper rule set. Version 0.1.3 verbosity also unions trivial-wrapper lines.','Upstream variant scans only .py files. Normalized variant renames extensionless Python entrypoint in analysis copy only.','Generated tests and any vendored .py files follow upstream discovery policy; inspect coverage before interpreting.','Zero files or functions is missing coverage, not proof of quality.']}
    (out/'quality.json').write_text(json.dumps(data,indent=2)+'\n')
    lines=['# Static code quality','', 'Pinned upstream scb-check 0.1.3; no inference. Lower erosion/verbosity is better. Scores below include the extensionless Python entrypoint in an analysis copy. Native-discovery results and every checkpoint are in quality.json.','', '| Run | Stage | CP | Files | LOC | Erosion | Verbosity |','|---|---|---:|---:|---:|---:|---:|']
    for r in rows:
        if r['variant']=='entrypoint-normalized':
            m=r['metrics'];lines.append(f"| {r['run_id']} | {r['stage']} | {r['label'].removeprefix('checkpoint_')} | {m['files_scanned']} | {m['total_loc']} | {m['erosion']:.3f} | {m['verbosity']:.3f} |")
    lines+=['','Limitations:']+['- '+x for x in data['limitations']]
    (out/'QUALITY.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':main()
