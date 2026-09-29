"""Read run artifacts from a checkout's results/ and intermediate/ directories.

Everything here is read-only and tolerant of runs that are still in flight:
missing or half-written files simply yield less data.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from kojo.dashboard.evaluation import summarize

ID = re.compile(r'[a-z0-9-]+')
ROLES = ('build', 'review', 'fix')
GRADED_ROLES = ('fix', 'build')  # roles that produce graded code; the earlier one loses to `fix`
LOG_TAIL_BYTES = 64_000
UNKNOWN = 'unknown'
QUALITY_VARIANT = 'entrypoint-normalized'  # the analysis variant that covers extensionless entrypoints


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


@dataclass(frozen=True)
class Run:
    """A run reduced to what comparisons need: its settings and final graded checkpoints."""
    id: str
    batch: str
    settings: dict  # model, skill, factory, effort, problem
    checkpoints: list = field(default_factory=list)


def _skill_name(manifest):
    name = (manifest.get('skills') or {}).get('name') or 'none'
    return re.sub(r'(-[0-9a-f]{10})+$', '', name)  # drop the content-hash suffixes


def _factory_name(manifest):
    loops = manifest.get('review_loops')
    return f'build + review x{loops}' if loops else 'build only'


def quality_metrics(row):
    """{'erosion', 'verbosity'} for the normalized variant from one quality.json row, or None.

    Suite files nest variants inside a row; per-run files have one row per variant.
    """
    if 'variants' in row:
        metrics = (row['variants'].get(QUALITY_VARIANT) or {}).get('metrics') or {}
    elif row.get('variant', QUALITY_VARIANT) == QUALITY_VARIANT:
        metrics = row.get('metrics') or {}
    else:
        return None
    if metrics.get('erosion') is None or metrics.get('verbosity') is None:
        return None
    return {'erosion': metrics['erosion'], 'verbosity': metrics['verbosity']}


def final_checkpoints(rows):
    """One row per graded checkpoint: the fixer's output if any, else the builder's.

    Cost and time cover every role that ran for that checkpoint.
    """
    by_number = {}
    for row in rows:
        by_number.setdefault(row['checkpoint'], []).append(row)
    final = []
    for number, group in sorted(by_number.items()):
        graded = [r for r in group if 'strict' in r]
        chosen = next((r for role in GRADED_ROLES for r in graded if r['role'] == role), None)
        if chosen:
            final.append({**chosen, 'cost_usd': sum(r['cost_usd'] or 0 for r in group),
                          'elapsed_seconds': sum(r['elapsed_seconds'] or 0 for r in group)})
    return final


class Store:
    def __init__(self, base):
        self.base = Path(base)
        self.results = self.base / 'results'
        self.intermediate = self.base / 'intermediate'

    # -- runs -------------------------------------------------------------

    def run_ids(self):
        found = set()
        for parent in (self.results / 'runs', self.intermediate / 'runs'):
            found |= {p.name for p in parent.glob('*') if p.is_dir() and ID.fullmatch(p.name)}
        return sorted(found)

    def checkpoint_rows(self, run_id):
        """One row per role and checkpoint, with grading metrics once graded."""
        rows = []
        root = self.results / 'runs' / run_id
        for role in ROLES:
            directories = sorted((root / role).glob('checkpoint_*'), key=lambda p: int(p.name.split('_')[1]))
            for directory in directories:
                number = int(directory.name.split('_')[1])
                run = load_json(directory / 'run.json') or {}
                row = {'role': role, 'checkpoint': number, 'status': run.get('status'),
                       'model': run.get('model'), 'effort': run.get('reasoning'),
                       'elapsed_seconds': run.get('elapsed_seconds'),
                       'cost_usd': run.get('api_price_equivalent_usd')}
                evaluation = load_json(directory / 'evaluation.json')
                if evaluation:
                    row.update(summarize(evaluation, number))
                rows.append(row)
        return rows

    def quality_by_checkpoint(self):
        """(run id, checkpoint) -> erosion/verbosity, from every published quality.json.

        These come from the offline scb-check analysis (scripts/scb_quality*.py); runs that
        haven't been analyzed simply have no entry.
        """
        paths = sorted(self.results.glob('comparisons/*/quality.json')) + sorted(self.results.glob('comparisons/*/*/quality.json'))
        found = {}
        for path in paths:
            for row in (load_json(path) or {}).get('rows', []):
                metrics = quality_metrics(row)
                if metrics:
                    found[(row['run_id'], row['checkpoint'])] = metrics
        return found

    def graded_runs(self):
        """Every run with at least one graded checkpoint, ready for comparison."""
        runs = []
        quality = self.quality_by_checkpoint()
        for run_id in self.run_ids():
            rows = final_checkpoints(self.checkpoint_rows(run_id))
            if not rows:
                continue
            rows = [{**row, **quality.get((run_id, row['checkpoint']), {'erosion': None, 'verbosity': None})} for row in rows]
            manifest = load_json(self.results / 'runs' / run_id / 'manifest.json') or {}
            config = load_json(self.results / 'runs' / run_id / 'run-config.json') or {}
            settings = {'model': rows[0]['model'] or UNKNOWN, 'effort': rows[0]['effort'] or UNKNOWN,
                        'skill': _skill_name(manifest), 'factory': _factory_name(manifest),
                        'problem': manifest.get('problem') or UNKNOWN}
            runs.append(Run(run_id, config.get('batch_id') or run_id, settings, rows))
        return runs

    def _batch_states(self):
        """Run id -> (batch id, status, exit code) from every batch's status.json."""
        states = {}
        for path in sorted((self.intermediate / 'batches').glob('*/status.json')):
            for run_id, state in ((load_json(path) or {}).get('runs') or {}).items():
                states[run_id] = (path.parent.name, state.get('status'), state.get('exit_code'))
        return states

    def _run_status(self, run_id, launcher_status):
        if launcher_status:
            return launcher_status
        if load_json(self.intermediate / 'runs' / run_id / 'launcher-exit.json'):
            return 'finished'
        return 'complete' if (self.results / 'runs' / run_id / 'results.json').exists() else UNKNOWN

    def _run_summary(self, run_id, states, rows):
        batch, status, exit_code = states.get(run_id, (None, None, None))
        graded = final_checkpoints(rows)  # one per checkpoint, not one per role that ran
        partial = [r['partial'] for r in graded if r['partial'] is not None]
        return {'id': run_id, 'batch': batch, 'status': self._run_status(run_id, status),
                'exit_code': exit_code, 'checkpoints_graded': len(graded),
                'strict_passed': sum(r['strict'] for r in graded),
                'partial_pass': sum(partial) / len(partial) if partial else None,
                'cost_usd': sum(r['cost_usd'] or 0 for r in rows),
                'elapsed_seconds': sum(r['elapsed_seconds'] or 0 for r in rows),
                'models': sorted({r['model'] for r in rows if r['model']})}

    def overview(self):
        """Batches with per-status counts, and a summary of every run."""
        states = self._batch_states()
        batches = []
        for plan in sorted((self.intermediate / 'batches').glob('*/plan.json')):
            status = load_json(plan.parent / 'status.json') or {}
            counts = {}
            for state in (status.get('runs') or {}).values():
                counts[state.get('status')] = counts.get(state.get('status'), 0) + 1
            batches.append({'id': plan.parent.name, 'action': status.get('action'),
                            'cancelled': status.get('cancelled'), 'counts': counts})
        runs = [self._run_summary(rid, states, self.checkpoint_rows(rid)) for rid in self.run_ids()]
        return {'batches': batches, 'runs': runs, 'comparisons': self.comparison_names()}

    def run_detail(self, run_id):
        """Summary plus every checkpoint row, or None for an unknown run."""
        if run_id not in self.run_ids():
            return None
        rows = self.checkpoint_rows(run_id)
        return {**self._run_summary(run_id, self._batch_states(), rows), 'checkpoints': rows}

    def log_tail(self, run_id):
        path = self.intermediate / 'runs' / run_id / 'controller.log'
        if not path.is_file():
            return ''
        with path.open('rb') as f:
            f.seek(max(0, path.stat().st_size - LOG_TAIL_BYTES))
            return f.read().decode('utf-8', 'replace')

    # -- published comparisons -------------------------------------------

    def comparison_names(self):
        return sorted(p.parent.name for p in (self.results / 'comparisons').glob('*/suite_analysis.json'))

    def comparison(self, name):
        """Per-model totals and a checkpoint grid from a published suite analysis."""
        data = load_json(self.results / 'comparisons' / name / 'suite_analysis.json')
        if data is None:
            return None
        models = []
        for model in data['models']:
            fractions = [c['passed'] / n for c in model['checkpoints']
                         if (n := c['passed'] + c['failed'] + c['skipped'])]
            models.append({
                'model': model['model'], 'strict': model['strict'],
                'checkpoints': len(model['checkpoints']),
                'partial_pass': sum(fractions) / len(model['checkpoints']) if model['checkpoints'] else None,
                'cost_usd': model.get('cost'), 'minutes': model.get('minutes'),
                'grid': [{key: c[key] for key in ('problem', 'checkpoint', 'strict', 'passed', 'failed', 'skipped')}
                         for c in model['checkpoints']]})
        charts = sorted(p.name for p in (self.results / 'comparisons' / name / 'charts').glob('figure-*.png'))
        return {'name': name, 'models': models, 'charts': charts, 'quality': self._quality_progress(name)}

    def _quality_progress(self, name):
        """Erosion/verbosity per model across normalized progress, if the suite was analyzed."""
        data = load_json(self.results / 'comparisons' / name / 'quality-suite' / 'chart_aggregates.json')
        if not data:
            return None
        progress = {}
        for entry in data['normalized_progress']:
            progress.setdefault(entry['metric'], {})[entry['model']] = entry['values']
        return {'models': data['model_order'], 'progress': progress}

    def chart_path(self, name, filename):
        path = self.results / 'comparisons' / name / 'charts' / filename
        return path if path.is_file() else None
