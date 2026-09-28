"""One sequential Luna build chain, one fresh review, one fresh follow-up."""
import argparse
import fcntl
import shutil
import time

from kojo.catalog import BASE, protocol_digest
from kojo.execution import audit, run_session, save, session_paths
from kojo.gauntlet import Experiment, copy_code, hashes, preflight, read
from kojo.run_chain import ChainBackend, compose_prompt


def instructions(backend, role):
    common = (
        f'Work only in your current src directory. Use Python 3.12 via {backend.python}; '
        'the executable entry file is code_search. Available libraries: Python standard library, '
        'PyYAML, lxml, cssselect, tomli-w. All public specifications are in the user prompt. '
        'Do not access parent directories, other runs, home directories, benchmark tests or external solutions. '
        'No network or package installation. Put self-tests and temporary files inside src. '
        'No skills or cheat sheet are supplied. Your execution budget is 300 seconds. '
    )
    return common + {
        'build': 'Implement the requested checkpoint, preserving earlier requirements. Use shell tools to verify your work and summarize your checks.',
        'review': 'Review the supplied code against the specifications and give actionable feedback. You may run checks in this disposable copy. Do not implement fixes. Your final response is the review that will be passed to a fresh developer. Identify concrete issues, locations and evidence; distinguish verified defects from suspicions.',
        'fix': 'Follow up on the supplied code review. Inspect the code and specifications, assess the feedback, implement justified fixes, and verify the result. This is the only follow-up; summarize changes and checks.',
    }[role]


def stage_prompt(experiment, role, checkpoint=5, feedback=None):
    specs = compose_prompt(experiment, checkpoint)
    if role == 'build':
        return specs
    specs = specs.replace('Implement the current checkpoint.', 'Review the completed program.' if role == 'review' else 'Improve the completed program using the review.')
    if role == 'fix':
        if not feedback or not feedback.strip():
            raise ValueError('A completed review is required before follow-up')
        specs += '\n\n# Feedback from the independent Luna reviewer\n' + feedback
    return specs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['audit', 'run'])
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args(argv)
    if not args.run_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.run_id):
        parser.error('Use lowercase letters, digits and hyphens')
    cfg, manifest = preflight()
    root = BASE / 'intermediate/runs' / args.run_id
    data = root / 'gauntlet'
    output = BASE / 'results/runs' / args.run_id
    backend = ChainBackend(cfg, manifest, data, output)
    experiment = Experiment(backend)
    if args.action == 'audit':
        for role in ('build', 'review', 'fix'):
            probe = root / 'offline-audit' / role
            audit(probe, instructions(backend, role), backend.runtime, None, True,
                  stage_prompt(experiment, role, 1 if role == 'build' else 5, 'Offline review placeholder.'), persist=True)
        print('All three role requests and native isolation verified without inference.', flush=True)
        return
    data.mkdir(parents=True, exist_ok=True)
    with (data / 'execution.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if output.exists() or (data / 'ledger.json').exists():
            raise RuntimeError('Run ID already used; no implicit resume or retry')
        output.mkdir(parents=True)
        save(output / 'manifest.json', {
            'run_id':args.run_id, 'problem':'code_search', 'condition':'single-review-factory',
            'pins':cfg, 'protocol_sha256':backend.protocol, 'quota':read(BASE / 'configs/quota.json'),
            'max_sessions':7, 'seconds_per_session':300, 'review_loops':1, 'skills':None,
            'sequence':'five incremental build checkpoints, one review of final code, one follow-up',
            'grading':'All calls finish or stop before grading; reviewer and fixer never receive official results.',
            'scope':'Exploratory same-task workflow test, not held-out learning or a compute-matched comparison.',
        })
        ledger=[]; frozen=[]; previous=None; failure=None

        def session(role, n, source, feedback=None):
            if protocol_digest() != backend.protocol:
                raise RuntimeError('Protocol changed during run')
            run = data / f'training-{role}/code_search/checkpoint_{n}'
            dest = output / role / f'checkpoint_{n}'
            copy_code(source, run / 'src')
            dest.mkdir(parents=True)
            save(dest / 'initial-src.json', hashes(run / 'src'))
            prompt = stage_prompt(experiment, role, n, feedback)
            (dest / 'prompt.md').write_text(prompt)
            (dest / 'instructions.md').write_text(instructions(backend, role))
            ledger.append({'role':role, 'checkpoint':n, 'reserved_at':time.time()})
            save(data / 'ledger.json', ledger)
            prior=[sample for p in session_paths(data) if (p.parent/'quota.json').exists() for sample in read(p.parent/'quota.json')]
            print(f'Starting {role} checkpoint {n}', flush=True)
            run_session(run, instructions(backend, role), prompt, 300, backend.runtime,
                        None, prior, isolated_src=True)
            for filename in ['run.json','quota.json','verification.json','transcript-verification.json','answer.txt']:
                shutil.copy2(run/filename, dest/filename)
            if role != 'review':
                copy_code(run/'src',run/'submission')
                shutil.copytree(run/'submission',dest/'submission')
                save(dest/'snapshot.json',hashes(run/'submission'))
                frozen.append({'name':'code_search','checkpoint':n,'run':run,'role':role})
            else:
                save(dest/'source-changes.json',{'before':hashes(source),'after':hashes(run/'src'),
                                               'carry_forward':'Only answer.txt; no reviewer workspace changes.'})
            print(f'Finished {role} checkpoint {n}', flush=True)
            return run

        try:
            for n in range(1,6):
                previous=session('build',n,previous)/'submission'
            review=session('review',5,previous)
            if read(review/'run.json')['status'] != 'complete':
                raise RuntimeError('Reviewer did not complete; refusing partial review follow-up')
            session('fix',5,previous,(review/'answer.txt').read_text())
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
