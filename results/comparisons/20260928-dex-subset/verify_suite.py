"""Verify frozen sources, native transcript hashes and report-only external access."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from kojo.gauntlet import hashes
from kojo.external_access import audit_external_sources
models={'opus5':'claude-opus-5','opus55':'claude-opus-5-5','sonnet55':'claude-sonnet-5-5','astra6':'gpt-6-astra','sol56':'gpt-5.6-sol','sol6':'gpt-6-sol','fable51':'claude-fable-5-1'}
checks=[];external=[]
for tag,model in models.items():
 for problem,count in [('circuit_eval',8),('database_migration',5),('dynamic_config_service_api',4)]:
  date='20260929' if tag=='fable51' or (problem=='dynamic_config_service_api' and tag in ['opus55','sonnet55']) else '20260928'
  attempt='02' if (problem=='database_migration' and tag not in ['sonnet55','fable51']) or (date=='20260929' and tag!='fable51') else '01'
  rid=f'{date}-{problem.replace("_","-")}-{tag}-medium-{attempt}'
  for n in range(1,count+1):
   cp=ROOT/'results/runs'/rid/f'build/checkpoint_{n}';raw=ROOT/'intermediate/runs'/rid/f'gauntlet/training-build/{problem}/checkpoint_{n}'
   r=json.loads((cp/'run.json').read_text());v=json.loads((cp/'transcript-verification.json').read_text());snapshot=json.loads((cp/'snapshot.json').read_text());t=raw/'transcript.jsonl'
   source_ok=hashes(cp/'submission')==snapshot
   initial=json.loads((cp/'initial-src.json').read_text())
   handoff_ok=initial==({} if n==1 else json.loads((cp.parent/f'checkpoint_{n-1}/snapshot.json').read_text()))
   transcript_ok=hashlib.sha256(t.read_bytes()).hexdigest()==v.get('transcript_sha256',v.get('sha256'))
   prompt_ok=v.get('exact_user_prompt',v.get('exact_user_prompt_in_session',False))
   model_ok=r['model']==model and r['reasoning']=='medium'
   record=dict(run_id=rid,checkpoint=n,source_hashes_match=source_ok,source_handoff_match=handoff_ok,native_transcript_hash_matches=transcript_ok,exact_prompt_verified=prompt_ok,model_effort_receipt_matches=model_ok)
   checks.append(record)
   if not all([source_ok,handoff_ok,transcript_ok,prompt_ok,model_ok]):print('CHECK',record)
   a=audit_external_sources(t);external.append(dict(run_id=rid,checkpoint=n,**a))
(OUT/'suite_verification.json').write_text(json.dumps(dict(checkpoints=checks,external_access=external,limitations=['Native receipts and heuristic external-source audit, not complete provider wire or egress logs.']),indent=2)+'\n')
print('Verified',len(checks),'checkpoints')
print('External events',sum(len(a['events']) for a in external),'flags',sum(len(a['flagged_records']) for a in external),'parse errors',sum(len(a['parse_or_coverage_errors']) for a in external))
for a in external:
 for e in a['events']:
  if e['flags']:print('FLAG',a['run_id'],a['checkpoint'],e['flags'],e['action_excerpt'][:300])
