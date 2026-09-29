"""Read-only web dashboard for run progress and results; stdlib only, no inference."""
import argparse
import hashlib
import json
import re
import statistics
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from kojo.catalog import BASE

STATIC = Path(__file__).parent / 'dashboard_static'
ID = re.compile(r'[a-z0-9-]+')
ROLES = ('build', 'review', 'fix')
LOG_TAIL_BYTES = 64_000


def load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def summarize_evaluation(evaluation, number):
    """Split test outcomes into the current checkpoint and earlier regressions."""
    cur = {'passed': 0, 'total': 0}
    prior = {'passed': 0, 'total': 0}
    failed = []
    for group, outcomes in (evaluation.get('tests') or {}).items():
        cp = group.split('-')[0]
        bucket = cur if cp == f'checkpoint_{number}' else prior
        for state, names in outcomes.items():
            bucket['total'] += len(names)
            if state == 'passed':
                bucket['passed'] += len(names)
            else:
                failed += [{'group': group, 'name': n, 'state': state} for n in names]
    strict = bool(cur['total'] + prior['total']) and not failed
    total = cur['total'] + prior['total']
    # Iso: every non-regression test of this checkpoint passes. Core: every Core-category test passes.
    core = [n for g, o in (evaluation.get('tests') or {}).items() if g.endswith('-Core')
            for st, n in o.items() if st != 'passed' and n]
    return {'current': cur, 'prior': prior, 'failed': failed, 'strict': strict,
            'iso': cur['total'] > 0 and cur['passed'] == cur['total'],
            'core': not core and any(g.endswith('-Core') for g in (evaluation.get('tests') or {})),
            'partial': (cur['passed'] + prior['passed']) / total if total else None,
            'grading_seconds': evaluation.get('duration'),
            'infrastructure_failure': bool(evaluation.get('infrastructure_failure'))}


def checkpoint_rows(base, run_id):
    """One row per role/checkpoint found under results/runs/<id> (or in-flight data)."""
    rows = []
    root = base / 'results/runs' / run_id
    for role in ROLES:
        for directory in sorted((root / role).glob('checkpoint_*'),
                                key=lambda p: int(p.name.split('_')[1])):
            number = int(directory.name.split('_')[1])
            run = load(directory / 'run.json') or {}
            row = {'role': role, 'checkpoint': number, 'status': run.get('status'),
                   'model': run.get('model'), 'effort': run.get('reasoning'),
                   'elapsed_seconds': run.get('elapsed_seconds'),
                   'cost_usd': run.get('api_price_equivalent_usd'), 'usage': run.get('usage')}
            evaluation = load(directory / 'evaluation.json') or load(directory / 'grading/evaluation.json')
            if evaluation:
                row.update(summarize_evaluation(evaluation, number))
            rows.append(row)
    return rows


METRICS = ('strict', 'iso', 'core', 'partial')
SETTINGS = ('model', 'skill', 'factory', 'effort', 'problem')
VARYING = tuple(d for d in SETTINGS if d != 'problem')  # results on different problems aren't comparable
GROUPS = ('model', 'skill', 'factory', 'effort', 'problem', 'batch', 'run')


def run_meta(base, run_id):
    manifest = load(base / 'results/runs' / run_id / 'manifest.json') or {}
    skills = manifest.get('skills') or {}
    loops = manifest.get('review_loops')
    return {'problem': manifest.get('problem') or 'unknown',
            'skill': re.sub(r'(-[0-9a-f]{10})+$', '', skills.get('name') or 'none'),
            'factory': 'build only' if not loops else f'build + review x{loops}'}


def final_checkpoints(rows):
    """One entry per checkpoint: the last code-producing graded role, cost/time over all roles."""
    by_number = {}
    for r in rows:
        by_number.setdefault(r['checkpoint'], []).append(r)
    out = []
    for number, group in sorted(by_number.items()):
        graded = [r for r in group if 'strict' in r]
        pick = next((r for role in ('fix', 'build') for r in graded if r['role'] == role), None)
        if pick:
            out.append({**pick, 'cost_usd': sum(r['cost_usd'] or 0 for r in group),
                        'elapsed_seconds': sum(r['elapsed_seconds'] or 0 for r in group)})
    return out


def mean_sd(values):
    values = [v for v in values if v is not None]
    if not values:
        return None, None
    m = sum(values) / len(values)
    return m, (statistics.stdev(values) if len(values) > 1 else 0.0)


