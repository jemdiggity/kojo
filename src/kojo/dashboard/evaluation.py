"""Turn one checkpoint's grading report into pass/fail metrics."""

Tally = dict  # {'passed': int, 'total': int}


def _split_group(group):
    """Report groups are named '<checkpoint>-<category>', e.g. 'checkpoint_2-Core'."""
    checkpoint, _, category = group.partition('-')
    return checkpoint, category


def summarize(evaluation, number):
    """Metrics for checkpoint `number` from its evaluation report.

    current/prior count tests introduced by this checkpoint versus earlier ones
    (regressions). strict: every test passes. iso: every current test passes.
    core: every Core-category test passes. partial: passed / collected.
    """
    current = {'passed': 0, 'total': 0}
    prior = {'passed': 0, 'total': 0}
    failed = []
    core_groups = core_failures = 0
    for group, outcomes in (evaluation.get('tests') or {}).items():
        checkpoint, category = _split_group(group)
        tally = current if checkpoint == f'checkpoint_{number}' else prior
        core_groups += category == 'Core'
        for state, names in outcomes.items():
            tally['total'] += len(names)
            if state == 'passed':
                tally['passed'] += len(names)
                continue
            core_failures += len(names) if category == 'Core' else 0
            failed += [{'group': group, 'name': name, 'state': state} for name in names]
    total = current['total'] + prior['total']
    return {
        'current': current, 'prior': prior, 'failed': failed,
        'strict': total > 0 and not failed,
        'iso': current['total'] > 0 and current['passed'] == current['total'],
        'core': core_groups > 0 and core_failures == 0,
        'partial': (current['passed'] + prior['passed']) / total if total else None,
    }
