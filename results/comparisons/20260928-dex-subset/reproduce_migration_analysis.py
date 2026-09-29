"""Aggregate migration receipts without inference or double-counting resumed sessions."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
rows=[]
for tag in ['opus5','opus55','astra6','sol56','sol6','sonnet55']:
    stem=f'20260928-database-migration-{tag}-medium-'
    rid=stem+('01' if tag=='sonnet55' else '02')
    checkpoints=[]
    for p in sorted((ROOT/'results/runs'/rid/'build').glob('checkpoint_*')):
        e=json.loads((p/'evaluation.json').read_text());counts={s:sum(len(g.get(s,[])) for g in e['tests'].values()) for s in ['passed','failed','skipped']}
        counts['checkpoint']=int(p.name.split('_')[-1]);counts['failures']=[{'group':k,'test':t} for k,g in e['tests'].items() for t in g.get('failed',[])]
        counts['new_tests']={s:sum(len(g.get(s,[])) for k,g in e['tests'].items() if 'Regression' not in k) for s in ['passed','failed','skipped']}
        checkpoints.append(counts)
    seen=set();sessions=[]
    for attempt in ['01','02']:
        for p in sorted((ROOT/'intermediate/runs'/(stem+attempt)/'gauntlet/training-build/database_migration').glob('checkpoint_*/run.json')):
            r=json.loads(p.read_text());identity=r.get('session_id') or r.get('transcript',{}).get('thread_id') or str(p)
            if identity in seen:continue
            seen.add(identity);cost=r.get('api_price_equivalent_usd')
            if tag=='sonnet55' and r.get('provider_usage'):
                u=r['provider_usage'];c=u['cache_creation'];cost=(u['input_tokens']*2+u['cache_read_input_tokens']*.2+u['output_tokens']*10+c['ephemeral_1h_input_tokens']*4+c['ephemeral_5m_input_tokens']*2.5)/1e6
            sessions.append({'receipt':str(p.relative_to(ROOT)),'status':r['status'],'seconds':r.get('elapsed_seconds',0),'cost':cost,'usage':r.get('usage')})
    rows.append({'model':tag,'run_id':rid,'checkpoints':checkpoints,'attempts':sessions,'total_minutes':sum(r['seconds'] for r in sessions)/60,'known_cost':sum(r['cost'] or 0 for r in sessions),'unmetered_attempts':sum(r['usage'] is None for r in sessions)})
(OUT/'migration_analysis.json').write_text(json.dumps(rows,indent=2)+'\n')
for r in rows:print(r['model'],round(r['total_minutes'],2),round(r['known_cost'],3),r['unmetered_attempts'],[f"{c['passed']}/{sum(c[s] for s in ['passed','failed','skipped'])}" for c in r['checkpoints']], [c['new_tests'] for c in r['checkpoints']])
