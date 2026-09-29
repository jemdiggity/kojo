"""Launch the three-problem SCBench comparison; default is a no-inference preview."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from kojo.batch import identifier, load_plan

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
PROBLEMS = ('circuit_eval', 'database_migration', 'dynamic_config_service_api')


def plans(prefix, models):
    identifier(prefix)
    if len(set(models)) != len(models):
        raise ValueError('Select each model only once')
    result = []
    for problem in PROBLEMS:
        runs = []
        for tag in models:
            model = MODELS[tag]
            effort = '--claude-effort' if model.startswith('claude-') else '--codex-effort'
            runs.append({'run_id': f'{prefix}-{problem.replace("_", "-")}-{tag}',
                         'factory_args': ['--problem', problem, '--build-model', model,
                                          effort, 'medium', '--seconds-per-session', '1800',
                                          '--no-review', '--monitor-only']})
        result.append({'batch_id': f'{prefix}-{problem.replace("_", "-")}',
                       'max_parallel': len(models), 'runs': runs})
    return result


def save_plans(directory, configs):
    # Refuse different settings before writing anything; audit then run may reuse plans.
    paths = [directory / f'{p}.json' for p in PROBLEMS]
    for path, config in zip(paths, configs):
        if path.exists() and json.loads(path.read_text()) != config:
            raise ValueError(f'Plan differs: {path}. Choose a new --id.')
    directory.mkdir(parents=True, exist_ok=True)
    for path, config in zip(paths, configs):
        if not path.exists():
            with path.open('x') as f:
                f.write(json.dumps(config, indent=2) + '\n')
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Supported model aliases (exact provider IDs):\n' +
               '\n'.join(f'  {alias:10} {model}' for alias, model in MODELS.items()) +
               '\n\nSelect models explicitly with --models.')
    parser.add_argument('--id', required=True, help='Fresh experiment prefix, e.g. repro-01')
    parser.add_argument('--models', nargs='+', choices=MODELS, required=True,
                        help='Space-separated list of model aliases')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--audit', action='store_true', help='Native CLI checks without inference')
    action.add_argument('--run', action='store_true', help='Execute models; consumes provider allowance')
    parser.add_argument('--tmux-session', help='Optional tmux log-viewer session; launcher stays foreground')
    args = parser.parse_args(argv)
    cli_bin = ROOT / 'intermediate/provider-cli/node_modules/.bin'
    if cli_bin.is_dir():
        os.environ['PATH'] = str(cli_bin) + os.pathsep + os.environ.get('PATH', '')
    try:
        configs = plans(args.id, args.models)
        if args.tmux_session:
            identifier(args.tmux_session)
        if not (args.run or args.audit):
            print(json.dumps(configs, indent=2))
            print('Preview only; no files written or model calls made.')
            return 0
        paths = save_plans(ROOT / 'intermediate/plans' / args.id, configs)
        for path in paths:
            load_plan(path)
    except (ValueError, KeyError) as error:
        parser.error(str(error))
    if args.audit:
        for path in paths:
            code = subprocess.call([sys.executable, str(ROOT / 'scripts/scb_batch.py'),
                                    str(path), '--audit'], cwd=ROOT)
            if code:
                return code
        return 0
    print(f'Launching {len(args.models) * 17} sessions: medium effort, 30 minutes each, '
          'no review, default output limits. Usage is monitored, not capped.', flush=True)
    cmd = [sys.executable, str(ROOT / 'scripts/scb_dex_sonnet_series.py'),
           '--run', '--series-id', args.id, '--tmux-session', args.tmux_session or '']
    for path in paths:
        cmd += ['--plan', str(path)]
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == '__main__':
    raise SystemExit(main())
