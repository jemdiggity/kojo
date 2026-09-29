import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from kojo.dashboard.evaluation import summarize
from kojo.dashboard.leaderboard import experiments, leaderboard
from kojo.dashboard.server import make_handler
from kojo.dashboard.store import Run, Store


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def passing(*groups):
    """An evaluation report where every listed group passes."""
    return {'tests': {group: {'passed': ['t'], 'failed': []} for group in groups}}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def add_run(self, run_id, *, batch=None, model='m', effort='low', skill=None, problem='p',
                review_loops=0, evaluation=None, cost=1.0, seconds=60):
        """Write one graded checkpoint (number 1) for a run, with its manifest and batch."""
        checkpoint = self.base / 'results/runs' / run_id / 'build/checkpoint_1'
        write(checkpoint / 'run.json', {'status': 'complete', 'model': model, 'reasoning': effort,
                                        'elapsed_seconds': seconds, 'api_price_equivalent_usd': cost})
        write(checkpoint / 'evaluation.json', evaluation or passing('checkpoint_1-Core'))
        write(self.base / 'results/runs' / run_id / 'manifest.json',
              {'problem': problem, 'review_loops': review_loops, 'skills': {'name': skill} if skill else None})
        if batch:
            write(self.base / 'results/runs' / run_id / 'run-config.json', {'batch_id': batch})


class SummarizeTests(unittest.TestCase):
    def test_separates_current_tests_from_regressions(self):
        report = {'tests': {'checkpoint_2-Core': {'passed': ['a', 'b'], 'failed': ['c']},
                            'checkpoint_1-Regression': {'passed': ['r'], 'failed': []}}}
        result = summarize(report, 2)
        self.assertEqual(result['current'], {'passed': 2, 'total': 3})
        self.assertEqual(result['prior'], {'passed': 1, 'total': 1})
        self.assertEqual(result['failed'], [{'group': 'checkpoint_2-Core', 'name': 'c', 'state': 'failed'}])
        self.assertEqual((result['strict'], result['iso'], result['core']), (False, False, False))
        self.assertAlmostEqual(result['partial'], 3 / 4)

    def test_iso_ignores_regressions_but_strict_does_not(self):
        report = {'tests': {'checkpoint_2-Functionality': {'passed': ['a'], 'failed': []},
                            'checkpoint_1-Regression': {'passed': [], 'failed': ['r']}}}
        result = summarize(report, 2)
        self.assertEqual((result['strict'], result['iso']), (False, True))

    def test_core_needs_a_core_test_and_no_core_failure(self):
        self.assertTrue(summarize(passing('checkpoint_1-Core'), 1)['core'])
        self.assertFalse(summarize(passing('checkpoint_1-Error'), 1)['core'])
        self.assertFalse(summarize({'tests': {}}, 1)['strict'])


class ExperimentTests(unittest.TestCase):
    @staticmethod
    def run_of(run_id, batch, model, skill, effort='low', problem='p'):
        return Run(run_id, batch, {'model': model, 'skill': skill, 'factory': 'build only',
                                   'effort': effort, 'problem': problem})

    def sweep(self, batch, model, skills, **kwargs):
        return [self.run_of(f'{batch}-{i}-{s}', batch, model, s, **kwargs) for i, s in enumerate(skills)]

    def test_batches_differing_in_one_parameter_combine(self):
        runs = self.sweep('b1', 'ma', ['none', 'sk', 'tk']) + self.sweep('b2', 'mb', ['tk', 'sk', 'none', 'sk'])
        (found,) = experiments(runs)
        self.assertEqual((found['vary'], found['batches']), ('model', ['b1', 'b2']))
        self.assertEqual(found['fixed']['skill'], ['none', 'sk', 'tk'])  # order and repeats are ignored
        self.assertEqual(len(found['runs']), 7)

    def test_batches_differing_in_two_parameters_do_not_combine(self):
        runs = self.sweep('b1', 'ma', ['none', 'sk']) + self.sweep('b2', 'mb', ['none', 'sk'], effort='high')
        self.assertEqual(experiments(runs), [])

    def test_different_problems_never_combine(self):
        runs = self.sweep('b1', 'ma', ['none']) + self.sweep('b2', 'mb', ['none'], problem='q')
        self.assertEqual(experiments(runs), [])


