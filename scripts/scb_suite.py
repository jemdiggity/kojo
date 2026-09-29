"""Launch selected SCBench problems; default is a no-inference preview."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from kojo.batch import identifier, load_plan
from kojo import factory_spec
from kojo.catalog import DATA_ROOT
from kojo.factory_spec import EFFORTS, MODELS
from kojo.known_skill_sets import KNOWN, resolve

NONE = 'none'
PROBLEMS = {'code_search': 5, 'circuit_eval': 8, 'database_migration': 5,
            'dynamic_config_service_api': 4}

PARALLEL = ('models', 'models-skills', 'models-skills-efforts', 'all')


def plans(prefix, models, problems, skill_sets=None, parallel=None, efforts=None, factories=None):
    """Batches for models (one build-only run each) or, with factories, one run per factory."""
    identifier(prefix)
    if factories and (models or efforts):
        raise ValueError('A factory sets its own models and efforts; use --factory without --models or --efforts')
    if factories:
        for name in factories:
            factory_spec.load(name)
    tags = factories or models
    if not tags or len(set(tags)) != len(tags):
        raise ValueError('Select each model or factory only once; at least one is required')
    if not problems or len(set(problems)) != len(problems):
        raise ValueError('Select each problem only once; at least one is required')
    if any(problem not in PROBLEMS for problem in problems):
        raise ValueError('Unsupported problem')
    if efforts is not None and (not efforts or len(set(efforts)) != len(efforts)):
        raise ValueError('Select each effort only once')
    if parallel not in (None, *PARALLEL):
        raise ValueError('Unsupported parallel mode')
    # Each directory is a separate experimental condition, not merged with others.
    conditions = skill_sets or [{'name': 'baseline', 'path': None}]
    levels = efforts or ['medium']
    for tag in ([] if factories else models):
        vendor = 'claude' if MODELS[tag].startswith('claude-') else 'codex'
        for effort in levels:
            if effort not in EFFORTS[vendor]:
                raise ValueError(f'{tag} supports efforts: {", ".join(EFFORTS[vendor])}')
    # Each entry is (problem, effort, batch) so modes can regroup along any dimension.
    entries = []
    for problem in problems:
        for effort in levels:
            for condition in conditions:
                runs = []
                for tag in tags:
                    suffix = ('-' + effort if efforts else '') + ('-' + condition['name'] if skill_sets else '')
                    if factories:
                        flags = ['--problem', problem, '--factory', tag, '--seconds-per-session', '1800', '--monitor-only']
                    else:
                        model = MODELS[tag]
                        flag = '--claude-effort' if model.startswith('claude-') else '--codex-effort'
                        flags = ['--problem', problem, '--build-model', model,
                                 flag, effort, '--seconds-per-session', '1800',
                                 '--no-review', '--monitor-only']
                    if condition['path']:
                        flags += ['--skill-set', str(condition['path']),
                                  '--skill-set-sha256', condition['sha256']]
                    runs.append({'run_id': f'{prefix}-{problem.replace("_", "-")}-{tag}{suffix}',
                                 'factory_args': flags})
                batch = f'{prefix}-{problem.replace("_", "-")}' + ('-' + effort if efforts else '') + \
                    ('-' + condition['name'] if skill_sets else '')
                entries.append((problem, effort, {'batch_id': batch,
                                                  'max_parallel': len(tags) if parallel else 1, 'runs': runs}))
    if parallel in ('models-skills', 'models-skills-efforts'):
        by_effort = parallel == 'models-skills'
        groups = [(p, e) for p in problems for e in (levels if by_effort else [None])]
        batches = []
        for problem, effort in groups:
            runs = [r for p, e, b in entries if p == problem and effort in (None, e) for r in b['runs']]
            batch_id = f'{prefix}-{problem.replace("_", "-")}' + ('-' + effort if efforts and effort else '')
            batches.append({'batch_id': batch_id, 'runs': runs, 'max_parallel': len(runs)})
        return batches
    batches = [b for _, _, b in entries]
    if parallel == 'all':
        runs = [run for batch in batches for run in batch['runs']]
        batches = [{'batch_id': prefix + '-all', 'runs': runs, 'max_parallel': len(runs)}]
    return batches


def save_plans(directory, configs):
    paths = [directory / (config['batch_id'] + '.json') for config in configs]
    # Freeze the entire ordered schedule, so changed selections or concurrency
    # cannot silently reuse an audited experiment ID.
    schedule = directory / 'schedule.json'
    if schedule.exists() and json.loads(schedule.read_text()) != configs:
        raise ValueError(f'Plan differs: {schedule}. Choose a new --id.')
    for path, config in zip(paths, configs):
        if path.exists() and json.loads(path.read_text()) != config:
            raise ValueError(f'Plan differs: {path}. Choose a new --id.')
    directory.mkdir(parents=True, exist_ok=True)
    for path, config in [(schedule, configs), *zip(paths, configs)]:
        if not path.exists():
            with path.open('x') as f:
                f.write(json.dumps(config, indent=2) + '\n')
    return paths


def reset_audit(experiment, configs):
    """An audit may replace its own earlier artifacts, but never state from a started real run."""
    plans_dir = ROOT / 'intermediate/plans' / experiment
    saved = plans_dir / 'schedule.json'
    previous = json.loads(saved.read_text()) if saved.exists() else []
    ids = {run['run_id'] for config in configs + previous for run in config['runs']}
    started = [rid for rid in sorted(ids) if (DATA_ROOT / 'intermediate/runs' / rid).exists()
               or (DATA_ROOT / 'results/runs' / rid).exists()]
    shape = lambda cs: [(c['batch_id'], c['max_parallel'], [r['run_id'] for r in c['runs']]) for c in cs]
    if started and previous and shape(previous) != shape(configs):
        raise ValueError(f'Run {started[0]} has started under this --id; choose a new --id to change the plan.')
    for config in configs:
        shutil.rmtree(ROOT / 'intermediate/batches' / (config['batch_id'] + '-audit'), ignore_errors=True)
        for run in config['runs']:
            shutil.rmtree(DATA_ROOT / 'intermediate/runs' / f"{config['batch_id']}-{run['run_id']}-audit", ignore_errors=True)
    if not started:
        shutil.rmtree(plans_dir, ignore_errors=True)  # Nothing has run, so the plan is still editable.


def mark(ok):
    """Green check or red x; colour only on a terminal."""
    symbol = '\u2713' if ok else '\u2717'
    if not sys.stdout.isatty() or os.environ.get('NO_COLOR'):
        return symbol
    return f"\033[{'32' if ok else '31'}m{symbol}\033[0m"


def label(flags):
    """Short human name for one run: CLI, problem, model, effort, skill set."""
    value = lambda name: flags[flags.index(name) + 1]
    if '--factory' in flags:
        skills = Path(value('--skill-set')).name if '--skill-set' in flags else 'none'
        return f"factory {value('--problem')} / {value('--factory')} / {skills}"
    effort = value('--claude-effort') if '--claude-effort' in flags else value('--codex-effort')
    skills = Path(value('--skill-set')).name if '--skill-set' in flags else 'none'
    cli = 'claude' if '--claude-effort' in flags else 'codex'
    return f"{cli:6} {value('--problem')} / {value('--build-model')} / {effort} / {skills}"


def audit(paths, configs, verbose):
    """Run the no-inference audit; print one PASS/FAIL line per run and a summary."""
    total = passed = 0
    for path, config in zip(paths, configs):
        command = [sys.executable, str(ROOT / 'scripts/scb_batch.py'), str(path), '--audit',
                   '--jobs', str(config['max_parallel'])]
        with tempfile.TemporaryFile('w+') as captured:
            out = None if verbose else captured
            code = subprocess.call(command, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT if out else None)
            captured.seek(0)
            output = captured.read()
        batch_passed = 0
        status_path = ROOT / 'intermediate/batches' / (config['batch_id'] + '-audit') / 'status.json'
        if not status_path.exists():
            # The launcher failed before starting any run; its own message is the diagnosis.
            print(f"FAIL {config['batch_id']}: launcher error (exit {code})\n{output.strip()[-1500:]}")
            total += len(config['runs'])
            return finish(passed, total, code or 1)
        runs = json.loads(status_path.read_text())['runs']
        for run in config['runs']:
            rid = f"{config['batch_id']}-{run['run_id']}-audit"
            ok = runs.get(rid, {}).get('status') == 'complete'
            total += 1
            passed += ok
            batch_passed += ok
            print(f"{mark(ok)} {label(run['factory_args'])}")
            if not ok:
                log = DATA_ROOT / 'intermediate/runs' / rid / 'controller.log'
                tail = log.read_text().strip().splitlines()[-5:] if log.exists() else ['(no controller log)']
                print('     ' + '\n     '.join(tail) + f'\n     log: {log}')
        if code:
            # Every run may have passed while the launcher itself still failed; say why.
            detail = [l for l in output.splitlines() if l.strip() and not l.startswith('[')]
            print(f"FAIL {config['batch_id']}: launcher exited {code} after its runs finished"
                  + (':\n     ' + '\n     '.join(detail[-12:]) if detail else
                     ' with no output; rerun with --verbose'))
        if batch_passed < len(config['runs']) or code:
            return finish(passed, total, code or 1)  # Stop before the next batch, as a failed audit should.
    return finish(passed, total, 0)


def finish(passed, total, code):
    print(f'Audit: {passed}/{total} passed; no inference was run.' + ('' if code == 0 else ' FAILED.'))
    return code


def launch_summary(args, skill_sets, configs):
    """Runs are the unit of parallelism; each run works through its checkpoints in order."""
    runs = sum(len(c['runs']) for c in configs)
    parallel = max(c['max_parallel'] for c in configs)
    checkpoints = sum(PROBLEMS[p] for p in args.problems)
    noun = lambda n, word: f'{n} {word}' + ('' if n == 1 else 's')
    skills = noun(max(1, len(skill_sets)), 'skill set')
    if args.factory:
        sessions = sum(factory_spec.load(name).max_sessions() for name in args.factory) * max(1, len(skill_sets)) * checkpoints
        return (f'Launching {noun(runs, "run")} ({noun(len(args.factory), "factory")} x {skills} x '
                f'{noun(len(args.problems), "problem")}), {parallel} at a time; each run does its checkpoints '
                f'one after another (up to {sessions} sessions in total). Each factory sets its own models '
                'and efforts; 30 minutes per session, default output limits. Usage is monitored, not capped.')
    sessions = len(args.models) * max(1, len(skill_sets)) * len(args.efforts or [0]) * checkpoints
    return (f'Launching {noun(runs, "run")} ({noun(len(args.models), "model")} x '
            f'{skills} x {noun(len(args.efforts or [0]), "effort")} x '
            f'{noun(len(args.problems), "problem")}), {parallel} at a time; each run does its checkpoints '
            f'one after another ({sessions} checkpoint sessions in total). '
            f'{", ".join(args.efforts or ["medium"])} effort, 30 minutes per session, no review, '
            'default output limits. Usage is monitored, not capped.')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        argv = ['-h']
    parser = argparse.ArgumentParser(
        usage='%(prog)s [-h]\n'
              '  --id ID\n'
              '  (--models MODEL [MODEL ...] | --factory FACTORY [FACTORY ...])\n'
              '  --problems PROBLEM [PROBLEM ...]\n'
              '  [--skill-sets SKILL_SET [SKILL_SET ...]]\n'
              '  [--efforts EFFORT [EFFORT ...]]\n'
              '  [--parallel {' + ','.join(PARALLEL) + '}]\n'
              '  [--audit | --run]\n'
              '  [--verbose]\n'
              '  [--tmux-session NAME]',
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Supported model aliases (exact provider IDs):\n' +
               '\n'.join(f'  {alias:10} {model}' for alias, model in MODELS.items()) +
               '\n\nSelect models (or factories) and problems explicitly with --models (or --factory) and --problems.')
    parser.add_argument('--id', required=True, help='Fresh experiment prefix, e.g. repro-01')
    parser.add_argument('--models', nargs='+', choices=MODELS, metavar='MODEL',
                        help='Space-separated model aliases (%s)' % ', '.join(MODELS))
    parser.add_argument('--factory', nargs='+', metavar='FACTORY',
                        help='Factory descriptions to run instead of --models: names from configs/factories/ '
                             '(see docs/factory-language.md); each defines its own models, efforts and review flow')
    parser.add_argument('--problems', nargs='+', choices=PROBLEMS, required=True, metavar='PROBLEM',
                        help='Space-separated problems in scheduling order (%s)' % ', '.join(PROBLEMS))
    parser.add_argument('--skill-sets', nargs='+', metavar='SKILL_SET',
                        help='Separate skill conditions: %s (no skills, the baseline), a well-known '
                             'name (%s), or a directory; omitted means a single no-skills run'
                             % (NONE, ', '.join(sorted(KNOWN))))
    parser.add_argument('--efforts', nargs='+', metavar='EFFORT',
                        help='Reasoning-effort conditions (Claude: %s; Codex: %s); omitted means medium'
                             % (', '.join(EFFORTS['claude']), ', '.join(EFFORTS['codex'])))
    parser.add_argument('--parallel', choices=PARALLEL,
                        help='Parallel dimensions; omitted means every run is sequential')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--audit', action='store_true', help='Native CLI checks without inference')
    parser.add_argument('--verbose', action='store_true', help='Show full launcher output for --audit')
    action.add_argument('--run', action='store_true', help='Execute models; consumes provider allowance')
    parser.add_argument('--tmux-session', help='Optional tmux log-viewer session; launcher stays foreground')
    args = parser.parse_args(argv)
    if bool(args.models) == bool(args.factory):
        parser.error('Choose exactly one of --models or --factory')
    if args.factory and args.efforts:
        parser.error('A factory sets its own efforts; remove --efforts')
    cli_bin = ROOT / 'intermediate/provider-cli/node_modules/.bin'
    if cli_bin.is_dir():
        os.environ['PATH'] = str(cli_bin) + os.pathsep + os.environ.get('PATH', '')
    try:
        from kojo.skill_sets import describe_sets, freeze_sets
        cache = ROOT / 'intermediate/vendor/skill-sets'
        specs = args.skill_sets or []
        if len(set(specs)) != len(specs):
            raise ValueError('Select each skill set only once')
        # 'none' is the explicit no-skills baseline condition; it has no directory to freeze.
        described = iter(describe_sets([resolve(s, cache) for s in specs if s != NONE]))
        skill_sets = [{'name': NONE, 'path': None, 'sha256': None} if s == NONE else next(described)
                      for s in specs]
        configs = plans(args.id, args.models, args.problems, skill_sets, args.parallel, args.efforts, args.factory)
        if args.tmux_session:
            identifier(args.tmux_session)
        if not (args.run or args.audit):
            print(json.dumps(configs, indent=2))
            print('Preview only; no plans written or model calls made'
                  + ('; named skill sets are cached under intermediate/vendor/skill-sets.' if any(n in KNOWN for n in args.skill_sets or []) else '.'))
            return 0
        if args.audit:
            reset_audit(args.id, configs)
        if skill_sets:
            frozen = iter(freeze_sets(ROOT / 'intermediate/plans' / args.id / 'skill-sets',
                                      [c for c in skill_sets if c['path']]))
            skill_sets = [next(frozen) if c['path'] else c for c in skill_sets]
            configs = plans(args.id, args.models, args.problems, skill_sets, args.parallel, args.efforts, args.factory)
        paths = save_plans(ROOT / 'intermediate/plans' / args.id, configs)
        for path in paths:
            load_plan(path)
    except (ValueError, KeyError) as error:
        parser.error(str(error))
    if args.audit:
        return audit(paths, configs, args.verbose)
    print(launch_summary(args, skill_sets, configs), flush=True)
    cmd = [sys.executable, str(ROOT / 'scripts/scb_dex_sonnet_series.py'),
           '--run', '--series-id', args.id, '--tmux-session', args.tmux_session or '']
    for path in paths:
        cmd += ['--plan', str(path)]
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == '__main__':
    raise SystemExit(main())
