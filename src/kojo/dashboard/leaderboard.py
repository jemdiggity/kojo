"""Aggregate runs into a paper-style table, and suggest comparisons worth making.

Pure functions over `store.Run` objects; no file access.
"""
import statistics

METRICS = ('strict', 'iso', 'core', 'partial')  # percent of checkpoints passing
QUALITY = ('erosion', 'verbosity')  # static-analysis scores in [0, 1]; lower is better
PROGRESS = (0, 0.25, 0.5, 0.75, 1)  # normalized positions along a run at which trajectories are sampled
SETTINGS = ('model', 'skill', 'factory', 'effort', 'problem')
# Results on different problems aren't comparable, so an experiment never varies the problem.
VARYING = tuple(s for s in SETTINGS if s != 'problem')
FILTERABLE = SETTINGS + ('batch', 'run')  # anything a run can be selected or grouped by
GROUPABLE = FILTERABLE


def dimension(run, name):
    """A run's value for a setting, or for 'batch' / 'run'."""
    if name == 'batch':
        return run.batch
    if name == 'run':
        return run.id
    return run.settings[name]


def mean_sd(values):
    values = [v for v in values if v is not None]
    if not values:
        return None, None
    return sum(values) / len(values), (statistics.stdev(values) if len(values) > 1 else 0.0)


def experiments(runs):
    """Suggested comparisons: sets of runs that differ in exactly one setting, matched through batches.

    These are only presets for the filters (each is selected by its `batches`); the filters stay
    the single way runs are chosen.

    A batch's parameters are the sets of values it uses per setting (so ordering and
    repeats don't matter). Batches with identical parameters for every setting but one
    are pooled, and that one setting must take at least two values across them. So
    batches that each sweep the same skills with different models combine, and a single
    batch that sweeps one setting is an experiment on its own.
    """
    batches = {}
    for run in runs:
        batch = batches.setdefault(run.batch, {'runs': [], **{s: set() for s in SETTINGS}})
        batch['runs'].append(run.id)
        for setting in SETTINGS:
            batch[setting].add(run.settings[setting])

    found = {}
    for vary in VARYING:
        held = [s for s in SETTINGS if s != vary]
        groups = {}
        for name, batch in batches.items():
            groups.setdefault(tuple(tuple(sorted(batch[s])) for s in held), []).append(name)
        for signature, names in groups.items():
            values = sorted(set().union(*(batches[n][vary] for n in names)))
            if len(values) < 2:
                continue
            fixed = {setting: list(vals) for setting, vals in zip(held, signature)}
            found[(vary, tuple(sorted(names)))] = {
                'vary': vary, 'fixed': fixed, 'batches': sorted(names), 'values': values,
                'runs': sorted(r for n in names for r in batches[n]['runs'])}
    return sorted(found.values(), key=lambda e: (-len(e['runs']), e['vary'], e['batches']))


def _facets(runs):
    """For each filterable dimension: [(value, run count)], over all runs."""
    counts = {name: {} for name in FILTERABLE}
    for run in runs:
        for name, seen in counts.items():
            value = dimension(run, name)
            seen[value] = seen.get(value, 0) + 1
    return {name: sorted(seen.items()) for name, seen in counts.items()}


def _row(key, sub, runs):
    checkpoints = [c for run in runs for c in run.checkpoints]
    row = {'key': key, 'sub': sub, 'runs': len(runs), 'run_ids': sorted(r.id for r in runs),
           'checkpoints': len(checkpoints)}
    for metric in METRICS:
        values = [c[metric] for c in checkpoints if c.get(metric) is not None]
        row[metric] = 100 * sum(values) / len(values) if values else None
    row['cost_mean'], row['cost_sd'] = mean_sd([c['cost_usd'] for c in checkpoints])
    row['cost_total'] = sum(c['cost_usd'] or 0 for c in checkpoints)
    row['minutes_mean'], row['minutes_sd'] = mean_sd(
        [c['elapsed_seconds'] / 60 for c in checkpoints if c['elapsed_seconds'] is not None])
    for metric in QUALITY:
        row[metric], row[f'{metric}_sd'] = mean_sd([c.get(metric) for c in checkpoints])
    return row


def _interpolate(points, x):
    """Linear interpolation of sorted (position, value) points at x."""
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


def trajectory(runs, metric, intermediate=False):
    """Mean `metric` at each PROGRESS position across runs, or None if no run has enough data.

    Each run is placed on 0..1 by checkpoint order so runs with different checkpoint counts align.
    `intermediate` follows the earlier stages a later stage replaced (e.g. build before fix).
    """
    per_run = []
    for run in runs:
        count = len(run.checkpoints)
        place = {c.get('checkpoint', i): i for i, c in enumerate(run.checkpoints)}
        rows = run.intermediate if intermediate else run.checkpoints
        points = sorted((place[c.get('checkpoint', i)] / (count - 1), c[metric])
                        for i, c in enumerate(rows) if count > 1 and c.get('checkpoint', i) in place and c.get(metric) is not None)
        if len(points) >= 2:
            per_run.append([_interpolate(points, x) for x in PROGRESS])
    if not per_run:
        return None
    columns = [[v for v in column if v is not None] for column in zip(*per_run)]
    return [sum(c) / len(c) if c else None for c in columns]


def leaderboard(runs, by, then=None, filters=None):
    """Percent of checkpoints passing each metric, per `by` (and optionally `then`) group.

    `filters` maps a dimension to its allowed values (a run is included if it matches every
    filtered dimension). `pooled` lists the values present among the included runs so callers can
    show which settings were combined; `experiments` are suggested comparisons over all runs.
    """
    if by not in GROUPABLE or (then and (then not in GROUPABLE or then == by)):
        raise ValueError('unknown grouping')
    filters = {name: set(values) for name, values in (filters or {}).items() if name in FILTERABLE and values}
    included = [r for r in runs if all(dimension(r, name) in values for name, values in filters.items())]

    groups = {}
    for run in included:
        groups.setdefault((dimension(run, by), dimension(run, then) if then else None), []).append(run)
    rows = sorted((_row(key, sub, members) for (key, sub), members in groups.items()),
                  key=lambda r: (-(r['strict'] or 0), r['key'], r['sub'] or ''))
    trajectories = [{'key': key, 'sub': sub, **{m: trajectory(members, m) for m in QUALITY},
                     'intermediate': {m: trajectory(members, m, intermediate=True) for m in QUALITY}}
                    for (key, sub), members in sorted(groups.items(), key=lambda g: (g[0][0], g[0][1] or ''))]
    return {'by': by, 'then': then or None, 'rows': rows, 'runs': len(included),
            'trajectories': [t for t in trajectories if any(t[m] or t['intermediate'][m] for m in QUALITY)],
            'facets': _facets(runs), 'experiments': experiments(runs),
            'pooled': {name: sorted({dimension(r, name) for r in included}) for name in FILTERABLE}}
