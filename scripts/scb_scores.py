"""Per-session scores of finished runs as a compact diff: -tests that broke / +tests now passing."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from kojo.catalog import DATA_ROOT


def base(name):
    return re.sub(r'\[.*', '', name)


def report(run, failures=False):
    """One line per graded session, in the order they ran."""
    path = Path(run) if Path(run).is_dir() else DATA_ROOT / 'results/runs' / run
    scores = json.loads((path / 'scores.json').read_text())
    print(f'{path.name}')
    print(f"  {'session':22} {'passed':>9}  -broken / +gained")
    before = set()  # Tests passing after the previous session.
    for score in scores:
        label = score.get('label', f"checkpoint_{score['checkpoint']}")
        report = json.loads((path / score['role'] / label / 'evaluation.json').read_text())
        # A test is Core/Functionality/Error in its own checkpoint but Regression later; match by checkpoint and name.
        passed = {(g.split('-')[0], t) for g, r in report['tests'].items() for t in r['passed']}
        failed = {(g, t) for g, r in report['tests'].items() for t in r['failed']}
        broken = sorted(f for f in failed if (f[0].split('-')[0], f[1]) in before)
        gained = passed - before
        cell = lambda c: f"{c['passed']}/{c['total']}"
        print(f"  {score['role'] + ' ' + label:22} {cell(score):>9}  -{len(broken)} / +{len(gained)}")
        if failures:
            for title, tests in (('new failures', [f for f in sorted(failed) if f[0].startswith(f"checkpoint_{score['checkpoint']}-")]),
                                 ('regression failures', [f for f in sorted(failed) if not f[0].startswith(f"checkpoint_{score['checkpoint']}-")]),
                                 ('broken (passed before)', broken)):
                names = sorted({f'{g}: {base(t)}' for g, t in tests})
                if names:
                    print(f'      {title} ({len(tests)} tests): ' + ('; '.join(names[:12]) + (' ...' if len(names) > 12 else '')))
        before = passed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+', help='Run IDs (under the data root) or run directories')
    parser.add_argument('--failures', action='store_true', help='Also name the failing tests, grouped')
    args = parser.parse_args(argv)
    for run in args.runs:
        report(run, args.failures)


if __name__ == '__main__':
    main()
