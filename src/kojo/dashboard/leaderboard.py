"""Aggregate runs into a paper-style table, and find comparable experiments.

Pure functions over `store.Run` objects; no file access.
"""
import hashlib
import json
import statistics

METRICS = ('strict', 'iso', 'core', 'partial')
SETTINGS = ('model', 'skill', 'factory', 'effort', 'problem')
# Results on different problems aren't comparable, so an experiment never varies the problem.
VARYING = tuple(s for s in SETTINGS if s != 'problem')
FILTERABLE = SETTINGS + ('batch',)
GROUPABLE = FILTERABLE + ('run',)


def dimension(run, name):
    """A run's value for a setting, or for 'batch' / 'run'."""
    return {'batch': run.batch, 'run': run.id}.get(name) or run.settings[name]


def mean_sd(values):
    values = [v for v in values if v is not None]
    if not values:
        return None, None
    return sum(values) / len(values), (statistics.stdev(values) if len(values) > 1 else 0.0)


def experiments(runs):
    """Sets of batches whose parameters are identical except for exactly one setting.

    A batch's parameters are the sets of values it uses per setting (so ordering and
    repeats don't matter). Batches that each sweep the same skills but use different
    models therefore combine into one experiment.
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
            distinct = {tuple(sorted(batches[n][vary])) for n in names}
            if len(distinct) < 2:
                continue
            fixed = {setting: list(values) for setting, values in zip(held, signature)}
            ident = hashlib.sha1(json.dumps([vary, fixed], sort_keys=True).encode()).hexdigest()[:10]
            found[ident] = {'id': ident, 'vary': vary, 'fixed': fixed, 'batches': sorted(names),
                            'values': sorted(set().union(*(batches[n][vary] for n in names))),
                            'runs': sorted(r for n in names for r in batches[n]['runs'])}
    return sorted(found.values(), key=lambda e: (-len(e['runs']), e['vary'], e['id']))


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
    return row


def leaderboard(runs, by, then=None, filters=None, experiment=None):
    """Percent of checkpoints passing each metric, per `by` (and optionally `then`) group.

    `filters` maps a dimension to its allowed values; `experiment` restricts to one
    catalogued experiment. `pooled` lists the values present among the included runs so
    callers can show which settings were combined.
    """
    if by not in GROUPABLE or (then and (then not in GROUPABLE or then == by)):
        raise ValueError('unknown grouping')
    filters = {name: set(values) for name, values in (filters or {}).items() if name in FILTERABLE and values}
    catalog = experiments(runs)
    allowed = None
    if experiment:
        chosen = next((e for e in catalog if e['id'] == experiment), None)
        allowed = set(chosen['runs']) if chosen else set()
    included = [r for r in runs if (allowed is None or r.id in allowed)
                and all(dimension(r, name) in values for name, values in filters.items())]

    groups = {}
    for run in included:
        groups.setdefault((dimension(run, by), dimension(run, then) if then else None), []).append(run)
    rows = sorted((_row(key, sub, members) for (key, sub), members in groups.items()),
                  key=lambda r: (-(r['strict'] or 0), r['key'], r['sub'] or ''))
    return {'by': by, 'then': then or None, 'rows': rows, 'runs': len(included),
            'facets': _facets(runs), 'experiments': catalog,
            'pooled': {name: sorted({dimension(r, name) for r in included}) for name in FILTERABLE}}
