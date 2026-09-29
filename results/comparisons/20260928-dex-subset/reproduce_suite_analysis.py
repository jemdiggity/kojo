"""Read-only aggregation of frozen grading and unique inference receipts; no model calls."""
import json
from pathlib import Path
from itertools import combinations
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
models=['opus5','opus55','astra6','sol56','sol6','sonnet55']
problems=['circuit_eval','database_migration','dynamic_config_service_api']
rows=[]
for model in models:
    sessions=[];seen=set();checks=[]
    for problem in problems:
        stem=f'20260928-{problem.replace("_","-")}-{model}-medium-'
        attempt='02' if problem=='database_migration' and model!='sonnet55' else '01'
        selected=ROOT/'results/runs'/(stem+attempt)/'build'
        evaluations={}
        if problem=='dynamic_config_service_api' and model in ['opus55','sonnet55']:
            selected=ROOT/'results/runs'/f'20260929-dynamic-config-service-api-{model}-medium-02'/'build'
            recovered=OUT/f'{model}-api-recovered-regraded/regrading.json'
            if recovered.exists():
                evaluations={int(c['checkpoint'].split('_')[-1]):c['evaluation'] for c in json.loads(recovered.read_text())['checkpoints']}
        for p in sorted(selected.glob('checkpoint_*/evaluation.json')):
            evaluations[int(p.parent.name.split('_')[-1])]=json.loads(p.read_text())
        if problem=='dynamic_config_service_api' and model=='astra6':
            evaluations={int(c['checkpoint'].split('_')[-1]):c['evaluation'] for c in json.loads((OUT/'astra-api-regraded/regrading.json').read_text())['checkpoints']}
        for cp,e in sorted(evaluations.items()):
            counts={s:sum(len(g.get(s,[])) for g in e['tests'].values()) for s in ['passed','failed','skipped']}
            outcomes={group+'::'+test:s for group,g in e['tests'].items() for s in ['passed','failed','skipped'] for test in g.get(s,[])}
            checks.append(dict(problem=problem,checkpoint=cp,**counts,strict=int(counts['failed']==0 and counts['skipped']==0),outcomes=outcomes))
        for p in sorted((ROOT/'intermediate/runs').glob(f'202609*-{problem.replace(chr(95),chr(45))}-{model}-medium-*/gauntlet/training-build/{problem}/checkpoint_*/run.json')):
            r=json.loads(p.read_text());ident=r.get('session_id') or r.get('transcript',{}).get('thread_id') or str(p)
            if r['status']=='started' or ident in seen:continue
            seen.add(ident);cost=r.get('api_price_equivalent_usd')
            if model=='sonnet55' and r.get('provider_usage'):
                u=r['provider_usage'];c=u['cache_creation'];cost=(u['input_tokens']*2+u['cache_read_input_tokens']*.2+u['output_tokens']*10+c['ephemeral_1h_input_tokens']*4+c['ephemeral_5m_input_tokens']*2.5)/1e6
            sessions.append(dict(problem=problem,receipt=str(p.relative_to(ROOT)),identity=ident,status=r['status'],seconds=r.get('elapsed_seconds',0),cost=cost,usage=r.get('usage'),transcript=r.get('transcript')))
    rows.append(dict(model=model,checkpoints=checks,attempts=sessions,strict=sum(c['strict'] for c in checks),accepted_checkpoints=len(checks),cost=sum(s['cost'] or 0 for s in sessions),minutes=sum(s['seconds'] for s in sessions)/60,unmetered=sum(s['usage'] is None for s in sessions),tokens={k:sum((s['usage'] or {}).get(k,0) for s in sessions) for k in ['input_tokens','cached_input_tokens','output_tokens']}))
pairs=[]
for a,b in combinations(rows,2):
    for ca in a['checkpoints']:
        cb=next((c for c in b['checkpoints'] if (c['problem'],c['checkpoint'])==(ca['problem'],ca['checkpoint'])),None)
        if cb is None:continue
        common=ca['outcomes'].keys() & cb['outcomes'].keys()
        pairs.append(dict(a=a['model'],b=b['model'],problem=ca['problem'],checkpoint=ca['checkpoint'],a_only_passed=sorted(t for t in common if ca['outcomes'][t]=='passed' and cb['outcomes'][t]!='passed'),b_only_passed=sorted(t for t in common if cb['outcomes'][t]=='passed' and ca['outcomes'][t]!='passed')))
(OUT/'suite_analysis.json').write_text(json.dumps(dict(models=rows,paired=pairs),indent=2)+'\n')
for r in rows:print(r['model'],r['strict'],r['accepted_checkpoints'],round(r['cost'],2),round(r['minutes'],1),r['tokens'])
