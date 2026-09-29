import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('scb_suite', Path(__file__).resolve().parents[1] / 'scripts/scb_suite.py')
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


class SuiteLauncherTests(unittest.TestCase):
    def test_preview_never_writes_or_launches(self):
        with patch.object(suite, 'save_plans') as save, patch.object(suite.subprocess, 'call') as call, patch('builtins.print'):
            self.assertEqual(suite.main(['--problems', 'circuit_eval', 'database_migration', '--id', 'preview', '--models', 'sonnet55']), 0)
            save.assert_not_called()
            call.assert_not_called()

    def test_published_experiment(self):
        # The README's reproduction command: these exact models and problems.
        models = ['sonnet55', 'opus55', 'sol6', 'astra6', 'fable51', 'opus5', 'sol56']
        problems = ['circuit_eval', 'database_migration', 'dynamic_config_service_api']
        plans = suite.plans('repro-01', models, problems)
        self.assertEqual(len(plans), 3)
        for problem, plan in zip(problems, plans):
            self.assertEqual(plan['max_parallel'], 1)
            self.assertEqual([r['factory_args'][r['factory_args'].index('--build-model') + 1] for r in plan['runs']],
                             [suite.MODELS[m] for m in models])
            for run in plan['runs']:
                flags = run['factory_args']
                self.assertEqual(flags[flags.index('--problem') + 1], problem)
                self.assertIn('medium', flags)
                self.assertIn('1800', flags)
                self.assertIn('--no-review', flags)
                self.assertNotIn('--claude-max-output-tokens', flags)

    def test_none_is_a_no_skills_baseline_condition(self):
        skills = [{'name': 'none', 'path': None, 'sha256': None},
                  {'name': 'karpathy-abc', 'path': '/fixture/karpathy', 'sha256': 'abc'}]
        baseline, skilled = suite.plans('cmp', ['sonnet55'], ['circuit_eval'], skills)
        self.assertEqual(baseline['runs'][0]['run_id'], 'cmp-circuit-eval-sonnet55-none')
        self.assertNotIn('--skill-set', baseline['runs'][0]['factory_args'])
        self.assertIn('--skill-set', skilled['runs'][0]['factory_args'])

    def test_efforts_are_a_dimension(self):
        args = ('cmp', ['sonnet55', 'astra6'], ['circuit_eval', 'database_migration'])
        skills = [{'name': 'none', 'path': None, 'sha256': None}]
        serial = suite.plans(*args, skills, None, ['low', 'high'])
        self.assertEqual([b['batch_id'] for b in serial][:2], ['cmp-circuit-eval-low-none', 'cmp-circuit-eval-high-none'])
        runs = [r for b in serial for r in b['runs']]
        self.assertEqual(len(runs), 8)
        self.assertEqual(len({r['run_id'] for r in runs}), 8)
        astra = next(r for r in runs if r['run_id'].endswith('astra6-high-none'))['factory_args']
        self.assertEqual(astra[astra.index('--codex-effort') + 1], 'high')
        widths = {mode: [b['max_parallel'] for b in suite.plans(*args, skills, mode, ['low', 'high'])]
                  for mode in suite.PARALLEL}
        self.assertEqual(widths, {'models': [2] * 4, 'models-skills': [2] * 4,
                                  'models-skills-efforts': [4, 4], 'all': [8]})

    def test_omitted_efforts_keep_published_medium_ids(self):
        run = suite.plans('cmp', ['sonnet55'], ['circuit_eval'])[0]['runs'][0]
        self.assertEqual(run['run_id'], 'cmp-circuit-eval-sonnet55')
        self.assertIn('medium', run['factory_args'])

    def test_efforts_must_suit_every_provider(self):
        with self.assertRaises(ValueError):
            suite.plans('cmp', ['sonnet55'], ['circuit_eval'], None, None, ['xhigh'])
        suite.plans('cmp', ['astra6'], ['circuit_eval'], None, None, ['xhigh'])

    def test_existing_plans_cannot_be_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = suite.plans('example', ['sonnet55'], ['circuit_eval', 'database_migration'])
            paths = suite.save_plans(root, original)
            before = [p.read_bytes() for p in paths]
            suite.save_plans(root, original)
            with self.assertRaises(ValueError):
                suite.save_plans(root, suite.plans('example', ['astra6'], ['circuit_eval', 'database_migration']))
            self.assertEqual(before, [p.read_bytes() for p in paths])

    def test_audit_failure_stops_before_next_problem(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(suite, 'ROOT', Path(tmp)), patch.object(suite, 'load_plan'), patch.object(suite.subprocess, 'call', return_value=7) as call:
            self.assertEqual(suite.main(['--problems', 'circuit_eval', 'database_migration', '--id', 'audit', '--audit', '--models', 'sonnet55']), 7)
            self.assertEqual(call.call_count, 1)
            self.assertIn('--audit', call.call_args.args[0])

    def test_audit_reports_one_line_per_run(self):
        skills = [{'name': 'none', 'path': None, 'sha256': None}]
        config = suite.plans('rep', ['sonnet55', 'astra6'], ['circuit_eval'], skills, None, ['low'])[0]
        with tempfile.TemporaryDirectory() as tmp, patch.object(suite, 'ROOT', Path(tmp)):
            good, bad = (f"{config['batch_id']}-{r['run_id']}-audit" for r in config['runs'])
            status = Path(tmp) / 'intermediate/batches' / (config['batch_id'] + '-audit') / 'status.json'
            status.parent.mkdir(parents=True)
            status.write_text(json.dumps({'runs': {good: {'status': 'complete'}, bad: {'status': 'failed'}}}))
            log = Path(tmp) / 'intermediate/runs' / bad / 'controller.log'
            log.parent.mkdir(parents=True)
            log.write_text('boom\n')
            with patch.object(suite.subprocess, 'call', return_value=1), patch('builtins.print') as out:
                self.assertEqual(suite.audit([Path('p')], [config], False), 1)
            text = '\n'.join(str(c.args[0]) for c in out.call_args_list)
            self.assertIn('\u2713 claude circuit_eval / claude-sonnet-5-5 / low / none', text)
            self.assertIn('\u2717 codex  circuit_eval / gpt-6-astra / low / none', text)
            self.assertIn('boom', text)
            self.assertIn('Audit: 1/2 passed', text)

    def test_audit_explains_launcher_failure_after_all_runs_pass(self):
        skills = [{'name': 'none', 'path': None, 'sha256': None}]
        config = suite.plans('rep', ['sonnet55'], ['circuit_eval'], skills, None, ['low'])[0]
        rid = f"{config['batch_id']}-{config['runs'][0]['run_id']}-audit"
        with tempfile.TemporaryDirectory() as tmp, patch.object(suite, 'ROOT', Path(tmp)):
            status = Path(tmp) / 'intermediate/batches' / (config['batch_id'] + '-audit') / 'status.json'
            status.parent.mkdir(parents=True)
            status.write_text(json.dumps({'runs': {rid: {'status': 'complete'}}}))
            def call(command, **kwargs):
                kwargs['stdout'].write('RuntimeError: Harness changed during batch\n')
                return 1
            with patch.object(suite.subprocess, 'call', side_effect=call), patch('builtins.print') as out:
                self.assertEqual(suite.audit([Path('p')], [config], False), 1)
            text = '\n'.join(str(c.args[0]) for c in out.call_args_list)
            self.assertIn('\u2713', text)
            self.assertIn('Harness changed during batch', text)

    def test_audit_reset_replaces_audit_state_until_a_real_run_starts(self):
        one = suite.plans('exp', ['sonnet55'], ['circuit_eval'])
        two = suite.plans('exp', ['opus55'], ['circuit_eval'])
        with tempfile.TemporaryDirectory() as tmp, patch.object(suite, 'ROOT', Path(tmp)):
            root = Path(tmp)
            suite.save_plans(root / 'intermediate/plans/exp', one)
            stale = root / 'intermediate/batches' / (one[0]['batch_id'] + '-audit')
            stale.mkdir(parents=True)
            suite.reset_audit('exp', two)  # Nothing started: plan and audit leftovers are replaced.
            self.assertFalse(stale.exists())
            self.assertFalse((root / 'intermediate/plans/exp').exists())
            suite.save_plans(root / 'intermediate/plans/exp', one)
            (root / 'intermediate/runs' / one[0]['runs'][0]['run_id']).mkdir(parents=True)
            suite.reset_audit('exp', one)  # Same plan after a real run started: allowed, plan kept.
            self.assertTrue((root / 'intermediate/plans/exp/schedule.json').exists())
            with self.assertRaises(ValueError):
                suite.reset_audit('exp', two)

    def test_model_list_selects_only_requested_models(self):
        with patch.object(suite, 'plans', wraps=suite.plans) as build, patch('builtins.print'):
            self.assertEqual(suite.main(['--problems', 'circuit_eval', 'database_migration', '--id', 'preview', '--models', 'sonnet55', 'opus55', 'astra6']), 0)
            self.assertEqual(build.call_args.args[1], ['sonnet55', 'opus55', 'astra6'])

    def test_duplicate_models_are_rejected(self):
        with patch('sys.stderr'):
            with self.assertRaises(SystemExit) as caught:
                suite.main(['--problems', 'circuit_eval', 'database_migration', '--id', 'preview', '--models', 'sonnet55', 'sonnet55'])
        self.assertEqual(caught.exception.code, 2)

    def test_models_are_required(self):
        with patch('sys.stderr'), patch.object(suite.subprocess, 'call') as call:
            with self.assertRaises(SystemExit) as caught:
                suite.main(['--problems', 'circuit_eval', 'database_migration', '--id', 'preview'])
            self.assertEqual(caught.exception.code, 2)
            call.assert_not_called()

    def test_problems_required_or_invalid_prevents_execution(self):
        for selection in [[], ['--problems', 'unknown'],
                          ['--problems', 'circuit_eval', 'circuit_eval']]:
            with self.subTest(selection=selection), patch('sys.stderr'), patch.object(suite.subprocess, 'call') as call:
                with self.assertRaises(SystemExit) as caught:
                    suite.main(['--id', 'example', '--models', 'sonnet55', '--run', *selection])
                self.assertEqual(caught.exception.code, 2)
                call.assert_not_called()

    def test_selected_problems_determine_plan_names_and_order(self):
        selected = ['dynamic_config_service_api', 'code_search']
        configs = suite.plans('example', ['sonnet55'], selected)
        with tempfile.TemporaryDirectory() as tmp:
            paths = suite.save_plans(Path(tmp), configs)
            self.assertEqual([p.stem for p in paths], ['example-'+p.replace('_','-') for p in selected])
            self.assertEqual(len(list(Path(tmp).glob('*.json'))), 3)
            for path, problem in zip(paths, selected):
                self.assertEqual(suite.json.loads(path.read_text())['runs'][0]['factory_args'][1], problem)

    def test_run_uses_selected_order_and_session_count(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(suite, 'ROOT', Path(tmp)), patch.object(suite, 'load_plan'), patch.object(suite.subprocess, 'call', return_value=0) as call, patch('builtins.print') as output:
            self.assertEqual(suite.main(['--id', 'example', '--models', 'sonnet55', 'astra6',
                                         '--problems', 'dynamic_config_service_api', 'code_search', '--run']), 0)
            command = call.call_args.args[0]
            paths = [command[i+1] for i, arg in enumerate(command) if arg == '--plan']
            self.assertEqual([Path(p).stem for p in paths], ['example-dynamic-config-service-api', 'example-code-search'])
            self.assertIn('Launching 18 sessions', output.call_args.args[0])

    def test_cartesian_modes_preserve_every_chain_and_barriers(self):
        skills=[{'name':s,'path':'/fixture/'+s,'sha256':s} for s in ['one','two','three']]
        problems=['circuit_eval','database_migration','dynamic_config_service_api']
        models=['sonnet55','opus55','astra6']
        for mode,batches,width in [(None,9,1),('models',9,3),('models-skills',3,9),('all',1,27)]:
            with self.subTest(mode=mode):
                plans=suite.plans('matrix',models,problems,skills,mode)
                self.assertEqual(len(plans),batches)
                self.assertTrue(all(p['max_parallel']==width for p in plans))
                runs=[r for p in plans for r in p['runs']]
                self.assertEqual(len({r['run_id'] for r in runs}),27)
                combinations=set()
                for r in runs:
                    f=r['factory_args']
                    combinations.add(tuple(f[f.index(k)+1] for k in ['--problem','--build-model','--skill-set']))
                    self.assertNotIn('--resume-run',f)
                self.assertEqual(len(combinations),27)
                if mode!='all':
                    for p in plans:
                        self.assertEqual(len({r['factory_args'][1] for r in p['runs']}),1)
                if mode in (None,'models'):
                    for p in plans:
                        self.assertEqual(len({r['factory_args'][-3] for r in p['runs']}),1)

    def test_concurrency_change_rejects_existing_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite.save_plans(Path(tmp),suite.plans('x',['sonnet55','astra6'],['circuit_eval']))
            with self.assertRaises(ValueError):
                suite.save_plans(Path(tmp),suite.plans('x',['sonnet55','astra6'],['circuit_eval'],parallel='all'))
