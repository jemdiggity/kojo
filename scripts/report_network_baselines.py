"""Verify network baseline evidence and report paired results; no model calls."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from network_baselines import PLANS

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src'))
from kojo.gauntlet import hashes
from kojo.execution import cost
from kojo.external_access import audit_external_sources
from report_checkpoint_compare import outcomes,paired

OUT=BASE/'results/comparisons/20260928-network-baselines'
def read(p):return json.loads(p.read_text())
def save(p,data):p.write_text(json.dumps(data,indent=2)+'\n')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    records=[];threads=[];protocols=set();quotas=[];audits=[];supplement=[]
    for (rid,_),name in zip(PLANS,['Luna low','Astra low']):
        root=BASE/'results/runs'/rid
        manifest=read(root/'manifest.json')
        assert manifest['network_enabled'] and manifest['max_sessions']==5 and manifest['review_loops']==0
        assert manifest['source_run'] is None and manifest['seconds_per_session']==600
        assert not (root/'STOPPED.json').exists()
        protocols.add(manifest['protocol_sha256'])
        scores=read(root/'scores.json')
        usage=Counter();seconds=0.;usd=0.;sessions=[];links=[]
        for n in range(1,6):
            dest=root/'build'/f'checkpoint_{n}'
            raw=BASE/'intermediate/runs'/rid/'gauntlet/training-build/code_search'/f'checkpoint_{n}'
            r=read(dest/'run.json');v=read(dest/'transcript-verification.json')
            assert r['fresh_conversation'] and r['network_enabled'] and r['max_seconds']==600
            assert r['model']==manifest['models']['build'] and r['reasoning']=='low'
            assert r['skills_audit']['enabled']==0
            assert v['stock_base_instructions_present'] and v['exact_user_prompt_in_session']
            assert v['base_instructions_provenance']=={'type':'model','model':r['model']}
            assert v['base_instructions_sha256']==hashlib.sha256((dest/'stock-instructions.md').read_bytes()).hexdigest()
            assert hashes(dest/'submission')==read(dest/'snapshot.json')
            assert read(dest/'initial-src.json')==(read(root/'build'/f'checkpoint_{n-1}'/'snapshot.json') if n>1 else {})
            native=[json.loads(x) for x in (raw/'transcript.jsonl').read_text().splitlines()]
            contexts=[x['payload'] for x in native if x.get('type')=='turn_context']
            assert contexts and all(x.get('model')==r['model'] and x.get('effort')=='low' for x in contexts)
            threads.append(v['thread_id']);quotas+=read(dest/'quota.json')
            u=r['usage'];partial=u is None
            if partial:
                ticks=[x['payload']['info']['total_token_usage'] for x in native if x.get('type')=='event_msg' and x.get('payload',{}).get('type')=='token_count' and x['payload'].get('info')]
                u=ticks[-1] if ticks else {}
            usage.update(u);seconds+=r['elapsed_seconds'];usd+=cost(u,r['model']) if partial else r['api_price_equivalent_usd']
            sessions.append({'checkpoint':n,'status':r['status'],'thread_id':v['thread_id'],'usage':u,'usage_is_partial':partial,'seconds':r['elapsed_seconds']})
            audit=audit_external_sources(raw/'transcript.jsonl')
            assert audit==read(dest/'external-access.json')
            audits.append({'run_id':rid,'checkpoint':n,**audit})
            # Supplemental review captures Python-driven pip invocations missed by
            # the frozen runtime auditor's shell-command pattern.
            for line_number,line in enumerate((raw/'events.jsonl').read_text().splitlines(),1):
                event=json.loads(line);item=event.get('item',{})
                command=item.get('command','');output=item.get('aggregated_output','')
                if event.get('type')=='item.completed' and item.get('type')=='command_execution' and 'pip' in command and ('install' in command or 'Downloading ' in output):
                    supplement.append({'run_id':rid,'checkpoint':n,'event_record':line_number,
                                       'source':str(raw/'events.jsonl'),'command':command,
                                       'exit_code':item.get('exit_code'),'output':output})

            links.append(f"- CP{n}: [native transcript]({raw}/transcript.jsonl), [readable transcript]({raw}/transcript.md), [external sources](build/checkpoint_{n}/external-access.json).")
        record={'run_id':rid,'name':name,'scores':scores,'usage':dict(usage),'seconds':seconds,'api_equivalent_usd':usd,'sessions':sessions}
        records.append(record)
        (root/'TRANSCRIPTS.md').write_text('# Verified baseline transcripts\n\n'+'\n'.join(links)+'\n')
        (root/'RESULTS.md').write_text('# '+name+' network-enabled baseline\n\n[Comparison](../../comparisons/20260928-network-baselines/RESULTS.md) · [Transcripts](TRANSCRIPTS.md)\n')
    assert len(protocols)==1 and len(threads)==len(set(threads))==10
    quotas.sort(key=lambda x:x['observed_at'])
    save(OUT/'accounting.json',{'runs':records,'quota_start':quotas[0],'quota_end':quotas[-1],'actual_subscription_cash_cost_usd':None})
    save(OUT/'external-access.json',audits)
    save(OUT/'package-access-supplement.json',supplement)
    pairs={str(n):paired(outcomes(BASE/'results/runs'/PLANS[0][0]/'build'/f'checkpoint_{n}'/'evaluation.json'),outcomes(BASE/'results/runs'/PLANS[1][0]/'build'/f'checkpoint_{n}'/'evaluation.json')) for n in range(1,6)}
    save(OUT/'paired.json',pairs)
    history={}
    for (rid,_),old in zip(PLANS,['20260928-code-search-luna-10m-01','20260928-code-search-astra-10m-01']):
        history[rid]={str(n):paired(outcomes(BASE/'results/runs'/old/'build'/f'checkpoint_{n}'/'evaluation.json'),outcomes(BASE/'results/runs'/rid/'build'/f'checkpoint_{n}'/'evaluation.json')) for n in range(1,6)}
    save(OUT/'historical-paired.json',history)
    lines=['# Network-enabled baselines','','| Checkpoint | Luna low | Astra low | Astra gains / losses vs Luna |','|---|---:|---:|---:|']
    for n in range(1,6):
        cells=[]
        for r in records:
            s=next(x for x in r['scores'] if x['checkpoint']==n)
            cells.append(f"{s['passed']}/{s['total']}")
        lines.append(f"| {n} | "+' | '.join(cells)+f" | {len(pairs[str(n)]['improved'])} / {len(pairs[str(n)]['regressed'])} |")
    lines+=['','| Condition | Input (cached subset) | Output | Minutes | API-equivalent USD |','|---|---:|---:|---:|---:|']
    for r in records:
        u=r['usage']
        lines.append(f"| {r['name']} | {u.get('input_tokens',0):,} ({u.get('cached_input_tokens',0):,}) | {u.get('output_tokens',0):,} | {r['seconds']/60:.2f} | {r['api_equivalent_usd']:.4f} |")
    lines+=['',f"Weekly quota: {quotas[0]['remaining_percent']}% → {quotas[-1]['remaining_percent']}% remaining (rounded, account-wide). Existing quota-floor waiver retained.",
            '',f"External-source audit: {sum(len(a['events']) for a in audits)} network-capable operations; {sum(bool(a['review_suggested']) for a in audits)} sessions with findings suggested for review. [Evidence](external-access.json). Python-driven pip calls can evade the runtime pattern; [supplemental package transcript evidence](package-access-supplement.json) records those too. Findings do not stop runs or decide validity. This heuristic is not a complete network traffic log.",
            '','Ten fresh conversations verified, one per checkpoint; current-only upstream specs, stock Codex base instructions, isolated installed skills, same harness and 600-second session caps. Each baseline began with empty source; its own code/environment persisted across checkpoints. No review or skill learning. Official grading occurred after each condition finished generation.',
            '','One sample per model on a previously examined task: preliminary evidence, not held-out learning or official SCB leaderboard scores. Dockerless macOS differs from the upstream container. Model aliases cannot pin provider weights. API-equivalent estimates use configured rates, not subscription charges; partial native token counts are marked in accounting. No learning cost or break-even estimate applies.',
            '','[Transcript observations](OBSERVATIONS.md).','','[Paired test identities](paired.json) · [Historical restricted-network comparison](historical-paired.json) · [Accounting](accounting.json). Historical differences combine network/runtime changes with sampling randomness.',
            '','Reproduce with new IDs in `scripts/network_baselines.py`; `--run` spends usage. Rebuild this report with `python3.12 scripts/report_network_baselines.py`. Pins and instruction hashes are recorded in each manifest.']
    for rid,_ in PLANS:lines.append(f"- [{rid}](../../runs/{rid}/RESULTS.md)")
    (OUT/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    index=BASE/'results/runs/index.json';items=read(index)
    for rid,_ in PLANS:
        if not any(x['run_id']==rid for x in items):items.append({'run_id':rid,'results':f'results/runs/{rid}','intermediate':f'intermediate/runs/{rid}','report':f'results/runs/{rid}/RESULTS.md','logs':f'results/runs/{rid}/TRANSCRIPTS.md'})
    save(index,items)
    print('\n'.join(lines[:15]))

if __name__=='__main__':main()
