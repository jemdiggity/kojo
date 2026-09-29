"""Launch a frozen Sonnet plan; print-only unless --run is supplied."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys

BASE=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--config',type=Path,default=BASE/'configs/experiments/sonnet-46-baseline.json')
    args=parser.parse_args()
    plan=json.loads(args.config.read_text())
    cmd=[sys.executable,'-u','-m','kojo.factory','run','--run-id',plan['run_id'],
         '--build-model',plan['model'],'--claude-effort',plan['effort'],
         '--seconds-per-session',str(plan['seconds_per_session']),'--no-review']
    for key,flag in [('max_output_tokens','--claude-max-output-tokens'),
                     ('max_budget_usd_per_session','--claude-max-budget-usd')]:
        if plan.get(key) is not None:
            cmd += [flag,str(plan[key])]
    if plan.get('resume_run'):
        cmd+=['--resume-run',plan['resume_run'],'--resume-checkpoint',str(plan['resume_checkpoint'])]
    sys.path.insert(0,str(BASE/'src'))
    from kojo.factory import parse_args
    parse_args(cmd[4:])
    print(shlex.join(cmd),flush=True)
    if not args.run:return
    if not plan['approval_status'].startswith('approved'):raise RuntimeError('Run not approved')
    run=BASE/'intermediate/runs'/plan['run_id']
    run.mkdir(parents=True,exist_ok=True)
    with (run/'launcher.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        output=BASE/'results/runs'/plan['run_id']
        if output.exists() or (run/'controller.log').exists():
            raise RuntimeError('Run ID already used')
        (run/'experiment-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
        with (run/'controller.log').open('x') as log:
            process=subprocess.Popen(cmd,cwd=BASE,env={**os.environ,'PYTHONPATH':str(BASE/'src')},
                                     stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
            def cancel(signum,frame):
                if process.poll() is None:process.send_signal(signal.SIGINT)
            signal.signal(signal.SIGINT,cancel)
            signal.signal(signal.SIGTERM,cancel)
            for line in process.stdout:
                print(line,end='',flush=True);log.write(line);log.flush()
            code=process.wait()
            (run/'launcher-exit.json').write_text(json.dumps({'exit_code':code})+'\n')
            if output.exists():
                (output/'experiment-plan.json').write_text((run/'experiment-plan.json').read_text())
            raise SystemExit(code)


if __name__=='__main__':main()