class LeaderboardTests(unittest.TestCase):
    @staticmethod
    def run_of(run_id, batch, model, skill, strict, iso=None):
        checkpoint = {'strict': strict, 'iso': strict if iso is None else iso, 'core': strict, 'partial': 1.0 if strict else 0.5,
                      'cost_usd': 2.0, 'elapsed_seconds': 120}
        return Run(run_id, batch, {'model': model, 'skill': skill, 'factory': 'build only', 'effort': 'low', 'problem': 'p'},
                   [checkpoint])

    def test_percentages_and_costs(self):
        runs = [self.run_of('r1', 'b', 'm', 'none', True), self.run_of('r2', 'b', 'm', 'none', False, iso=True)]
        (row,) = leaderboard(runs, 'model')['rows']
        self.assertEqual((row['strict'], row['iso'], row['partial']), (50, 100, 75))
        self.assertEqual((row['cost_mean'], row['cost_total'], row['minutes_mean']), (2.0, 4.0, 2.0))
        self.assertEqual(row['run_ids'], ['r1', 'r2'])

    def test_then_by_and_filters(self):
        runs = [self.run_of('r1', 'b1', 'ma', 'none', True), self.run_of('r2', 'b1', 'ma', 'sk', False),
                self.run_of('r3', 'b2', 'mb', 'none', False)]
        both = leaderboard(runs, 'model', then='skill')
        self.assertEqual({(r['key'], r['sub']) for r in both['rows']}, {('ma', 'none'), ('ma', 'sk'), ('mb', 'none')})
        only = leaderboard(runs, 'model', filters={'batch': ['b2']})
        self.assertEqual([r['key'] for r in only['rows']], ['mb'])
        self.assertEqual(only['pooled']['batch'], ['b2'])
        self.assertEqual(only['facets']['batch'], [('b1', 2), ('b2', 1)])

    def test_experiment_selects_its_runs(self):
        runs = [self.run_of('r1', 'b1', 'ma', 'none', True), self.run_of('r2', 'b2', 'mb', 'none', False),
                self.run_of('r3', 'b3', 'mc', 'sk', True)]
        (found,) = experiments(runs)
        picked = leaderboard(runs, 'model', experiment=found['id'])
        self.assertEqual(picked['runs'], 2)
        self.assertEqual(leaderboard(runs, 'model', experiment='nope')['runs'], 0)

    def test_rejects_unknown_groupings(self):
        for kwargs in ({'by': 'bogus'}, {'by': 'model', 'then': 'model'}, {'by': 'model', 'then': 'bogus'}):
            with self.assertRaises(ValueError):
                leaderboard([], **kwargs)


class StoreTests(Fixture):
    def test_graded_run_settings(self):
        self.add_run('run-a', batch='b1', model='m1', effort='medium', skill='karpathy-0123456789-0123456789', review_loops=2)
        (run,) = Store(self.base).graded_runs()
        self.assertEqual((run.id, run.batch), ('run-a', 'b1'))
        self.assertEqual(run.settings, {'model': 'm1', 'effort': 'medium', 'skill': 'karpathy',
                                        'factory': 'build + review x2', 'problem': 'p'})

    def test_run_without_a_batch_is_its_own_batch(self):
        self.add_run('run-a')
        self.assertEqual(Store(self.base).graded_runs()[0].batch, 'run-a')

    def test_final_checkpoint_prefers_fix_and_sums_cost(self):
        self.add_run('run-a', cost=1.0)
        fix = self.base / 'results/runs/run-a/fix/checkpoint_1'
        write(fix / 'run.json', {'status': 'complete', 'model': 'm', 'reasoning': 'low',
                                 'elapsed_seconds': 30, 'api_price_equivalent_usd': 0.5})
        write(fix / 'evaluation.json', {'tests': {'checkpoint_1-Core': {'passed': [], 'failed': ['x']}}})
        (run,) = Store(self.base).graded_runs()
        (checkpoint,) = run.checkpoints
        self.assertEqual((checkpoint['role'], checkpoint['strict'], checkpoint['cost_usd'], checkpoint['elapsed_seconds']),
                         ('fix', False, 1.5, 90))


class ServerTests(Fixture):
    def setUp(self):
        super().setUp()
        self.add_run('run-a', batch='b1', evaluation={'tests': {
            'checkpoint_1-Core': {'passed': ['a', 'b'], 'failed': ['c']}}})
        write(self.base / 'intermediate/batches/b1/plan.json', {})
        write(self.base / 'intermediate/batches/b1/status.json',
              {'action': 'run', 'cancelled': False, 'runs': {'run-a': {'status': 'running'}}})
        (self.base / 'intermediate/runs/run-a').mkdir(parents=True)
        (self.base / 'intermediate/runs/run-a/controller.log').write_text('hello log')
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.base))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f'http://127.0.0.1:{server.server_port}'

    def fetch(self, path):
        with urllib.request.urlopen(self.url + path) as response:
            return response.read().decode()

    def status(self, path):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.fetch(path)
        return caught.exception.code

    def test_overview_and_run_detail(self):
        overview = json.loads(self.fetch('/api/overview'))
        run = overview['runs'][0]
        self.assertEqual((run['id'], run['status'], run['batch'], run['strict_passed']), ('run-a', 'running', 'b1', 0))
        self.assertAlmostEqual(run['partial_pass'], 2 / 3)
        self.assertEqual(overview['batches'][0]['counts'], {'running': 1})
        checkpoint = json.loads(self.fetch('/api/runs/run-a'))['checkpoints'][0]
        self.assertEqual(checkpoint['current'], {'passed': 2, 'total': 3})
        self.assertEqual(checkpoint['failed'][0]['name'], 'c')

    def test_leaderboard_endpoint(self):
        data = json.loads(self.fetch('/api/leaderboard?by=model&then=skill&batch=b1'))
        self.assertEqual([(r['key'], r['sub']) for r in data['rows']], [('m', 'none')])
        self.assertEqual(self.status('/api/leaderboard?by=bogus'), 400)

    def test_log_and_static_files(self):
        self.assertEqual(self.fetch('/api/runs/run-a/log'), 'hello log')
        self.assertIn('<title>Kojo Runs</title>', self.fetch('/'))
        self.assertIn('parseRoute', self.fetch('/static/app.js'))
        self.assertIn('--bg', self.fetch('/static/style.css'))

    def test_unknown_and_traversal_paths_are_not_found(self):
        for path in ('/api/runs/nope', '/api/runs/..%2F..%2Fetc', '/api/comparisons/x', '/static/missing.js',
                     '/static/..%2Fserver.py', '/api/comparisons/x/charts/..%2Fa.png', '/other'):
            self.assertEqual(self.status(path), 404, path)


if __name__ == '__main__':
    unittest.main()
