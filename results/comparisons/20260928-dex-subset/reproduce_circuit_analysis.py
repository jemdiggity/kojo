import json,pathlib,hashlib,itertools,collections
root=pathlib.Path(__file__).resolve().parents[3];out=root/'results/comparisons/20260928-dex-subset'; tags=['opus5','opus55','astra6','sol56','sol6','sonnet55']; data={'schema_version':1,'problem':'circuit_eval','models':{},'paired':{},'sources':{}}
for tag in tags:
 rows=[];usage=collections.Counter();cost=0;secs=0;corrected=0
 for cp in range(1,9):
  p=root/f'results/runs/20260928-circuit-eval-{tag}-medium-01/build/checkpoint_{cp}'
  ds={}
  for name in ['evaluation.json','run.json','transcript-verification.json','external-access.json']:
   raw=(p/name).read_bytes();ds[name]=json.loads(raw);data['sources'][str((p/name).relative_to(root))]=hashlib.sha256(raw).hexdigest()
  e,r,v,a=[ds[n] for n in ['evaluation.json','run.json','transcript-verification.json','external-access.json']]
  outcomes={f'{g.split("-")[0]}::{t}':status for g,x in e['tests'].items() for status,names in x.items() for t in names}
  assert r['status']=='complete' and r['reasoning']=='medium' and v.get('exact_user_prompt',v.get('exact_user_prompt_in_session'))
  usage.update(r['usage']);secs+=r['elapsed_seconds'];cost+=r['api_price_equivalent_usd']
  if r.get('provider')=='claude':
   u=r['provider_usage'];i,o,read,w=(5,25,.5,10) if tag=='opus5' else ((4,20,.2,8) if tag=='opus55' else (2,10,.2,4));cc=u['cache_creation'];adjusted=(u['input_tokens']*i+u['output_tokens']*o+u['cache_read_input_tokens']*read+cc['ephemeral_1h_input_tokens']*w+cc['ephemeral_5m_input_tokens']*i*1.25)/1e6
  else:adjusted=r['api_price_equivalent_usd']
  corrected+=adjusted
  rows.append({'checkpoint':cp,'passed':sum(x=='passed' for x in outcomes.values()),'total':len(outcomes),'failed':[k for k,v in outcomes.items() if v=='failed'],'outcomes':outcomes,'elapsed_seconds':r['elapsed_seconds'],'usage':r['usage'],'recorded_cost_usd':r['api_price_equivalent_usd'],'recalculated_api_equivalent_usd':adjusted,'external_access':a,'transcript_verification':v})
 data['models'][tag]={'checkpoints':rows,'strict_passes':sum(x['passed']==x['total'] for x in rows),'mean_checkpoint_fraction':sum(x['passed']/x['total'] for x in rows)/8,'elapsed_seconds':secs,'usage':dict(usage),'recorded_cost_usd':cost,'api_equivalent_usd':corrected}
for a,b in itertools.combinations(tags,2):
 pairs=[]
 for x,y in zip(data['models'][a]['checkpoints'],data['models'][b]['checkpoints']):
  assert set(x['outcomes'])==set(y['outcomes'])
  pairs.append({'checkpoint':x['checkpoint'],'a_only_passes':[k for k,v in x['outcomes'].items() if v=='passed' and y['outcomes'][k]!='passed'],'b_only_passes':[k for k,v in y['outcomes'].items() if v=='passed' and x['outcomes'][k]!='passed']})
 data['paired'][a+'__'+b]=pairs
(out/'circuit_analysis.json').write_text(json.dumps(data,indent=2)+'\n')
for t,x in data['models'].items():print(t,x['strict_passes'],round(x['mean_checkpoint_fraction']*100,3),x['api_equivalent_usd'])
