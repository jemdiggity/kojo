"""One authorized, fresh baseline chain; no skill learning or other problems."""

import fcntl
import shutil
import time

from kojo.catalog import BASE, protocol_digest
from kojo.execution import save, session_paths
from kojo.gauntlet import Backend, Experiment, preflight, read

DATA = BASE / 'intermediate/runs/20260927-code-search-baseline-01/gauntlet'
OUTPUT = BASE / 'results/runs/20260927-code-search-baseline-01'


class SingleBackend(Backend):
    def authorize(self):
        if protocol_digest() != self.protocol or self.cfg['max_sessions'] != 5:
            raise RuntimeError('Single-run protocol changed')

    def session(self, run, instructions, prompt, role, skill=None):
        parts = run.relative_to(self.data).parts
        if (len(parts) != 3 or parts[:2] != ('training-single', 'code_search')
                or parts[2] not in [f'checkpoint_{n}' for n in range(1, 6)]
                or role != 'solver' or skill != ''):
            raise RuntimeError('Outside the authorized five-checkpoint baseline')
        return super().session(run, instructions, prompt, role, skill)


def main():
    cfg, manifest = preflight()
    cfg = {**cfg, 'max_sessions': 5}
    backend = SingleBackend(cfg, manifest, DATA, OUTPUT)
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / 'execution.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        save(OUTPUT / 'protocol.json', {
            'sha256': backend.protocol, 'model': cfg['model'],
            'reasoning': cfg['reasoning'], 'max_sessions': 5,
            'solver_seconds': cfg['solver_seconds'], 'skill': None,
            'authorization': 'User requested one full code_search run',
            'dataset': manifest['problems']['code_search'],
            'quota': read(BASE / 'configs/quota.json'),
        })
        experiment = Experiment(backend)
        try:
            rows = experiment.solve_chain('training-single', 'code_search', '')
            scores = []
            for row in rows:
                score = experiment.score([row])[0]
                scores.append(score)
                dest = OUTPUT / 'checkpoints' / f"checkpoint_{row['checkpoint']}"
                dest.mkdir(parents=True, exist_ok=True)
                if not (dest / 'submission').exists():
                    shutil.copytree(row['run'] / 'submission', dest / 'submission')
                for file in ['run.json', 'quota.json', 'snapshot.json']:
                    shutil.copy2(row['run'] / file, dest / file)
                shutil.copy2(row['run'] / 'grading/evaluation.json', dest / 'evaluation.json')
                save(OUTPUT / 'scores.json', scores)
                print(f"Graded checkpoint {row['checkpoint']}: {score['passed']}/{score['total']}", flush=True)
        except BaseException as error:
            save(OUTPUT / 'STOPPED.json', {'reason': str(error), 'time': time.time()})
            raise
        finally:
            sessions = [read(p) for p in session_paths(DATA)]
            save(OUTPUT / 'accounting.json', {
                'sessions': sessions,
                'elapsed_seconds': sum(r.get('elapsed_seconds', 0) for r in sessions),
                'known_api_equivalent_usd': sum(r.get('api_price_equivalent_usd') or 0 for r in sessions),
                'unmetered_sessions': sum(r.get('usage') is None for r in sessions),
                'actual_subscription_cash_cost_usd': None,
            })


if __name__ == '__main__':
    main()
