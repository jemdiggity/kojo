"""Named, src-isolated five-checkpoint code_search runs; explicit run action spends quota."""
import argparse
import fcntl
import hashlib
import json
import shutil
import time
from pathlib import Path

from kojo.catalog import BASE, digest, protocol_digest
from kojo.execution import audit, run_session, save, session_paths
from kojo.gauntlet import Backend, Experiment, copy_code, hashes, preflight, read


def compose_prompt(experiment, checkpoint):
    parts = ['Implement the current checkpoint. Earlier specifications remain requirements unless superseded. All task information is supplied here; do not seek files outside src.']
    for n in range(1, checkpoint + 1):
        parts += [f'\n# {"CURRENT" if n == checkpoint else "PRIOR"} CHECKPOINT {n}\n', experiment.spec('code_search', n)]
    return '\n'.join(parts)


class ChainBackend(Backend):
    def session(self, run, instructions, prompt, role, skill=None):
        raise RuntimeError('Use the bounded chain controller')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['audit', 'run'])
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--guidance', default='configs/prompts/verified-implementation-v1.md')
    args = parser.parse_args(argv)
    if not args.run_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.run_id):
        parser.error('Use a lowercase run ID with digits and hyphens')
    cfg, manifest = preflight()
    data = BASE / 'intermediate/runs' / args.run_id / 'gauntlet'
    output = BASE / 'results/runs' / args.run_id
    guide_path = (BASE / args.guidance).resolve()
    guidance = guide_path.read_text()
    backend = ChainBackend(cfg, manifest, data, output)
    experiment = Experiment(backend)
    instructions = (
        'Build the requested command-line program in your current src directory. '
        f'Use Python 3.12, entry file code_search, and {backend.python} for execution. '
        'Available libraries: Python standard library, PyYAML, lxml, cssselect, tomli-w. '
        'The complete current and prior public specifications are in the user prompt. '
        'Only src contains task files you may access. Do not inspect parent directories, other runs, '
        'home directories, benchmark tests, or external solutions. No network or package installation. '
        'Put all implementation, self-tests and temporary files inside src. '
        'Checkpoint 1 starts empty; later checkpoints contain only your previous checkpoint code. '
        'Use shell tools to implement and verify the specification, preserve earlier requirements, '
        'and summarize your own checks. Your execution budget is 300 seconds. '
        'The following guidance is supplied explicitly; no other skills are enabled.'
    )
    if args.action == 'audit':
        probe = BASE / 'intermediate/runs' / args.run_id / 'offline-audit'
        audit(probe, instructions, backend.runtime, guidance, True, compose_prompt(experiment, 1))
        if list((probe / 'src').iterdir()):
            raise RuntimeError('Audit polluted initial src')
        print('Exact request and strict src isolation passed; no model calls')
        return
    data.mkdir(parents=True, exist_ok=True)
    with (data / 'execution.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (data / 'ledger.json').exists() or output.exists():
            raise RuntimeError('Run ID already used; refusing implicit resume or retry')
        output.mkdir(parents=True)
        (output / 'guidance.md').write_text(guidance)
        (output / 'instructions.md').write_text(instructions)
        identity = {
            'run_id': args.run_id, 'problem': 'code_search', 'condition': 'stronger-model-assisted-guidance',
            'model': cfg['model'], 'reasoning': cfg['reasoning'], 'max_sessions': 5,
            'seconds_per_session': 300, 'protocol_sha256': backend.protocol,
            'guidance_sha256': digest(output / 'guidance.md'), 'pins': cfg,
            'quota': read(BASE / 'configs/quota.json'),
            'comparison': 'Exploratory same-task rerun after analyzing baseline failures; not held-out learning evidence. Prompt delivery and read isolation also changed.',
            'guidance_author': 'Stronger supervising assistant; no writer inference session. Authoring cost separately unmetered.',
        }
        save(output / 'manifest.json', identity)
        rows = []; previous = None; ledger = []
        try:
            for n in range(1, 6):
                if protocol_digest() != backend.protocol or guide_path.read_text() != guidance:
                    raise RuntimeError('Protocol or guidance changed during run')
                run = data / 'training-single/code_search' / f'checkpoint_{n}'
                copy_code(previous, run / 'src')
                initial = hashes(run / 'src')
                if n == 1 and initial:
                    raise RuntimeError('Checkpoint 1 must start empty')
                prompt = compose_prompt(experiment, n)
                dest = output / f'checkpoints/checkpoint_{n}'
                dest.mkdir(parents=True)
                (dest / 'prompt.md').write_text(prompt)
                (dest / 'SPEC.md').write_text(experiment.spec('code_search', n))
                save(dest / 'initial-src.json', initial)
                ledger.append({'checkpoint': n, 'reserved_at': time.time()})
                save(data / 'ledger.json', ledger)
                prior = [sample for p in session_paths(data) if (p.parent/'quota.json').exists() for sample in read(p.parent/'quota.json')]
                run_session(run, instructions, prompt, 300, backend.runtime, guidance, prior, isolated_src=True)
                copy_code(run / 'src', run / 'submission')
                save(run / 'snapshot.json', {'skill_sha256': hashlib.sha256(guidance.encode()).hexdigest(), 'files': hashes(run / 'submission')})
                shutil.copytree(run / 'submission', dest / 'submission')
                for filename in ['run.json', 'quota.json', 'snapshot.json', 'verification.json']:
                    shutil.copy2(run / filename, dest / filename)
                rows.append({'name':'code_search', 'checkpoint':n, 'run':run})
                previous = run / 'submission'
                print(f'Checkpoint {n} frozen', flush=True)
            scores=[]
            # All model calls finish before any official grading is exposed.
            for row in rows:
                score=experiment.score([row])[0]; scores.append(score)
                dest=output / f"checkpoints/checkpoint_{row['checkpoint']}"
                shutil.copy2(row['run'] / 'grading/evaluation.json', dest / 'evaluation.json')
                save(output / 'scores.json', scores)
                print(f"Graded checkpoint {row['checkpoint']}: {score['passed']}/{score['total']}",flush=True)
        except BaseException as error:
            save(output / 'STOPPED.json', {'reason':str(error),'time':time.time()})
            raise
        finally:
            sessions=[read(p) for p in session_paths(data)]
            save(output / 'accounting.json', {
                'sessions':sessions, 'sessions_reserved':len(ledger),
                'elapsed_seconds':sum(r.get('elapsed_seconds',0) for r in sessions),
                'known_api_equivalent_usd':sum(r.get('api_price_equivalent_usd') or 0 for r in sessions),
                'unmetered_sessions':sum(r.get('usage') is None for r in sessions),
                'actual_subscription_cash_cost_usd':None,
            })


if __name__ == '__main__':
    main()
