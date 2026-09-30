"""Rank runs by partial pass (mean of each build checkpoint's passed/total) and strict checkpoints.
Usage: scb_rank.py PREFIX [ROLE=build]  (reads $KOJO_DATA_DIR/results/runs/PREFIX*/scores.json)"""
import json, os, sys
from pathlib import Path
root = Path(os.environ.get('KOJO_DATA_DIR') or Path(__file__).resolve().parents[1]) / 'results/runs'
role = sys.argv[2] if len(sys.argv) > 2 else 'build'
rows = []
for d in sorted(root.glob(sys.argv[1] + '*')):
    f = d / 'scores.json'
    if not f.exists():
        continue
    s = [x for x in json.loads(f.read_text()) if x.get('role') == role]
    if s:
        rows.append((sum(x['fraction'] for x in s) / len(s), sum(x['strict'] for x in s), len(s), d.name,
                     ' '.join(f"{x['passed']}/{x['total']}" for x in s)))
for p, st, n, name, cps in sorted(rows, reverse=True):
    print(f'{p:6.1%} strict {st}/{n}  {name}\n        {cps}')