def experiments(runs):
    """Sets of batches whose parameters are identical except for exactly one setting.

    A batch's parameters are the values it uses per setting (e.g. skills {none, a, b}),
    so batches that each sweep the same skills but use different models combine into
    one experiment. Problem never varies, and a run outside any batch counts as its own.
    """
    batches = {}
    for meta, _ in runs:
        batch = batches.setdefault(meta['batch'] if meta['batch'] != 'none' else meta['run'],
                                   {'runs': [], **{d: set() for d in SETTINGS}})
        batch['runs'].append(meta['run'])
        for d in SETTINGS:
            batch[d].add(meta[d])
    found = {}
    for vary in VARYING:
        fixed_dims = [d for d in SETTINGS if d != vary]
        groups = {}
        for name, batch in batches.items():
            groups.setdefault(tuple(tuple(sorted(batch[d])) for d in fixed_dims), []).append(name)
        for key, names in groups.items():
            values = sorted(set().union(*(batches[n][vary] for n in names)))
            if len({tuple(sorted(batches[n][vary])) for n in names}) < 2:
                continue
            fixed = {d: list(v) for d, v in zip(fixed_dims, key)}
            ident = hashlib.sha1(json.dumps([vary, fixed], sort_keys=True).encode()).hexdigest()[:10]
            found[ident] = {'id': ident, 'vary': vary, 'values': values, 'fixed': fixed,
                            'batches': sorted(names),
                            'runs': sorted(r for n in names for r in batches[n]['runs'])}
    return sorted(found.values(), key=lambda e: (-len(e['runs']), e['vary'], e['id']))


def leaderboard(base, by, filters=None, then=None, experiment=None):
    """Paper-style table: percent of checkpoints passing each metric, per group.

    Runs are pooled across batches; `filters` maps a dimension to allowed values,
    and `pooled` reports every setting present among the included runs so the
    caller can see which dimensions were mixed.
    """
    if by not in GROUPS or (then is not None and (then not in GROUPS or then == by)):
        return None
    filters = {k: set(v) for k, v in (filters or {}).items() if k in GROUPS and v}
    runs = []
    for rid in run_ids(base):
        rows = final_checkpoints(checkpoint_rows(base, rid))
        if rows:
            batch = (load(base / 'results/runs' / rid / 'run-config.json') or {}).get('batch_id')
            runs.append(({**run_meta(base, rid), 'run': rid, 'batch': batch or 'none',
                          'model': rows[0]['model'] or 'unknown', 'effort': rows[0]['effort'] or 'unknown'}, rows))
    facets = {dim: {} for dim in GROUPS if dim != 'run'}
    for meta, _ in runs:
        for dim, counts in facets.items():
            counts[meta[dim]] = counts.get(meta[dim], 0) + 1
    catalog = experiments(runs)
    allowed = None
    if experiment:
        chosen = next((e for e in catalog if e['id'] == experiment), None)
        allowed = set(chosen['runs']) if chosen else set()
    included = [(m, r) for m, r in runs if (allowed is None or m['run'] in allowed)
                and all(m[d] in v for d, v in filters.items())]
    pooled = {dim: sorted({m[dim] for m, _ in included}) for dim in facets}
    groups = {}
    for meta, rows in included:
        entry = groups.setdefault((meta[by], meta[then] if then else None), {'runs': set(), 'rows': []})
        entry['runs'].add(meta['run'])
        entry['rows'] += rows
    table = []
    for (key, sub), entry in groups.items():
        rows = entry['rows']
        row = {'key': key, 'sub': sub, 'runs': len(entry['runs']), 'run_ids': sorted(entry['runs']),
               'checkpoints': len(rows)}
        for metric in METRICS:
            values = [r[metric] for r in rows if r.get(metric) is not None]
            row[metric] = 100 * sum(values) / len(values) if values else None
        row['cost_mean'], row['cost_sd'] = mean_sd([r['cost_usd'] for r in rows])
        row['cost_total'] = sum(r['cost_usd'] or 0 for r in rows)
        minutes = [r['elapsed_seconds'] / 60 for r in rows if r['elapsed_seconds'] is not None]
        row['minutes_mean'], row['minutes_sd'] = mean_sd(minutes)
        table.append(row)
    return {'by': by, 'then': then, 'rows': sorted(table, key=lambda r: (-(r['strict'] or 0), r['key'], r['sub'] or '')),
            'facets': {d: sorted(c.items()) for d, c in facets.items()}, 'pooled': pooled,
            'runs': len(included), 'experiments': catalog}


def batch_states(base):
    """Map run id -> (batch id, state) from every batch status.json."""
    states = {}
    for status in sorted((base / 'intermediate/batches').glob('*/status.json')):
        data = load(status) or {}
        for rid, state in (data.get('runs') or {}).items():
            states[rid] = (status.parent.name, state.get('status'), state.get('exit_code', state.get('exit')))
    return states


def run_ids(base):
    ids = set()
    for parent in ('results/runs', 'intermediate/runs'):
        ids |= {p.name for p in (base / parent).glob('*') if p.is_dir() and ID.fullmatch(p.name)}
    return sorted(ids)


