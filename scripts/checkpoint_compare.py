"""Fresh four-condition, 10-minute checkpoint-factory comparison (40 sessions max)."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parents[1]
PLANS = [
    ('20260928-code-search-luna-10m-01', ['--no-review']),
    ('20260928-code-search-luna-review-10m-01', []),
    ('20260928-code-search-astra-10m-01', ['--build-model', 'gpt-6-astra', '--no-review']),
    ('20260928-code-search-astra-review-10m-01', ['--review-model', 'gpt-6-astra']),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Spend subscription usage; default prints commands only')
    args = parser.parse_args()
    sys.path.insert(0, str(BASE/'src'))
    from kojo.catalog import protocol_digest
    protocol = protocol_digest()
    for rid, _ in PLANS:
        if args.run and ((BASE/'results/runs'/rid).exists() or (BASE/'intermediate/runs'/rid/'gauntlet/ledger.json').exists()):
            raise RuntimeError(f'Run ID already used: {rid}; refusing partial resume')
    for rid, flags in PLANS:
        if protocol_digest() != protocol:
            raise RuntimeError('Common harness changed during comparison')
        cmd = [sys.executable, '-u', '-m', 'kojo.factory', 'run', '--run-id', rid,
               '--seconds-per-session', '600', '--review-scope', 'checkpoint', '--monitor-only', *flags]
        print(' '.join(cmd), flush=True)
        if args.run:
            subprocess.run(cmd, cwd=BASE, env={**os.environ, 'PYTHONPATH': str(BASE/'src')}, check=True)
            manifest = json.loads((BASE/'results/runs'/rid/'manifest.json').read_text())
            if manifest['protocol_sha256'] != protocol or manifest['source_run'] is not None:
                raise RuntimeError('Run violated common-harness/fresh-source protocol')
    if args.run:
        print('All four fresh conditions completed.', flush=True)


if __name__ == '__main__':
    main()
