import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from kojo import dashboard


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        cp = self.base / 'results/runs/run-a/build/checkpoint_2'
        write(cp / 'run.json', {'status': 'complete', 'model': 'm', 'reasoning': 'medium',
                                'elapsed_seconds': 90, 'api_price_equivalent_usd': 1.5})
        write(cp / 'evaluation.json', {'duration': 3, 'tests': {
            'checkpoint_2-Core': {'passed': ['a', 'b'], 'failed': ['c']},
            'checkpoint_1-Regression': {'passed': ['a']}}})
        write(self.base / 'intermediate/batches/b1/plan.json', {})
        write(self.base / 'intermediate/batches/b1/status.json',
              {'action': 'run', 'cancelled': False, 'runs': {'run-a': {'status': 'running'}}})
        (self.base / 'intermediate/runs/run-a').mkdir(parents=True)
        (self.base / 'intermediate/runs/run-a/controller.log').write_text('hello log')
        server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.make_handler(self.base))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f'http://127.0.0.1:{server.server_port}'

    def fetch(self, path):
        with urllib.request.urlopen(self.url + path) as r:
            return r.read().decode()

    def test_overview_and_detail(self):
        data = json.loads(self.fetch('/api/overview'))
        run = data['runs'][0]
        self.assertEqual((run['id'], run['status'], run['batch']), ('run-a', 'running', 'b1'))
        self.assertEqual(run['strict_passed'], 0)
        self.assertEqual(data['batches'][0]['counts'], {'running': 1})
        detail = json.loads(self.fetch('/api/runs/run-a'))
        row = detail['checkpoints'][0]
        self.assertEqual(row['current'], {'passed': 2, 'total': 3})
        self.assertEqual(row['prior'], {'passed': 1, 'total': 1})
        self.assertEqual(row['failed'][0]['name'], 'c')
        self.assertFalse(row['strict'])

    def test_leaderboard_metrics(self):
        cp = self.base / 'results/runs/run-b/build/checkpoint_2'
        write(cp / 'run.json', {'status': 'complete', 'model': 'm2', 'reasoning': 'low',
                                'elapsed_seconds': 120, 'api_price_equivalent_usd': 2.0})
        write(cp / 'evaluation.json', {'tests': {
            'checkpoint_2-Core': {'passed': ['a'], 'failed': []},
            'checkpoint_1-Regression': {'passed': ['a'], 'failed': ['r']}}})
        write(self.base / 'results/runs/run-b/manifest.json',
              {'problem': 'p', 'review_loops': 1, 'skills': {'name': 'sk-0123456789-0123456789'}})
        rows = {r['key']: r for r in json.loads(self.fetch('/api/leaderboard?by=model'))['rows']}
        self.assertEqual((rows['m2']['strict'], rows['m2']['iso'], rows['m2']['core']), (0, 100, 100))
        self.assertAlmostEqual(rows['m2']['partial'], 100 * 2 / 3)
        self.assertEqual((rows['m']['iso'], rows['m']['core']), (0, 0))
        self.assertEqual(rows['m2']['minutes_mean'], 2)
        by_skill = {r['key'] for r in json.loads(self.fetch('/api/leaderboard?by=skill'))['rows']}
        self.assertEqual(by_skill, {'sk', 'none'})
        factory = {r['key'] for r in json.loads(self.fetch('/api/leaderboard?by=factory'))['rows']}
        self.assertEqual(factory, {'build only', 'build + review x1'})
        with self.assertRaises(urllib.error.HTTPError):
            self.fetch('/api/leaderboard?by=bogus')

    def test_leaderboard_filters_and_pooling(self):
        for rid, batch, model, effort in (('run-b', 'b2', 'm2', 'medium'), ('run-c', 'b3', 'm3', 'low')):
            cp = self.base / 'results/runs' / rid / 'build/checkpoint_1'
            write(cp / 'run.json', {'status': 'complete', 'model': model, 'reasoning': effort})
            write(cp / 'evaluation.json', {'tests': {'checkpoint_1-Core': {'passed': ['a'], 'failed': []}}})
            write(self.base / 'results/runs' / rid / 'run-config.json', {'batch_id': batch})
            write(self.base / 'results/runs' / rid / 'manifest.json', {'problem': 'p'})
        write(self.base / 'results/runs/run-a/manifest.json', {'problem': 'p'})
        data = json.loads(self.fetch('/api/leaderboard?by=model'))
        self.assertEqual({r['key'] for r in data['rows']}, {'m', 'm2', 'm3'})
        self.assertEqual(data['pooled']['problem'], ['p'])
        self.assertEqual(data['pooled']['effort'], ['low', 'medium'])
        data = json.loads(self.fetch('/api/leaderboard?by=model&batch=b2&batch=b3'))
        self.assertEqual({r['key'] for r in data['rows']}, {'m2', 'm3'})
        self.assertEqual(data['runs'], 2)
        self.assertEqual(data['facets']['batch'], [['b2', 1], ['b3', 1], ['none', 1]])
        data = json.loads(self.fetch('/api/leaderboard?by=effort&model=m3'))
        self.assertEqual([r['key'] for r in data['rows']], ['low'])

    def test_leaderboard_then_by(self):
        cp = self.base / 'results/runs/run-b/build/checkpoint_1'
        write(cp / 'run.json', {'status': 'complete', 'model': 'm', 'reasoning': 'medium'})
        write(cp / 'evaluation.json', {'tests': {'checkpoint_1-Core': {'passed': ['a'], 'failed': []}}})
        write(self.base / 'results/runs/run-b/manifest.json', {'skills': {'name': 'sk-0123456789'}})
        data = json.loads(self.fetch('/api/leaderboard?by=model&then=skill'))
        self.assertEqual({(r['key'], r['sub']) for r in data['rows']}, {('m', 'none'), ('m', 'sk')})
        by_sub = {r['sub']: r for r in data['rows']}
        self.assertEqual((by_sub['sk']['run_ids'], by_sub['none']['run_ids']), (['run-b'], ['run-a']))
        self.assertEqual((by_sub['sk']['strict'], by_sub['none']['strict']), (100, 0))
        for bad in ('then=model', 'then=bogus'):
            with self.assertRaises(urllib.error.HTTPError):
                self.fetch('/api/leaderboard?by=model&' + bad)

    def test_experiments_are_batches_differing_in_one_parameter(self):
        def add(rid, batch, model, effort, skill, problem='p'):
            cp = self.base / 'results/runs' / rid / 'build/checkpoint_1'
            write(cp / 'run.json', {'status': 'complete', 'model': model, 'reasoning': effort})
            write(cp / 'evaluation.json', {'tests': {'checkpoint_1-Core': {'passed': ['a'], 'failed': []}}})
            write(self.base / 'results/runs' / rid / 'manifest.json',
                  {'problem': problem, 'skills': {'name': skill} if skill else None})
            write(self.base / 'results/runs' / rid / 'run-config.json', {'batch_id': batch})
        # b1 and b2 sweep the same skills and differ only in model; b3 also changes effort.
        for batch, model, effort in (('b1', 'ma', 'low'), ('b2', 'mb', 'low'), ('b3', 'mc', 'high')):
            for skill in (None, 'sk-0123456789', 'tk-0123456789'):
                add(f'{batch}-{(skill or "no")[:2]}', batch, model, effort, skill)
        add('other-problem', 'b4', 'ma', 'low', None, problem='q')
        data = json.loads(self.fetch('/api/leaderboard?by=model'))
        exps = {(e['vary'], tuple(e['batches'])) for e in data['experiments']}
        self.assertIn(('model', ('b1', 'b2')), exps)
        self.assertFalse([e for e in exps if 'b3' in e[1]])  # differs from the others in two settings
        self.assertFalse([e for e in exps if 'b4' in e[1]])  # a different problem never combines
        both = next(e for e in data['experiments'] if e['batches'] == ['b1', 'b2'])
        self.assertEqual(len(both['runs']), 6)
        self.assertEqual(both['fixed']['skill'], ['none', 'sk', 'tk'])
        self.assertEqual(both['fixed']['effort'], ['low'])
        picked = json.loads(self.fetch(f"/api/leaderboard?by=model&then=skill&experiment={both['id']}"))
        self.assertEqual(picked['runs'], 6)
        self.assertEqual({(r['key'], r['sub']) for r in picked['rows']},
                         {(m, s) for m in ('ma', 'mb') for s in ('none', 'sk', 'tk')})
        self.assertEqual(json.loads(self.fetch('/api/leaderboard?by=skill&experiment=nope'))['runs'], 0)

    def test_experiment_matching_ignores_ordering(self):
        def add(rid, batch, model, skill):
            cp = self.base / 'results/runs' / rid / 'build/checkpoint_1'
            write(cp / 'run.json', {'status': 'complete', 'model': model, 'reasoning': 'low'})
            write(cp / 'evaluation.json', {'tests': {'checkpoint_1-Core': {'passed': ['a'], 'failed': []}}})
            write(self.base / 'results/runs' / rid / 'manifest.json',
                  {'problem': 'p', 'skills': {'name': skill} if skill else None})
            write(self.base / 'results/runs' / rid / 'run-config.json', {'batch_id': batch})
        # Same skills, created in opposite orders and with a repeat in b2; models differ.
        for i, skill in enumerate((None, 'sk-0123456789', 'tk-0123456789')):
            add(f'b1-{i}', 'b1', 'ma', skill)
        for i, skill in enumerate(('tk-0123456789', 'sk-0123456789', None, 'sk-0123456789')):
            add(f'b2-{i}', 'b2', 'mb', skill)
        data = json.loads(self.fetch('/api/leaderboard?by=model'))
        both = [e for e in data['experiments'] if e['batches'] == ['b1', 'b2']]
        self.assertEqual(len(both), 1)
        self.assertEqual(both[0]['fixed']['skill'], ['none', 'sk', 'tk'])
        self.assertEqual(len(both[0]['runs']), 7)

    def test_log_and_page(self):
        self.assertEqual(self.fetch('/api/runs/run-a/log'), 'hello log')
        self.assertIn('<title>Kojo Runs</title>', self.fetch('/'))

    def test_rejects_unknown_and_traversal(self):
        for path in ('/api/runs/nope', '/api/runs/..%2F..%2Fetc', '/api/comparisons/x',
                     '/api/comparisons/x/charts/..%2Fa.png', '/other'):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.fetch(path)
            self.assertEqual(ctx.exception.code, 404, path)


if __name__ == '__main__':
    unittest.main()
