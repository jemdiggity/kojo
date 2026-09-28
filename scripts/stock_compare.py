"""2026-09-28 authorized four-condition stock-Codex SCB comparison (14 sessions)."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

base=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--run',action='store_true',help='Execute the authorized batch; otherwise print its plan')
a=p.parse_args()
luna='20260928-code-search-luna-stock-01'
plans=[
 [luna,'--no-review'],
 ['20260928-code-search-luna-review-stock-01','--source-run',luna],
 ['20260928-code-search-astra-stock-01','--build-model','gpt-6-astra','--no-review'],
 ['20260928-code-search-astra-review-stock-01','--source-run',luna,'--review-model','gpt-6-astra'],
]
for plan in plans:
 cmd=[sys.executable,'-u','-m','kojo.factory','run','--run-id',*plan,'--monitor-only','--seconds-per-session','300']
 print(' '.join(cmd),flush=True)
 if a.run:subprocess.run(cmd,cwd=base,env={**os.environ,'PYTHONPATH':str(base/'src')},check=True)
