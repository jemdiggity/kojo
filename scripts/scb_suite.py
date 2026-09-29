#!/usr/bin/env python3
"""Launch selected SCBench problems; default is a no-inference preview."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from kojo.batch import identifier, load_plan
from kojo.known_skill_sets import KNOWN, resolve

MODELS = {
    'sonnet55': 'claude-sonnet-5-5',
    'opus55': 'claude-opus-5-5',
    'sol6': 'gpt-6-sol',
    'astra6': 'gpt-6-astra',
    'opus5': 'claude-opus-5',
    'sol56': 'gpt-5.6-sol',
    'fable51': 'claude-fable-5-1',
}
DEFAULT_MODELS = tuple(MODELS)[:-1]
PROBLEMS = {'code_search': 5, 'circuit_eval': 8, 'database_migration': 5,
            'dynamic_config_service_api': 4}


def plans(prefix, models, problems, skill_sets=None, parallel=None):
    identifier(prefix)
    if not models or len(set(models)) != len(models):
        raise ValueError('Select each model only once; at least one is required')
    if not problems or len(set(problems)) != len(problems):
        raise ValueError('Select each problem only once; at least one is required')
    if any(problem not in PROBLEMS for problem in problems):
        raise ValueError('Unsupported problem')
    if parallel not in (None, 'models', 'models-skills', 'all'):
        raise ValueError('Unsupported parallel mode')
    # Each directory is a separate experimental condition, not merged with others.
    conditions = skill_sets or [{'name': 'baseline', 'path': None}]
    batches = []
    for problem in problems:
        for condition in conditions:
            runs = []
            for tag in models:
                model = MODELS[tag]
                effort = '--claude-effort' if model.startswith('claude-') else '--codex-effort'
                suffix = '-' + condition['name'] if skill_sets else ''
                flags = ['--problem', problem, '--build-model', model,
                         effort, 'medium', '--seconds-per-session', '1800',
                         '--no-review', '--monitor-only']
                if condition['path']:
                    flags += ['--skill-set', str(condition['path']),
                              '--skill-set-sha256', condition['sha256']]
                runs.append({'run_id': f'{prefix}-{problem.replace("_", "-")}-{tag}{suffix}',
                             'factory_args': flags})
            batches.append({'batch_id': f'{prefix}-{problem.replace("_", "-")}' +
                            ('-' + condition['name'] if skill_sets else ''),
                            'max_parallel': len(models) if parallel else 1, 'runs': runs})
    if parallel == 'models-skills':
        batches = [{'batch_id': f'{prefix}-{problem.replace("_", "-")}',
                    'runs': [run for b in batches for run in b['runs']
                             if run['factory_args'][1] == problem],
                    'max_parallel': len(models) * len(conditions)} for problem in problems]
    elif parallel == 'all':
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        argv = ['-h']
    parser = argparse.ArgumentParser(
        usage='%(prog)s [-h]\n'
              '  --id ID\n'
              '  --models MODEL [MODEL ...]\n'
              '  --problems PROBLEM [PROBLEM ...]\n'
              '  [--skill-sets SKILL_SET [SKILL_SET ...]]\n'
              '  [--parallel {models,models-skills,all}]\n'
              '  [--audit | --run]\n'
              '  [--tmux-session NAME]',
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Supported model aliases (exact provider IDs):\n' +
               '\n'.join(f'  {alias:10} {model}' for alias, model in MODELS.items()) +
               '\n\nSelect models and problems explicitly with --models and --problems.')
    parser.add_argument('--id', required=True, help='Fresh experiment prefix, e.g. repro-01')
    parser.add_argument('--models', nargs='+', choices=MODELS, required=True, metavar='MODEL',
                        help='Space-separated model aliases (%s)' % ', '.join(MODELS))
    parser.add_argument('--problems', nargs='+', choices=PROBLEMS, required=True, metavar='PROBLEM',
                        help='Space-separated problems in scheduling order (%s)' % ', '.join(PROBLEMS))
    parser.add_argument('--skill-sets', nargs='+', metavar='SKILL_SET',
                        help='Separate skill conditions: a well-known name (%s) or a directory; '
                             'omitted means no skills' % ', '.join(sorted(KNOWN)))
    parser.add_argument('--parallel', choices=['models', 'models-skills', 'all'],
                        help='Parallel dimensions; omitted means every run is sequential')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--audit', action='store_true', help='Native CLI checks without inference')
    action.add_argument('--run', action='store_true', help='Execute models; consumes provider allowance')
    parser.add_argument('--tmux-session', help='Optional tmux log-viewer session; launcher stays foreground')
    args = parser.parse_args(argv)
    cli_bin = ROOT / 'intermediate/provider-cli/node_modules/.bin'
    if cli_bin.is_dir():
        os.environ['PATH'] = str(cli_bin) + os.pathsep + os.environ.get('PATH', '')
    try:
        from kojo.skill_sets import describe_sets, freeze_sets
        cache = ROOT / 'intermediate/vendor/skill-sets'
        skill_sets = describe_sets([resolve(s, cache) for s in args.skill_sets or []])
        configs = plans(args.id, args.models, args.problems, skill_sets, args.parallel)
        if args.tmux_session:
            identifier(args.tmux_session)
        if not (args.run or args.audit):
            print(json.dumps(configs, indent=2))
            print('Preview only; no plans written or model calls made'
                  + ('; named skill sets are cached under intermediate/vendor/skill-sets.' if any(n in KNOWN for n in args.skill_sets or []) else '.'))
            return 0
        if skill_sets:
            skill_sets = freeze_sets(ROOT / 'intermediate/plans' / args.id / 'skill-sets', skill_sets)
            configs = plans(args.id, args.models, args.problems, skill_sets, args.parallel)
        paths = save_plans(ROOT / 'intermediate/plans' / args.id, configs)
        for path in paths:
            load_plan(path)
    except (ValueError, KeyError) as error:
        parser.error(str(error))
    if args.audit:
        for path in paths:
            code = subprocess.call([sys.executable, str(ROOT / 'scripts/scb_batch.py'),
                                    str(path), '--audit', '--jobs', str(configs[paths.index(path)]['max_parallel'])], cwd=ROOT)
            if code:
                return code
        return 0
    print(f'Launching {len(args.models) * max(1, len(skill_sets)) * sum(PROBLEMS[p] for p in args.problems)} sessions: medium effort, 30 minutes each, '
          'no review, default output limits. Usage is monitored, not capped.', flush=True)
    cmd = [sys.executable, str(ROOT / 'scripts/scb_dex_sonnet_series.py'),
           '--run', '--series-id', args.id, '--tmux-session', args.tmux_session or '']
    for path in paths:
        cmd += ['--plan', str(path)]
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == '__main__':
    raise SystemExit(main())
