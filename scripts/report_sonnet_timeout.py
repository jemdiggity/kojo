"""Report an incomplete Sonnet trajectory from its frozen configuration and receipts."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'src'))
from kojo.registry import register_runs
from kojo.external_access import audit_external_sources
from kojo.gauntlet import hashes


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    root = BASE / 'results/runs' / args.run_id
    plan = read(root / 'experiment-plan.json')
    assert plan['run_id'] == args.run_id
    assert (root / 'STOPPED.json').exists(), 'Only report a stopped run'
    data = BASE / 'intermediate/runs' / args.run_id / 'gauntlet/training-build/code_search'
    scores = read(root / 'scores.json')
    stopped = read(root / 'STOPPED.json')
    records, audits, analyses, links = [], [], [], []
    lines = [f"# Sonnet 4.6 {plan['effort']}: incomplete trajectory", '',
             f"The chain stopped: {stopped['reason']}. No incomplete source was carried into the next checkpoint. Only completed checkpoints were graded.", '',
             '| Checkpoint | Result | Input (cached) | Output | Minutes | API-equivalent USD |',
             '|---|---|---:|---:|---:|---:|']
    for n in range(1, plan['checkpoints'] + 1):
        raw = data / f'checkpoint_{n}'
        if not (raw / 'run.json').exists():
            lines.append(f'| {n} | Not started | — | — | — | — |')
            continue
        record = read(raw / 'run.json')
        records.append(record)
        usage = record.get('usage') or {}
        score = next((s for s in scores if s['checkpoint'] == n), None)
        result = f"{score['passed']}/{score['total']} passed" if score else f"{record['status']}; unscored"
        cost = record.get('api_price_equivalent_usd')
        lines.append(f"| {n} | {result} | {usage.get('input_tokens', 'unknown')} ({usage.get('cached_input_tokens', 'unknown')}) | {usage.get('output_tokens', 'unknown')} | {record['elapsed_seconds']/60:.2f} | {cost if cost is not None else 'unknown'} |")
        if (raw / 'transcript.jsonl').exists():
            audits.append({'checkpoint': n, **audit_external_sources(raw / 'transcript.jsonl')})
        links.append(f'- CP{n}: [native transcript]({raw}/transcript.jsonl), [stream]({raw}/events.jsonl).')
        if record['status'] == 'complete':
            continue
        rows = []
        malformed = 0
        for line in (raw / 'events.jsonl').read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                malformed += 1
        calls = [c for r in rows if isinstance(r.get('message'), dict)
                 for c in r['message'].get('content', []) if isinstance(c, dict) and c.get('type') == 'tool_use']
        source = raw / 'interrupted-source'
        prior = root / 'build' / f'checkpoint_{n-1}' / 'submission'
        analysis = {
            'checkpoint': n, 'status': record['status'], 'seconds': record['elapsed_seconds'],
            'tool_calls': dict(Counter(c['name'] for c in calls)),
            'permission_denials': sum(r.get('subtype') == 'permission_denied' for r in rows),
            'native_output_limit_continuations': sum(r.get('type') == 'user' and 'Output token limit hit.' in json.dumps(r.get('message', {})) for r in rows),
            'estimated_streamed_thinking_tokens': sum(r.get('estimated_tokens_delta', 0) for r in rows if r.get('subtype') == 'thinking_tokens'),
            'source_identical_to_prior_checkpoint': hashes(source) == hashes(prior) if source.exists() and prior.exists() else None,
            'final_usage': record.get('usage'), 'malformed_stream_lines': malformed,
            'limitations': 'Streamed thinking token counts are estimates, not final billed usage. Empty thinking blocks do not reveal reasoning content.',
        }
        analyses.append(analysis)
    known = sum(r.get('api_price_equivalent_usd') or 0 for r in records)
    unknown = sum(r.get('api_price_equivalent_usd') is None for r in records)
    lines += ['', f'Known API-equivalent cost within this trajectory: ${known:.4f}; {unknown} session(s) have unknown final cost. This is not measured Claude Max billing. Earlier attempts are separate and excluded. No usage cap was applied.', '', '## Incomplete checkpoint evidence', '']
    for a in analyses:
        lines.append(f"CP{a['checkpoint']}: {a['tool_calls']}; {a['permission_denials']} native permission denials; {a['native_output_limit_continuations']} stock output-limit continuations; {a['estimated_streamed_thinking_tokens']:,} estimated streamed thinking tokens. Source identical to prior checkpoint: {a['source_identical_to_prior_checkpoint']}. Thinking text is not available, so this does not establish what the model was reasoning about.")
    lines += ['', '## Configuration and limits', '',
              f"CLI {plan['cli_version']}; {plan['model']}; effort {plan['effort']}; {plan['seconds_per_session']//60} minutes per checkpoint; output-token override {plan.get('max_output_tokens', 'unset (observed default 32,000)')}. Fresh conversations, stock system prompt, current checkpoint specification, no learned skills or review. Network access enabled; external access reported for human assessment.", '',
              plan.get('intervention', 'No response-limit intervention configured.'), '',
              f"External-access inventory: {sum(len(a['events']) for a in audits)} network-capable operations; {sum(bool(a.get('review_suggested')) for a in audits)} sessions flagged for human review. This heuristic transcript inventory is not a complete network log or proof of no contamination.", '',
              'The SCB paper used Sonnet 4.6 high, Claude Code 2.1.44, and a two-hour checkpoint limit. This Dockerless, single-problem trajectory is not a paper replication. Unscored checkpoints cannot establish model performance. [Paper](https://arxiv.org/html/2603.24755v1).', '',
              '[Frozen configuration](experiment-plan.json) · [Accounting](accounting.json) · [External access](external-access.json) · [Manifest](manifest.json) · [Transcript analysis](TIMEOUT-ANALYSIS.json).', '',
              f'Rebuild this report: `python3.12 scripts/report_sonnet_timeout.py --run-id {args.run_id}`. To reproduce inference, copy the frozen configuration to the launcher configuration, choose a new run ID, and run `python3.12 scripts/sonnet_baseline.py --run`. This consumes provider usage.']
    save(root / 'TIMEOUT-ANALYSIS.json', analyses)
    save(root / 'external-access.json', audits)
    (root / 'RESULTS.md').write_text('\n'.join(lines) + '\n')
    (root / 'TRANSCRIPTS.md').write_text('# Captured transcripts\n\n' + '\n'.join(links) + '\n')
    register_runs([{'run_id': args.run_id, 'results': str(root.relative_to(BASE)), 'intermediate': f'intermediate/runs/{args.run_id}', 'report': f'results/runs/{args.run_id}/RESULTS.md', 'logs': f'results/runs/{args.run_id}/TRANSCRIPTS.md'}])
    print('\n'.join(lines[:12]))


if __name__ == '__main__':
    main()
