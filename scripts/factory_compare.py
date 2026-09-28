"""Run the explicitly authorized, 14-session factory comparison serially."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

base=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--run',action='store_true',help='Spend subscription usage; otherwise only print the plan')
a=p.parse_args()
if a.run:
    p.error('This historical comparison was canceled. Do not resume; authorize new runs with new IDs.')
luna='20260927-code-search-factory-02'
plans=[
 [luna],
 ['20260927-code-search-astra-01','--build-model','gpt-6-astra','--no-review'],
 ['20260927-code-search-astra-review-01','--source-run',luna,'--review-model','gpt-6-astra'],
]
for plan in plans:
 cmd=[sys.executable,'-u','-m','kojo.factory','run','--run-id',*plan,'--monitor-only']
 print(' '.join(cmd),flush=True)
 if a.run:
  subprocess.run(cmd,cwd=base,env={**os.environ,'PYTHONPATH':str(base/'src')},check=True)
