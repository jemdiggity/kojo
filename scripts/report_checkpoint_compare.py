"""Verify and summarize the completed fresh comparison; makes no model calls."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from checkpoint_compare import PLANS

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src'))
from kojo.execution import cost
from kojo.gauntlet import hashes

NAMES=['Luna','Luna → Luna review → Luna fix','Astra low','Luna → Astra low review → Luna fix']
OUT=BASE/'results/comparisons/20260928-checkpoint-factory-10m'

def read(path):return json.loads(path.read_text())
def save(path,data):path.write_text(json.dumps(data,indent=2)+'\n')
def outcomes(path):
    return {group+'/'+name:status for group,groups in read(path)['tests'].items() for status,names in groups.items() for name in names}
def paired(a,b):
    assert a.keys()==b.keys()
    return {'improved':[k for k in a if a[k]!='passed' and b[k]=='passed'],
            'regressed':[k for k in a if a[k]=='passed' and b[k]!='passed']}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    records=[];threads=[];protocols=set();quotas=[];primary=[];within={};cross={}
    for (rid,flags),name in zip(PLANS,NAMES):
        root=BASE/'results/runs'/rid;raw=BASE/'intermediate/runs'/rid/'gauntlet'
        manifest=read(root/'manifest.json');scores=read(root/'scores.json')
        reviewed='--no-review' not in flags
        assert not (root/'STOPPED.json').exists()
        assert manifest['source_run'] is None and manifest['seconds_per_session']==600
        assert manifest['review_scope']=='checkpoint' and manifest['max_sessions']==(15 if reviewed else 5)
        protocols.add(manifest['protocol_sha256'])
        usage=Counter();partial=Counter();known=0.;partial_cost=0.;seconds=0.;sessions=[];links=[];bounds=[]
        for n in range(1,6):
            prev=root/('fix' if reviewed else 'build')/f'checkpoint_{n-1}'
            assert read(root/'build'/f'checkpoint_{n}'/'initial-src.json')==(read(prev/'snapshot.json') if n>1 else {})
            for role in (['build','review','fix'] if reviewed else ['build']):
                dest=root/role/f'checkpoint_{n}';src=raw/f'training-{role}/code_search/checkpoint_{n}'
                row=read(dest/'run.json');receipt=read(dest/'transcript-verification.json')
                assert row['max_seconds']==600 and row['fresh_conversation']
                assert row['model']==manifest['models'][role] and row['reasoning']=='low'
                assert row['skills_audit']['enabled']==0
                assert receipt['stock_base_instructions_present'] and receipt['exact_user_prompt_in_session']
                assert receipt['base_instructions_provenance']=={'type':'model','model':row['model']}
                assert receipt['base_instructions_sha256']==hashlib.sha256((dest/'stock-instructions.md').read_bytes()).hexdigest()
                native=[json.loads(line) for line in (src/'transcript.jsonl').read_text().splitlines()]
                contexts=[x['payload'] for x in native if x.get('type')=='turn_context']
                assert contexts and all(x.get('model')==row['model'] and x.get('effort')=='low' for x in contexts)
                threads.append(receipt['thread_id']);quotas+=read(dest/'quota.json')
                if role!='review':assert hashes(dest/'submission')==read(dest/'snapshot.json')
                if role in ['review','fix']:
                    assert read(dest/'initial-src.json')==read(root/'build'/f'checkpoint_{n}'/'snapshot.json')
                if role=='fix':assert (dest/'prompt.md').read_text().endswith((root/'review'/f'checkpoint_{n}'/'answer.txt').read_text())
                seconds+=row['elapsed_seconds']
                if row['usage']:
                    usage.update(row['usage']);known+=row['api_price_equivalent_usd']
                else:
                    ticks=[x['payload']['info']['total_token_usage'] for x in native if x.get('type')=='event_msg' and x.get('payload',{}).get('type')=='token_count' and x['payload'].get('info')]
                    if ticks:
                        u=ticks[-1];partial.update(u);c=cost(u,row['model']);partial_cost+=c
                        bounds.append({'role':role,'checkpoint':n,'usage':u,'api_equivalent_usd':c,'source':str(src/'transcript.jsonl')})
                sessions.append({'role':role,'checkpoint':n,'model':row['model'],'status':row['status'],'thread_id':receipt['thread_id'],'elapsed_seconds':row['elapsed_seconds'],'usage':row['usage'],'api_equivalent_usd':row['api_price_equivalent_usd']})
                links.append(f'- {role} CP{n}: [native]({src}/transcript.jsonl), [readable]({src}/transcript.md), [receipt]({role}/checkpoint_{n}/transcript-verification.json).')
        final_role='fix' if reviewed else 'build'
        primary.append([s for s in scores if s['role']==final_role])
        if reviewed:
            within[rid]={str(n):paired(outcomes(root/'build'/f'checkpoint_{n}'/'evaluation.json'),outcomes(root/'fix'/f'checkpoint_{n}'/'evaluation.json')) for n in range(1,6)}
            save(root/'paired.json',within[rid])
        full_success=next(s['strict'] for s in scores if s['role']==final_role and s['checkpoint']==5)
        record={'strict_final_success':full_success,'cost_per_fully_successful_final_task_usd':(known+partial_cost)/full_success if full_success else None,'skill_learning_cost_usd':0,'run_id':rid,'name':name,'seconds':seconds,'completed_usage':dict(usage),'partial_usage':dict(partial),'completed_api_equivalent_usd':known,'partial_api_equivalent_usd':partial_cost,'unmetered_sessions':sum(s['usage'] is None for s in sessions),'partial_counts':bounds,'sessions':sessions}
        records.append(record);save(root/'verified-sessions.json',sessions)
        (root/'TRANSCRIPTS.md').write_text('# Verified native transcripts\n\nExact prompt, stock base, model/low reasoning, isolated skills, fresh contexts and source handoffs verified. These are native CLI records, not independent provider wire receipts. Raw transcripts remain local ignored intermediates.\n\n'+'\n'.join(links)+'\n')
        lines=['# '+name+' — fresh 10-minute checkpoint factory','','| Checkpoint | Builder tests | Final tests | Review improvements / regressions |','|---|---:|---:|---:|']
        for n in range(1,6):
            b=next(s for s in scores if s['role']=='build' and s['checkpoint']==n);f=next(s for s in scores if s['role']==final_role and s['checkpoint']==n)
            delta=within[rid][str(n)] if reviewed else None
            lines.append(f"| {n} | {b['passed']}/{b['total']} | {f['passed']}/{f['total']} | "+(f"{len(delta['improved'])} / {len(delta['regressed'])}" if delta else '—')+' |')
        lines+=['',f"{len(sessions)} sessions, {seconds/60:.2f} model minutes. API-equivalent {'lower bound' if record['unmetered_sessions'] else 'estimate'}: ${known+partial_cost:.4f}. Subscription cash cost unknown.",'','[Full comparison and limitations](../../comparisons/20260928-checkpoint-factory-10m/RESULTS.md) · [Transcripts](TRANSCRIPTS.md) · [Manifest](manifest.json) · [Accounting](accounting.json)']
        (root/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    assert len(protocols)==1 and len(threads)==40 and len(set(threads))==40
    baseline=BASE/'results/runs'/PLANS[0][0]
    for (rid,flags),name in zip(PLANS[1:],NAMES[1:]):
        role='build' if '--no-review' in flags else 'fix';root=BASE/'results/runs'/rid
        cross[rid]={str(n):paired(outcomes(baseline/'build'/f'checkpoint_{n}'/'evaluation.json'),outcomes(root/role/f'checkpoint_{n}'/'evaluation.json')) for n in range(1,6)}
    quotas.sort(key=lambda x:x['observed_at'])
    save(OUT/'accounting.json',{'runs':records,'quota_first':quotas[0],'quota_last':quotas[-1],'protocol_sha256':next(iter(protocols)),'unique_sessions':40})
    save(OUT/'paired.json',{'within_checkpoint_review':within,'cross_condition_vs_luna':cross})
    lines=['# Fresh checkpoint-factory comparison — restricted-network diagnostic','','The user explicitly chose to finish this restricted-network diagnostic after we confirmed that standard SCB allows dependency networking. All four conditions started from empty workspaces under one verified harness hash. Each reviewed checkpoint ran build → review → fix once; the fixed code carried forward. Every session used a fresh conversation and a 600-second limit. All models used low reasoning.','','| Condition | CP1 | CP2 | CP3 | CP4 | CP5 | Fully passed checkpoints |','|---|---:|---:|---:|---:|---:|---:|']
    for name,scores in zip(NAMES,primary):
        scores.sort(key=lambda x:x['checkpoint']);lines.append('| '+name+' | '+' | '.join(f"{s['passed']}/{s['total']}" for s in scores)+f" | {sum(s['strict'] for s in scores)}/5 |")
    lines+=['','Reviewed rows use the final fixer output at every checkpoint. Official scoring includes the required regressions. [Exact paired test changes](paired.json). Cross-condition comparisons use independently generated implementations; within-checkpoint comparisons use the same pre-fix code.','','## Review effects within each checkpoint','','| Reviewed condition | CP1 gain/loss | CP2 gain/loss | CP3 gain/loss | CP4 gain/loss | CP5 gain/loss |','|---|---:|---:|---:|---:|---:|']
    for rid,name in [(PLANS[1][0],NAMES[1]),(PLANS[3][0],NAMES[3])]:
        lines.append('| '+name+' | '+' | '.join(f"{len(within[rid][str(n)]['improved'])} / {len(within[rid][str(n)]['regressed'])}" for n in range(1,6))+' |')
    lines+=['','## Findings for the factory', '', 'Both review conditions improved the final score over the fresh Luna baseline, but intermediate checkpoints and individual review loops could regress. The Astra-reviewed chain finished two tests behind the Astra-only chain at a lower recorded API-equivalent cost. These are single-run observations on independently generated implementations, not a reliable model ranking or causal estimate.', '', 'The Luna-only review loop at checkpoint 5 rejected a previously working Java pattern after adding compiler-based validation, dropping from 85/104 to 81/104. A separate public-example probe reproduced the rejection; see [failure analysis](ANALYSIS.md). The Astra-reviewed loop lost one test at checkpoint 3 and two at checkpoint 4 even while gaining 34 others at checkpoint 4. All four conditions fully passed only checkpoints 1 and 2; none solved the final task completely.', '', 'Cost per fully successful final task is undefined in all conditions (zero full successes). No skill learning occurred, so skill-learning cost is zero. No future-task break-even estimate is supported.', '', '## Resource use','','| Condition | Input (cached subset) | Output | Model minutes | API-equivalent USD |','|---|---:|---:|---:|---:|']
    for r in records:
        u=Counter(r['completed_usage']);u.update(r['partial_usage']);prefix='≥' if r['unmetered_sessions'] else ''
        lines.append(f"| {r['name']} | {prefix}{u['input_tokens']:,} ({u['cached_input_tokens']:,}) | {prefix}{u['output_tokens']:,} | {r['seconds']/60:.2f} | {prefix}${r['completed_api_equivalent_usd']+r['partial_api_equivalent_usd']:.4f} |")
    total=sum(r['completed_api_equivalent_usd']+r['partial_api_equivalent_usd'] for r in records);missing=sum(r['unmetered_sessions'] for r in records)
    lines+=['',f"40 unique sessions; {sum(r['seconds'] for r in records)/60:.2f} model minutes. API-equivalent {'lower bound' if missing else 'estimate'}: **${total:.4f}**. {missing} sessions lack completed usage totals; their last native cumulative counts are included when available. Quota remaining: **{quotas[0]['remaining_percent']}% → {quotas[-1]['remaining_percent']}%**, rounded/account-wide. The authorized quota-floor waiver remained active.",'','Cost uses configured standard short-context API rates: Luna $0.10/$0.01/$0.50 and Astra $10/$1/$50 per million uncached input/cached input/output tokens. Cached input is a subset; repeated requests are summed. These are estimates, not subscription cash charges. Service-tier/long-context billing is not established. [Full session accounting](accounting.json).','','## Scope and reproducibility','','This tests factory workflow changes on one previously examined task. No learned skills or cheat sheets were supplied; no skill updater ran. It is not a held-out generalization or GEPA gskill experiment. Reviewed arms consume three sessions per checkpoint versus one for baselines, so the comparison is not compute-matched. Astra review is stronger-model assistance. One sample cannot estimate randomness or support a future-task break-even calculation.','','Stock model-provided base instructions, installed-skill isolation, tools/runtime, current-only upstream builder prompts, dataset/evaluator pins and session limits were held constant. Reviews receive the public specifications through the current checkpoint as part of the intervention. Hidden scoring follows all generation in a condition; it never selects further model calls. Frozen source, source handoffs, exact reviewer feedback, all 40 unique native conversations and their model/effort settings were verified. Native logs are not provider wire receipts.','','The adapter is Dockerless macOS, with package-network access disabled and an explicitly specified Python 3.12 entry command. The network block was our harness choice, not an SCB requirement: the pinned Docker runtime defaults to bridge networking and its Python environment installs requirements. It prevented parser installation. These are restricted-network diagnostic results, not faithful SCB scores. The user explicitly authorized finishing this batch unchanged after the deviation was identified. Model aliases cannot pin backend weights. Earlier 5-minute/final-review results differ in multiple factors and must not be used to attribute changes solely to review placement.','','[Protocol, pins and reproduction](../../../docs/checkpoint-comparison.md). Run `python3.12 scripts/checkpoint_compare.py` to print commands; `--run` spends usage and refuses used IDs. New reproductions require new IDs. Rebuild this report without inference using `python3.12 scripts/report_checkpoint_compare.py` while the local transcripts remain present. Raw data stay under ignored `intermediate/runs`; final artifacts live under `results/runs`.','']
    lines += [f'- [{name}](../../runs/{rid}/RESULTS.md)' for (rid,_),name in zip(PLANS,NAMES)]
    (OUT/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    index=BASE/'results/runs/index.json';items=read(index)
    for rid,_ in PLANS:
        if not any(x['run_id']==rid for x in items):items.append({'run_id':rid,'results':f'results/runs/{rid}','intermediate':f'intermediate/runs/{rid}','report':f'results/runs/{rid}/RESULTS.md','logs':f'results/runs/{rid}/TRANSCRIPTS.md'})
    save(index,items)
    print('\n'.join(lines[:12]));print(f'API-equivalent {total:.4f}; incomplete sessions {missing}')

if __name__=='__main__':main()
