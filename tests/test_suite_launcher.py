import importlib.util
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
