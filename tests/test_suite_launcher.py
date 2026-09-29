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
            self.assertEqual(suite.main(['--id', 'preview', '--models', 'sonnet55']), 0)
            save.assert_not_called()
            call.assert_not_called()

    def test_order_and_settings(self):
        plans = suite.plans('example', suite.DEFAULT_MODELS)
        self.assertEqual(len(plans), 3)
        for problem, plan in zip(suite.PROBLEMS, plans):
            self.assertEqual(plan['max_parallel'], 6)
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
            original = suite.plans('example', ['sonnet55'])
            paths = suite.save_plans(root, original)
            before = [p.read_bytes() for p in paths]
            suite.save_plans(root, original)
            with self.assertRaises(ValueError):
                suite.save_plans(root, suite.plans('example', ['astra6']))
            self.assertEqual(before, [p.read_bytes() for p in paths])

    def test_audit_failure_stops_before_next_problem(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(suite, 'ROOT', Path(tmp)), patch.object(suite, 'load_plan'), patch.object(suite.subprocess, 'call', return_value=7) as call:
            self.assertEqual(suite.main(['--id', 'audit', '--audit', '--models', 'sonnet55']), 7)
            self.assertEqual(call.call_count, 1)
            self.assertIn('--audit', call.call_args.args[0])

    def test_model_list_selects_only_requested_models(self):
        with patch.object(suite, 'plans', wraps=suite.plans) as build, patch('builtins.print'):
            self.assertEqual(suite.main(['--id', 'preview', '--models', 'sonnet55', 'opus55', 'astra6']), 0)
            self.assertEqual(build.call_args.args[1], ['sonnet55', 'opus55', 'astra6'])

    def test_duplicate_models_are_rejected(self):
        with patch('sys.stderr'):
            with self.assertRaises(SystemExit) as caught:
                suite.main(['--id', 'preview', '--models', 'sonnet55', 'sonnet55'])
        self.assertEqual(caught.exception.code, 2)

    def test_models_are_required(self):
        with patch('sys.stderr'), patch.object(suite.subprocess, 'call') as call:
            with self.assertRaises(SystemExit) as caught:
                suite.main(['--id', 'preview'])
            self.assertEqual(caught.exception.code, 2)
            call.assert_not_called()