def run_summary(base, run_id, states=None):
    states = batch_states(base) if states is None else states
    batch, status, code = states.get(run_id, (None, None, None))
    config = load(base / 'intermediate/runs' / run_id / 'run-config.json') or {}
    rows = checkpoint_rows(base, run_id)
    graded = [r for r in rows if 'strict' in r]
    if status is None:
        exit_info = load(base / 'intermediate/runs' / run_id / 'launcher-exit.json')
        status = 'finished' if exit_info else ('complete' if (base/'results/runs'/run_id/'results.json').exists() else 'unknown')
    partial = [r['current']['passed'] / r['current']['total'] for r in graded if r['current']['total']]
    return {
        'id': run_id, 'batch': batch, 'status': status, 'exit_code': code,
        'problem': config.get('problem'), 'checkpoints_done': len(rows),
        'checkpoints_graded': len(graded),
        'strict_passed': sum(r['strict'] for r in graded),
        'partial_pass': sum(partial) / len(partial) if partial else None,
        'cost_usd': sum(r['cost_usd'] or 0 for r in rows),
        'elapsed_seconds': sum(r['elapsed_seconds'] or 0 for r in rows),
        'models': sorted({r['model'] for r in rows if r['model']}),
    }


def overview(base):
    states = batch_states(base)
    batches = []
    for plan in sorted((base / 'intermediate/batches').glob('*/plan.json')):
        status = load(plan.parent / 'status.json') or {}
        counts = {}
        for state in (status.get('runs') or {}).values():
            counts[state.get('status')] = counts.get(state.get('status'), 0) + 1
        batches.append({'id': plan.parent.name, 'cancelled': status.get('cancelled'),
                        'action': status.get('action'), 'counts': counts})
    comparisons = sorted(p.parent.name for p in (base / 'results/comparisons').glob('*/suite_analysis.json'))
    return {'batches': batches, 'runs': [run_summary(base, r, states) for r in run_ids(base)],
            'comparisons': comparisons}


def run_detail(base, run_id):
    if not ID.fullmatch(run_id) or run_id not in run_ids(base):
        return None
    return {**run_summary(base, run_id), 'checkpoints': checkpoint_rows(base, run_id)}


def run_log(base, run_id):
    if not ID.fullmatch(run_id):
        return None
    path = base / 'intermediate/runs' / run_id / 'controller.log'
    if not path.is_file():
        return ''
    with path.open('rb') as f:
        size = path.stat().st_size
        f.seek(max(0, size - LOG_TAIL_BYTES))
        return f.read().decode('utf-8', 'replace')


def comparison(base, name):
    """Per-model totals from a published suite analysis, without per-test outcomes."""
    if not ID.fullmatch(name):
        return None
    data = load(base / 'results/comparisons' / name / 'suite_analysis.json')
    if data is None:
        return None
    models = []
    for m in data['models']:
        cps = m['checkpoints']
        models.append({
            'model': m['model'], 'strict': m['strict'], 'checkpoints': len(cps),
            'accepted_checkpoints': m.get('accepted_checkpoints'),
            'partial_pass': (sum(c['passed'] / (c['passed'] + c['failed'] + c['skipped'])
                                 for c in cps if c['passed'] + c['failed'] + c['skipped']) / len(cps)) if cps else None,
            'cost_usd': m.get('cost'), 'minutes': m.get('minutes'), 'unmetered': m.get('unmetered'),
            'grid': [{'problem': c['problem'], 'checkpoint': c['checkpoint'], 'strict': c['strict'],
                      'passed': c['passed'], 'failed': c['failed'], 'skipped': c['skipped']} for c in cps]})
    charts = sorted(p.name for p in (base / 'results/comparisons' / name / 'charts').glob('figure-*.png'))
    return {'name': name, 'models': models, 'charts': charts}


def make_handler(base):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body, kind='application/json', code=200):
            if not isinstance(body, bytes):
                body = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def missing(self):
            self.send({'error': 'not found'}, code=404)

        def do_GET(self):
            parts = [p for p in urlparse(self.path).path.split('/') if p]
            if not parts:
                return self.send((STATIC / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            if parts[0] != 'api':
                return self.missing()
            route = parts[1:]
            if route == ['overview']:
                return self.send(overview(base))
            if route == ['leaderboard']:
                query = parse_qs(urlparse(self.path).query)
                data = leaderboard(base, query.get('by', ['model'])[0],
                                   {d: query.get(d, []) for d in GROUPS if d != 'run'},
                                   query.get('then', [None])[0] or None,
                                   query.get('experiment', [None])[0] or None)
                return self.send(data) if data else self.missing()
            if len(route) == 2 and route[0] == 'runs':
                detail = run_detail(base, route[1])
                return self.send(detail) if detail else self.missing()
            if len(route) == 3 and route[0] == 'runs' and route[2] == 'log':
                text = run_log(base, route[1])
                return self.send(text, 'text/plain; charset=utf-8') if text is not None else self.missing()
            if len(route) == 2 and route[0] == 'comparisons':
                data = comparison(base, route[1])
                return self.send(data) if data else self.missing()
            if len(route) == 4 and route[0] == 'comparisons' and route[2] == 'charts':
                image = base / 'results/comparisons' / route[1] / 'charts' / route[3]
                if ID.fullmatch(route[1]) and re.fullmatch(r'figure-[a-z0-9-]+\.png', route[3]) and image.is_file():
                    return self.send(image.read_bytes(), 'image/png')
            return self.missing()

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--base', type=Path, default=BASE, help='checkout holding results/ and intermediate/')
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.base.resolve()))
    print(f'Kojo dashboard: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
