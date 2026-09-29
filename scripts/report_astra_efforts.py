"""Reproduce the Astra effort comparison from frozen run receipts."""
import itertools
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kojo.catalog import BASE
from kojo.registry import register_runs

OUT = BASE/'results/comparisons/20260928-astra-efforts'
OUT.mkdir(parents=True, exist_ok=True)
rows = {}
for effort in ['low', 'medium', 'high']:
    rid = f'20260928-code-search-astra-{effort}-default-01'
    root = BASE/'results/runs'/rid
    raw = BASE/'intermediate/runs'/rid/'gauntlet/training-build/code_search'
    checks = []
    manifest = json.loads((root/'manifest.json').read_text())
    for n in range(1,6):
        p = root/f'build/checkpoint_{n}'
        read = lambda name: json.loads((p/name).read_text())
        run = read('run.json'); grade = read('evaluation.json'); verify = read('transcript-verification.json')
        assert run['status']=='complete' and run['model']=='gpt-6-astra' and run['reasoning']==effort
        assert verify['exact_user_prompt_in_session'] and verify['stock_base_instructions_present']
        records = [json.loads(line) for line in (raw/f'checkpoint_{n}/transcript.jsonl').open()]
        contexts = [r['payload'] for r in records if r.get('type')=='turn_context']
        assert contexts and all(c['model']=='gpt-6-astra' and c['effort']==effort for c in contexts)
        request = json.loads((raw/f'checkpoint_{n}/audit-request.json').read_text())
        assert request['model']=='gpt-6-astra' and request['reasoning']['effort']==effort
        assert 'max_output_tokens' not in request
        passed=[]; failed=[]
        for group, tests in grade['tests'].items():
            cp=group.split('-')[0]
            passed += [f'{cp}::{t}' for t in tests['passed']]
            failed += [f'{cp}::{t}' for t in tests['failed']]
            assert not tests['skipped']
        checks.append(dict(checkpoint=n,passed=len(passed),total=len(passed)+len(failed),
            passed_tests=passed,failed_tests=failed,usage=run['usage'],seconds=run['elapsed_seconds'],
            cost=run['api_price_equivalent_usd'],session_id=verify['thread_id'],external_access=read('external-access.json')))
    assert len({c['session_id'] for c in checks})==5
    rows[effort]=dict(run_id=rid,checkpoints=checks,protocol_sha256=manifest['protocol_sha256'],
        seconds=sum(c['seconds'] for c in checks),cost=sum(c['cost'] for c in checks),
        usage={k:sum(c['usage'].get(k,0) or 0 for c in checks) for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']})
assert len({r['protocol_sha256'] for r in rows.values()})==1
assert len({c['session_id'] for r in rows.values() for c in r['checkpoints']})==15
paired=[]
for left,right in itertools.combinations(rows,2):
    for a,b in zip(rows[left]['checkpoints'],rows[right]['checkpoints']):
        assert set(a['passed_tests']+a['failed_tests'])==set(b['passed_tests']+b['failed_tests'])
        paired.append(dict(left=left,right=right,checkpoint=a['checkpoint'],
            left_only=sorted(set(a['passed_tests'])-set(b['passed_tests'])),right_only=sorted(set(b['passed_tests'])-set(a['passed_tests']))))
(OUT/'comparison.json').write_text(json.dumps(dict(runs=rows,paired=paired),indent=2)+'\n')
lines=['# Astra low / medium / high: code_search','',
 'All three completed five checkpoints without timeout, interruption, or retry. Low finishes at 96/104; medium and high finish at 95/104. Higher effort did not improve correctness in this single run per effort. Randomness is not controlled by repeats, so this is preliminary evidence, not a general effort ranking.','',
 '| Checkpoint | Low | Medium | High |','|---|---:|---:|---:|']
for n in range(5):
    lines.append('| CP'+str(n+1)+' | '+' | '.join(f"{r['checkpoints'][n]['passed']}/{r['checkpoints'][n]['total']}" for r in rows.values())+' |')
lines += ['', '| Effort | Input tokens (cached included) | Cached input | Output tokens | Model minutes | API-equivalent USD |','|---|---:|---:|---:|---:|---:|']
for effort,r in rows.items():
    u=r['usage'];lines.append(f"| {effort} | {u['input_tokens']:,} | {u['cached_input_tokens']:,} | {u['output_tokens']:,} | {r['seconds']/60:.2f} | {r['cost']:.4f} |")
lines += ['','## Per-checkpoint usage','','| Effort | Checkpoint | Input | Cached input | Output | Minutes | USD |','|---|---|---:|---:|---:|---:|---:|']
for effort,r in rows.items():
    for c in r['checkpoints']:
        u=c['usage'];lines.append(f"| {effort} | CP{c['checkpoint']} | {u['input_tokens']:,} | {u['cached_input_tokens']:,} | {u['output_tokens']:,} | {c['seconds']/60:.2f} | {c['cost']:.4f} |")
lines += ['','## Paired test differences','']
for p in paired:
    if p['left_only'] or p['right_only']:
        lines.append(f"- CP{p['checkpoint']}, {p['left']} vs {p['right']}: {p['left']}-only passes: {', '.join(p['left_only']) or 'none'}; {p['right']}-only passes: {', '.join(p['right_only']) or 'none'}.")
lines += ['','Other checkpoint pairs have identical pass/fail sets. Full failed-test identities and external-access evidence are recorded in comparison.json.','', '## Verification and external access','',
 'All 15 native transcripts have distinct conversation IDs and verify gpt-6-astra, the designated effort, exact user prompts, and stock model instructions. Per-checkpoint offline request captures also verify effort and absence of a max_output_tokens override. All three manifests have the same protocol hash. Installed skills and memory are disabled; source persists across fresh checkpoint conversations.']
for effort,r in rows.items():
    events=[e for c in r['checkpoints'] for e in c['external_access']['events']]
    statuses=sorted({c['external_access']['status'] for c in r['checkpoints']})
    lines += ['',f"{effort}: {len(events)} recorded external/package operations; audit statuses: {', '.join(statuses)}."]
lines += ['','Only package-install operations for tree-sitter and its language grammars were observed (low 3, medium 3, high 2); no benchmark or solution access was observed. The inventory is based on recorded tool calls and outputs, not a complete network capture. External access is reported for human judgment; no run was stopped for it.','', '## Reproduction and limits','',
 'Run configuration: configs/batches/20260928-astra-efforts.json. Assign fresh batch/run IDs, then run python3.12 scripts/scb_batch.py CONFIG --run --jobs 3 --tmux-session NAME. Regenerate this report with python3.12 scripts/report_astra_efforts.py. Raw transcripts and controller logs remain in intermediate/runs/<run-id>; grading and receipts remain in results/runs/<run-id>.','',
 'Codex CLI 0.158.0; five sequential code_search checkpoints; current spec only; no review; default output limit; 1800 seconds per checkpoint; network enabled; cumulative grading after the whole chain. Dataset and runner pins are recorded in each manifest. This newer dataset has 47 tests at CP3, versus 44 in the paper. This is an effort comparison on one task, not held-out skill learning or paper replication.','',
 'Costs are the harness API-equivalent estimates ($10/$1/$50 per million uncached input/cached input/output tokens), not incremental subscription charges. Aggregated usage does not reconstruct any per-request pricing tiers. Model time sums session elapsed time and excludes grading; concurrent execution can affect timing. No timeout costs are missing and no retries were made.','']
(OUT/'RESULTS.md').write_text('\n'.join(lines))
register_runs([{'run_id':r['run_id'],'report':str((OUT/'RESULTS.md').relative_to(BASE))} for r in rows.values()])
print(json.dumps({k:{x:r[x] for x in ['seconds','cost','usage']} for k,r in rows.items()},indent=2))
print(json.dumps([p for p in paired if p['left_only'] or p['right_only']],indent=2))
for effort,r in rows.items():
 for c in r['checkpoints']:
  for e in c['external_access']['events']:print(effort,c['checkpoint'],e['kind'],e.get('requested_urls'),e['action_excerpt'][:230])
