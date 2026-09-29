"""Inventory Sonnet attempts without double-counting sessions copied by restarts."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main():
    roots = sorted((BASE / 'results/runs').glob('20260928-code-search-sonnet46-*'))
    sessions = {}
    rows = []
    for root in roots:
        raw = BASE / 'intermediate/runs' / root.name / 'gauntlet/training-build/code_search'
        paths = sorted(raw.glob('checkpoint_*/run.json'))
        if not paths:
            paths = sorted(root.glob('build/checkpoint_*/run.json'))
        fresh, reused = [], []
        for path in paths:
            record = json.loads(path.read_text())
            identity = record['session_id']
            if identity in sessions:
                assert sessions[identity]['record'] == record, 'Copied session receipt changed'
                reused.append(identity)
                continue
            sessions[identity] = {'record': record, 'run_id': root.name, 'checkpoint': int(path.parent.name.split('_')[-1])}
            fresh.append(record)
        known = sum(r.get('api_price_equivalent_usd') or 0 for r in fresh)
        unknown = sum(r.get('api_price_equivalent_usd') is None for r in fresh)
        rows.append({'run_id': root.name, 'new_sessions': len(fresh), 'reused_sessions': len(reused),
                     'known_api_equivalent_usd': known, 'unknown_cost_sessions': unknown,
                     'statuses': [r['status'] for r in fresh]})
    out = BASE / 'results/comparisons/20260928-sonnet-attempts'
    out.mkdir(parents=True, exist_ok=True)
    known = sum(r['known_api_equivalent_usd'] for r in rows)
    unknown = sum(r['unknown_cost_sessions'] for r in rows)
    result = {'runs': rows, 'unique_sessions': sessions, 'known_api_equivalent_usd': known,
              'unknown_cost_sessions': unknown, 'billing_basis': 'API-equivalent; subscription cash charges unknown'}
    (out / 'accounting.json').write_text(json.dumps(result, indent=2) + '\n')
    lines = ['# Sonnet attempt history', '',
             'Restarts copy earlier session receipts. This inventory counts each session UUID once, including infrastructure failures and interrupted attempts.', '',
             '| Run | New / reused sessions | New session outcomes | Known API-equivalent USD | Unknown-cost sessions |',
             '|---|---:|---|---:|---:|']
    for row in rows:
        rid = row['run_id']
        lines.append(f"| [{rid}](../../runs/{rid}/RESULTS.md) | {row['new_sessions']} / {row['reused_sessions']} | {', '.join(row['statuses'])} | {row['known_api_equivalent_usd']:.4f} | {row['unknown_cost_sessions']} |")
    lines += ['', f'Known cost across unique recorded sessions: **${known:.4f}**, plus **{unknown} sessions with unknown final cost**. This is not total subscription billing.', '',
              'These were exploratory retries with different effort, time limits, and response allowances. They are not independent repetitions of one fixed condition. Earlier grading was never inserted into subsequent model prompts. The final trajectory retains its original session identities and restart provenance.', '',
              'No skill-learning loop was run in this phase. These attempts do not support a skill-learning break-even estimate.', '',
              'Rebuild with `python3.12 scripts/report_sonnet_history.py`. [Detailed accounting](accounting.json).']
    (out / 'RESULTS.md').write_text('\n'.join(lines) + '\n')
    print(f'{len(sessions)} unique sessions; known ${known:.4f}; {unknown} unknown-cost sessions')


if __name__ == '__main__':
    main()
