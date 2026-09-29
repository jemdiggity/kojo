"""Run independent SCB factories concurrently; checkpoints remain sequential."""
import argparse
from collections import deque
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

from kojo.catalog import BASE, DATA_ROOT, protocol_digest
from kojo.execution import save
from kojo.factory import parse_args
from kojo.registry import register_runs


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', value):
        raise ValueError('IDs must contain lowercase letters, digits, and hyphens')
    return value


def load_plan(path):
    plan = json.loads(Path(path).read_text())
    if not isinstance(plan,dict) or set(plan)-{'batch_id','max_parallel','runs','description'}:
        raise ValueError('Unknown batch fields; expected batch_id, max_parallel, runs, description')
    identifier(plan['batch_id'])
    if not isinstance(plan.get('runs'), list) or not plan['runs']:
        raise ValueError('Provide a nonempty runs list')
    jobs = plan.get('max_parallel', 2)
    if type(jobs) is not int or jobs < 1:
        raise ValueError('max_parallel must be a positive integer')
    seen = set()
    for run in plan['runs']:
        if not isinstance(run,dict) or set(run)-{'run_id','factory_args','description'} or 'factory_args' not in run:
            raise ValueError('Each run needs run_id and factory_args; description is optional')
        rid = identifier(run['run_id'])
        if rid in seen:
            raise ValueError(f'Duplicate run ID: {rid}')
        seen.add(rid)
        flags = run.get('factory_args', [])
        if not isinstance(flags, list) or not all(isinstance(x, str) for x in flags):
            raise ValueError('factory_args must be an array of CLI arguments')
        if any(x.startswith('--run-id') for x in flags):
            raise ValueError('Set run_id separately from factory_args')
        try:
            args, _, _ = parse_args(['run', '--run-id', rid, *flags])
        except SystemExit as error:
            raise ValueError(f'Invalid factory arguments for {rid}') from error
        if args.run_id != rid:
            raise ValueError('factory_args cannot override run_id')
    return plan


def commands(plan, action):
    result = []
    for run in plan['runs']:
        # Audits never consume the IDs reserved for the subsequent paid batch.
        rid = run['run_id'] if action == 'run' else f"{plan['batch_id']}-{run['run_id']}-audit"
        result.append((rid, [sys.executable, '-u', '-m', 'kojo.factory', action,
                             '--run-id', rid, *run.get('factory_args', [])]))
    return result


def prepare_tmux(session):
    if not session:
        return
    identifier(session)
    if not shutil.which('tmux'):
        raise RuntimeError('tmux is not installed')
    if subprocess.run(['tmux', 'has-session', '-t', session], capture_output=True).returncode:
        subprocess.run(['tmux', 'new-session', '-d', '-s', session], check=True)


def log_window(session, rid, path):
    if session:
        subprocess.run(['tmux', 'new-window', '-d', '-t', session, '-n', rid,
                        shlex.join(['tail', '-n', '+1', '-F', str(path)])], check=True)


