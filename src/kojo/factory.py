"""Bounded checkpoint factories with one independent review/follow-up per checkpoint."""
import argparse
import fcntl
import shutil
import time

from kojo.catalog import BASE, protocol_digest
from kojo.execution import audit, run_session, save, session_paths
from kojo.gauntlet import Experiment, copy_code, hashes, preflight, read
from kojo.run_chain import ChainBackend, compose_prompt


def instructions(backend, role):
    # These are task requests, never replacement Codex base instructions.
    return {
        'build': '',
        'review': 'Review the supplied code against the specifications and give actionable feedback. You may run checks in this disposable copy. Do not implement fixes. Your final response is the review that will be passed to a fresh developer. Identify concrete issues, locations and evidence; distinguish verified defects from suspicions.',
        'fix': 'Follow up on the supplied code review. Inspect the code and specifications, assess the feedback, implement justified fixes, and verify the result. This is the only follow-up; summarize changes and checks.',
    }[role]


def stage_prompt(experiment, role, checkpoint=5, feedback=None):
    from kojo.scb_prompt import render_checkpoint
    if role == 'build':
        return render_checkpoint(experiment.spec('code_search',checkpoint),checkpoint,experiment.b.python)
    # Review/fix are explicitly experimental roles, not native SCB checkpoints.
    # Only public specs through this checkpoint; future specs never reach these roles.
    specs = instructions(None,role) + "\n\n" + "\n\n".join(
        f"# Public checkpoint {n} specification\n"+experiment.spec('code_search',n) for n in range(1,checkpoint+1))
    if role == 'fix':
        if not feedback or not feedback.strip():
            raise ValueError('A completed review is required before follow-up')
        specs += '\n\n# Feedback from the independent reviewer\n' + feedback
    return specs


def review_and_fix(session, checkpoint, source):
    """One review/fix loop for this checkpoint; never inspect official grades."""
    review = session('review', checkpoint, source)
    if read(review/'run.json')['status'] != 'complete':
        raise RuntimeError('Reviewer did not complete; refusing partial review follow-up')
    return session('fix', checkpoint, source, (review/'answer.txt').read_text())/'submission'


