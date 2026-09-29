"""Reproduce the requested high-effort baseline comparison from frozen receipts."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kojo.catalog import BASE
from kojo.registry import register_runs

OUT = BASE / 'results/comparisons/20260928-opus55-sol56-high'
OUT.mkdir(parents=True, exist_ok=True)
rows = {}
for tag, model in [('opus55', 'claude-opus-5-5'), ('sol56', 'gpt-5.6-sol')]:
    rid = f'20260928-code-search-{tag}-high-default-01'
    root = BASE / 'results/runs' / rid
    raw = BASE / 'intermediate/runs' / rid / 'gauntlet/training-build/code_search'
    checks = []
    sessions = []
    for n in range(1, 6):
        p = root / f'build/checkpoint_{n}'
        read = lambda name: json.loads((p / name).read_text())
        run = read('run.json'); grade = read('evaluation.json')
        verify = read('transcript-verification.json'); external = read('external-access.json')
        assert run['status'] == 'complete' and run['model'] == model and run['reasoning'] == 'high'
        if tag == 'opus55':
            assert verify['model'] == model and verify['reasoning'] == 'high'
            assert verify['exact_user_prompt'] and verify['stock_prompt_snapshot']
            session = verify['session_id']
        else:
            assert verify['exact_user_prompt_in_session'] and verify['stock_base_instructions_present']
            contexts = [json.loads(line)['payload'] for line in (raw / f'checkpoint_{n}/transcript.jsonl').open()
                        if json.loads(line).get('type') == 'turn_context']
            assert contexts and all(c['model'] == model and c['effort'] == 'high' for c in contexts)
            session = verify['thread_id']
        sessions.append(session)
        passed = []; failed = []
        for group, tests in grade['tests'].items():
            cp = group.split('-')[0]
            passed += [f'{cp}::{t}' for t in tests['passed']]
            failed += [f'{cp}::{t}' for t in tests['failed']]
            assert not tests['skipped']
        checks.append(dict(checkpoint=n, passed=len(passed), total=len(passed)+len(failed),
            passed_tests=passed, failed_tests=failed, usage=run['usage'],
            seconds=run['elapsed_seconds'], cost=run['api_price_equivalent_usd'],
            session_id=session, external_access=external))
    assert len(set(sessions)) == 5
    rows[tag] = dict(run_id=rid, model=model, checkpoints=checks,
        seconds=sum(c['seconds'] for c in checks), cost=sum(c['cost'] for c in checks),
        usage={k:sum(c['usage'].get(k, 0) or 0 for c in checks)
               for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']})
paired = []
for a, b in zip(rows['opus55']['checkpoints'], rows['sol56']['checkpoints']):
    assert set(a['passed_tests']+a['failed_tests']) == set(b['passed_tests']+b['failed_tests'])
    paired.append(dict(checkpoint=a['checkpoint'], opus_only=sorted(set(a['passed_tests'])-set(b['passed_tests'])),
        sol_only=sorted(set(b['passed_tests'])-set(a['passed_tests'])), both_failed=sorted(set(a['failed_tests'])&set(b['failed_tests']))))
(OUT/'comparison.json').write_text(json.dumps(dict(runs=rows, paired=paired), indent=2)+'\n')
lines = ['# Opus 5.5 high vs Sol 5.6 high: code_search', '',
 'Both runs completed all five checkpoints without timeout or retry. Both finish at 95/104; Opus passes one extra test at CP3 and CP4. This is one trajectory per model, not evidence of a general model ranking.', '',
 '| Checkpoint | Opus passed | Sol passed | Opus minutes | Sol minutes | Opus USD | Sol USD |',
 '|---|---:|---:|---:|---:|---:|---:|']
for a,b in zip(rows['opus55']['checkpoints'],rows['sol56']['checkpoints']):
    lines.append(f"| CP{a['checkpoint']} | {a['passed']}/{a['total']} | {b['passed']}/{b['total']} | {a['seconds']/60:.2f} | {b['seconds']/60:.2f} | {a['cost']:.4f} | {b['cost']:.4f} |")
lines += ['', '| Model | Input tokens (cached included) | Cached input | Output tokens | Model minutes | API-equivalent USD |', '|---|---:|---:|---:|---:|---:|']
for r in rows.values():
    u=r['usage'];lines.append(f"| {r['model']} | {u['input_tokens']:,} | {u['cached_input_tokens']:,} | {u['output_tokens']:,} | {r['seconds']/60:.2f} | {r['cost']:.4f} |")
lines += ['', 'Costs describe API-equivalent usage, not additional subscription charges. Sol uses standard-context token rates ($4/$0.40/$20 per million input/cached/output); this aggregate estimate does not reconstruct possible long-context premiums. Claude cost is the native CLI-reported amount. Time is the sum of model-session elapsed times; runs overlapped.', '', '## Paired differences']
for p in paired:
    lines += ['', f"CP{p['checkpoint']}: Opus-only passes: {', '.join(p['opus_only']) or 'none'}. Sol-only passes: {', '.join(p['sol_only']) or 'none'}."]
lines += ['', 'Full failed-test identities, token counts per checkpoint, and external-access evidence are in comparison.json.', '', '## Transcript and external-source audit', '',
 'All ten captured sessions match the requested model and high effort, contain the exact checkpoint prompt and stock system instructions, and have distinct conversation IDs. Offline request audits confirm Opus defaults to 128000 output tokens with adaptive thinking, while Sol sends no max_output_tokens override. Installed skills and memory are disabled. Source carries forward; checkpoint conversations are fresh.', '',
 'No benchmark/source-solution access was observed in the recorded external-access inventory. Recorded external targets were PyPI/package downloads for tree-sitter and its language grammars. Some scanner entries labelled search are shell queries to PyPI metadata, not web searches for benchmark answers. This is transcript evidence, not a complete network capture.', '',
 'Dependency installation encountered certificate errors and agents worked around them with curl/wheels or CA settings. Opus also listed the shared Claude temporary-directory parent while diagnosing certificates; directory names from other local Claude sessions appeared. This is a filesystem-isolation limitation; no other session contents or benchmark solutions were observed in that recorded action. Do not describe this run as perfectly isolated from all host metadata.', '',
 '## Reproduction and limitations', '',
 'Configuration: configs/batches/20260928-opus55-sol56-high.json. Run with python3.12 scripts/scb_batch.py CONFIG --run --jobs 2 --tmux-session NAME after assigning unused batch/run IDs. Rebuild this report with python3.12 scripts/report_opus_sol.py.', '',
 '30 minutes per checkpoint; no review; network enabled; current checkpoint spec only; cumulative grading after each complete chain. No learning or skill revision is involved. Same dataset and harness between these runs; provider CLIs differ (Claude 2.1.283, Codex 0.158.0). This dataset is newer than the paper: CP3 contains 47 tests rather than 44, so this is not a paper replication. No randomness repeats were run.', '']
(OUT/'RESULTS.md').write_text('\n'.join(lines))
register_runs([{'run_id':r['run_id'],'report':str((OUT/'RESULTS.md').relative_to(BASE))} for r in rows.values()])
print(json.dumps({k:{x:r[x] for x in ['seconds','cost','usage']} for k,r in rows.items()},indent=2))
print(json.dumps(paired,indent=2))