def execute(plan, batch_dir, jobs, *, action='run', base=None, data=None, tmux_session=None,
            command_list=None, expected_protocol=None):
    """Bounded process scheduler. command_list enables real-process offline tests."""
    # Code and working directory come from `base` (the worktree); run output goes to `data`.
    # Tests that pass only `base` keep everything under it.
    data = Path(data) if data else (Path(base) if base else DATA_ROOT)
    base = Path(base or BASE)
    command_list = commands(plan, action) if command_list is None else command_list
    if jobs < 1:
        raise ValueError('jobs must be positive')
    # Hold every run lock, including queued runs, until the batch is finished.
    # Another batch/single-run launcher cannot reserve the same ID concurrently.
    with contextlib.ExitStack() as stack:
        for rid, _ in command_list:
            root = data / 'intermediate/runs' / rid
            root.mkdir(parents=True, exist_ok=True)
            lock = stack.enter_context((root / 'launcher.lock').open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if (root/'controller.log').exists() or (root/'gauntlet/ledger.json').exists() or (data/'results/runs'/rid).exists():
                raise RuntimeError(f'Run ID already used: {rid}')
        batch_dir = Path(batch_dir)
        batch_dir.mkdir(parents=True, exist_ok=False)
        save(batch_dir/'plan.json', {**plan,'max_parallel':jobs})
        save(batch_dir/'commands.json', [{'run_id':rid, 'argv':cmd} for rid,cmd in command_list])
        states = {rid: {'status':'queued', 'command':cmd} for rid,cmd in command_list}
        pending = deque(command_list)
        active = {}
        cancelled = False
        failure = None

        def snapshot():
            save(batch_dir/'status.json', {'action':action, 'max_parallel':jobs,
                                          'cancelled':cancelled, 'runs':states})

        def cancel(signum, frame):
            nonlocal cancelled
            cancelled = True
            for process, _ in active.values():
                if process.poll() is None:
                    try:
                        process.send_signal(signal.SIGINT)
                    except ProcessLookupError:
                        pass

        previous_handlers = {sig:signal.signal(sig,cancel) for sig in (signal.SIGINT,signal.SIGTERM)}
        snapshot()
        try:
            while pending or active:
                if expected_protocol and protocol_digest() != expected_protocol and not cancelled:
                    failure = RuntimeError('Harness changed during batch')
                    cancel(None, None)
                while pending and len(active) < jobs and not cancelled:
                    rid, cmd = pending.popleft()
                    root = data/'intermediate/runs'/rid
                    record = {'run_id':rid, 'batch_id':plan['batch_id'], 'action':action,
                              'command':cmd, 'protocol_sha256':expected_protocol,
                              'plan':next((p for p in plan['runs'] if p['run_id']==rid or f"{plan['batch_id']}-{p['run_id']}-audit"==rid), None)}
                    save(root/'run-config.json',record)
                    log = (root/'controller.log').open('x')
                    try:
                        log_window(tmux_session,rid,root/'controller.log')
                        process = subprocess.Popen(cmd, cwd=base,
                            env={**os.environ,'PYTHONPATH':str(base/'src')},
                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
                    except Exception:
                        log.close()
                        states[rid].update(status='launch_failed',finished_at=time.time())
                        raise
                    active[rid] = process,log
                    if cancelled:
                        process.send_signal(signal.SIGINT)
                    states[rid].update(status='running',pid=process.pid,started_at=time.time())
                    print(f'[{rid}] started; log: {root / "controller.log"}',flush=True)
                    snapshot()
                for rid, (process,log) in list(active.items()):
                    code = process.poll()
                    if code is None:
                        continue
                    log.close()
                    del active[rid]
                    states[rid].update(status='cancelled' if cancelled else ('complete' if code==0 else 'failed'),
                                       exit_code=code,finished_at=time.time())
                    root=data/'intermediate/runs'/rid
                    save(root/'launcher-exit.json',{'exit_code':code})
                    output=data/'results/runs'/rid
                    if output.exists():
                        shutil.copy2(root/'run-config.json',output/'run-config.json')
                        register_runs([{'run_id':rid,'results':f'results/runs/{rid}',
                                        'intermediate':f'intermediate/runs/{rid}',
                                        'batch_id':plan['batch_id']}],data)
                    print(f'[{rid}] {states[rid]["status"]}; exit={code}',flush=True)
                    snapshot()
                if cancelled:
                    while pending:
                        rid,_=pending.popleft()
                        states[rid]['status']='cancelled_before_start'
                    snapshot()
                if active:
                    time.sleep(0.1)
        except BaseException as error:
            failure = error
            cancel(None,None)
        finally:
            # Controllers catch SIGINT and terminate their model/grading children.
            # Wait for cleanup rather than abandoning detached inference processes.
            for rid,(process,log) in active.items():
                code=process.wait()
                log.close()
                states[rid].update(status='cancelled',exit_code=code,finished_at=time.time())
                save(data/'intermediate/runs'/rid/'launcher-exit.json',{'exit_code':code})
            for rid,_ in pending:
                states[rid]['status']='cancelled_before_start'
            snapshot()
            for sig,handler in previous_handlers.items():
                signal.signal(sig,handler)
        if failure:
            raise failure
        return 130 if cancelled else int(any(s['status']!='complete' for s in states.values()))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--run',action='store_true',help='Launch paid/model-usage runs; default prints only')
    mode.add_argument('--audit',action='store_true',help='Concurrent native CLI checks against dummy endpoints; no inference')
    parser.add_argument('--jobs',type=int,help='Override max_parallel')
    parser.add_argument('--tmux-session',help='Create per-run log windows in this tmux session')
    args=parser.parse_args(argv)
    plan=load_plan(args.plan)
    jobs=args.jobs if args.jobs is not None else plan.get('max_parallel',2)
    if jobs<1:
        parser.error('--jobs must be positive')
    action='audit' if args.audit else 'run'
    for rid,cmd in commands(plan,action):
        print(f'[{rid}] {shlex.join(cmd)}',flush=True)
    if not (args.run or args.audit):
        print(f'Dry run only. Up to {jobs} independent factories; checkpoints stay sequential.')
        return 0
    prepare_tmux(args.tmux_session)
    directory=BASE/'intermediate/batches'/(plan['batch_id']+('-audit' if args.audit else ''))
    return execute(plan,directory,jobs,action=action,tmux_session=args.tmux_session,
                   expected_protocol=protocol_digest())


if __name__=='__main__':
    raise SystemExit(main())