def run_checkpoint(session, checkpoint, source, *, review=True):
    """Carry this checkpoint's final factory output into the next build."""
    built = session('build', checkpoint, source)/'submission'
    return review_and_fix(session, checkpoint, built) if review else built


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['audit', 'run'])
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--build-model', choices=['gpt-6-luna','gpt-6-astra'], default='gpt-6-luna')
    parser.add_argument('--review-model', choices=['gpt-6-luna','gpt-6-astra'], default='gpt-6-luna')
    parser.add_argument('--no-review', action='store_true')
    parser.add_argument('--review-scope', choices=['checkpoint','final'], default='checkpoint', help='One review/fix loop per checkpoint (default); final preserves historical runs')
    parser.add_argument('--seconds-per-session', type=int, default=600, help='Time limit for each builder, reviewer, and fixer session (default: 600)')
    parser.add_argument('--source-run', help='Reuse only this run’s frozen final builder source for a paired review')
    parser.add_argument('--monitor-only', action='store_true', help='Explicit user-authorized waiver of the weekly floor for this bounded run')
    args = parser.parse_args(argv)
    if args.seconds_per_session <= 0:
        parser.error('seconds-per-session must be positive')
    if args.source_run and (args.no_review or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.source_run)):
        parser.error('source-run needs a review and a valid run ID')
    if args.source_run and args.review_scope != 'final':
        parser.error('source-run reuses final code only and requires --review-scope final')
    models={'build':args.build_model,'review':args.review_model,'fix':args.build_model}
    if not args.run_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.run_id):
        parser.error('Use lowercase letters, digits and hyphens')
    cfg, manifest = preflight()
    root = BASE / 'intermediate/runs' / args.run_id
    data = root / 'gauntlet'
    output = BASE / 'results/runs' / args.run_id
    backend = ChainBackend(cfg, manifest, data, output)
    experiment = Experiment(backend)
    if args.action == 'audit':
        for role in (('build',) if args.no_review else ('build', 'review', 'fix')):
            probe = root / 'offline-audit' / role
            audit(probe, None, backend.runtime, None, True,
                  stage_prompt(experiment, role, 1 if role == 'build' else 5, 'Offline review placeholder.'), persist=True, model=models[role])
        print('All three role requests and native isolation verified without inference.', flush=True)
        return
    data.mkdir(parents=True, exist_ok=True)
    with (data / 'execution.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if output.exists() or (data / 'ledger.json').exists():
            raise RuntimeError('Run ID already used; no implicit resume or retry')
        output.mkdir(parents=True)
        save(output / 'manifest.json', {
            'run_id':args.run_id, 'problem':'code_search', 'condition':'checkpoint-review-factory' if args.review_scope == 'checkpoint' else 'single-review-factory',
            'pins':cfg, 'protocol_sha256':backend.protocol, 'quota':read(BASE / 'configs/quota.json'),
            'max_sessions':(0 if args.source_run else 5)+(0 if args.no_review else (10 if args.review_scope == 'checkpoint' else 2)), 'seconds_per_session':args.seconds_per_session, 'review_loops':0 if args.no_review else (5 if args.review_scope == 'checkpoint' else 1), 'review_scope':args.review_scope, 'review_loops_per_checkpoint':0 if args.no_review else (1 if args.review_scope == 'checkpoint' else None), 'skills':None,
            'prompt_protocol':'stock-codex-scb-just-solve-v1','builder_specs':'current checkpoint only','base_instructions':'stock Codex; no override','checkpoint_workspace':'persistent directory including virtualenv; fresh CLI conversation','review_specs':'public specs through current checkpoint; custom review intervention','models':models,'reasoning':'low','source_run':args.source_run,'quota_monitor_only':args.monitor_only,
            'sequence':('reused frozen builder' if args.source_run else 'five incremental build checkpoints') + ('' if args.no_review else (', each followed by one review and one fix; fixed code carries forward' if args.review_scope == 'checkpoint' else ', one final review, one follow-up')),
            'grading':'All calls finish or stop before grading; reviewer and fixer never receive official results.',
            'scope':'Exploratory same-task workflow test, not held-out learning or a compute-matched comparison.',
        })
        ledger=[]; frozen=[]; previous=None; failure=None

        def session(role, n, source, feedback=None):
            if protocol_digest() != backend.protocol:
                raise RuntimeError('Protocol changed during run')
            run = data / f'training-{role}/code_search/checkpoint_{n}'
            dest = output / role / f'checkpoint_{n}'
            # Native SCB keeps one workspace/environment across checkpoints.
            # The process/conversation is fresh; its filesystem is not reset.
            shared_work = role == 'build' or (role == 'fix' and args.review_scope == 'checkpoint')
            work = data/'builder-workspace/src' if shared_work else run/'src'
            if shared_work:
                work.mkdir(parents=True,exist_ok=True)
                if role == 'build' and n == 1 and list(work.iterdir()):
                    raise RuntimeError('First builder workspace must be empty')
                if source is not None and hashes(work, exclude_generated=True) != hashes(source):
                    raise RuntimeError('Shared workspace does not match the preceding frozen source')
            else:
                copy_code(source,work)
            dest.mkdir(parents=True)
            save(dest / 'initial-src.json', hashes(source) if source else {})
            prompt = stage_prompt(experiment, role, n, feedback)
            (dest / 'prompt.md').write_text(prompt)
            (dest / 'instructions.md').write_text(instructions(backend, role))
            ledger.append({'role':role, 'checkpoint':n, 'reserved_at':time.time()})
            save(data / 'ledger.json', ledger)
            prior=[sample for p in session_paths(data) if (p.parent/'quota.json').exists() for sample in read(p.parent/'quota.json')]
            print(f'Starting {role} checkpoint {n}', flush=True)
            run_session(run, None, prompt, args.seconds_per_session, backend.runtime,
                        None, prior, isolated_src=True, model=models[role], monitor_only=args.monitor_only, work_path=work)
            for filename in ['run.json','quota.json','verification.json','transcript-verification.json','answer.txt','stock-instructions.md']:
                if filename == 'answer.txt' and not (run/filename).exists():
                    continue  # A timed-out session may have no final answer; preserve its code/receipts.
                shutil.copy2(run/filename, dest/filename)
            if role != 'review':
                copy_code(work,run/'submission')
                shutil.copytree(run/'submission',dest/'submission')
                save(dest/'snapshot.json',hashes(run/'submission'))
                frozen.append({'name':'code_search','checkpoint':n,'run':run,'role':role})
            else:
                save(dest/'source-changes.json',{'before':hashes(source),'after':hashes(work, exclude_generated=True),
                                               'carry_forward':'Only answer.txt; no reviewer workspace changes.'})
            print(f'Finished {role} checkpoint {n}', flush=True)
            return run

        try:
            if args.source_run:
                original=BASE/'results/runs'/args.source_run/'build/checkpoint_5'
                if hashes(original/'submission') != read(original/'snapshot.json'):
                    raise RuntimeError('Reused builder snapshot mismatch')
                previous=original/'submission'
                save(output/'reused-builder.json',{'run_id':args.source_run,'files':hashes(previous)})
            else:
                for n in range(1,6):
                    previous=run_checkpoint(session,n,previous,review=not args.no_review and args.review_scope == 'checkpoint')
            if not args.no_review and args.review_scope == 'final':
                previous=review_and_fix(session,5,previous)
        except BaseException as error:
            failure=error
            save(output/'STOPPED.json',{'reason':str(error),'time':time.time()})
        finally:
            sessions=[read(p) for p in session_paths(data)]
            save(output/'accounting.json',{'sessions':sessions,'sessions_reserved':len(ledger),
                'elapsed_seconds':sum(r.get('elapsed_seconds',0) for r in sessions),
                'known_api_equivalent_usd':sum(r.get('api_price_equivalent_usd') or 0 for r in sessions),
                'unmetered_sessions':sum(r.get('usage') is None for r in sessions),
                'actual_subscription_cash_cost_usd':None})
        # Scoring is exclusively controller-side, after no more model calls can occur.
        scores=[]
        for row in frozen:
            score=experiment.score([row])[0]; score['role']=row['role']; scores.append(score)
            shutil.copy2(row['run']/'grading/evaluation.json',output/row['role']/f"checkpoint_{row['checkpoint']}"/'evaluation.json')
            save(output/'scores.json',scores)
            print(f"Graded {row['role']} checkpoint {row['checkpoint']}: {score['passed']}/{score['total']}",flush=True)
        if failure:
            raise failure


if __name__ == '__main__':
    main()
