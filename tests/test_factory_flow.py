"""The factory description language and the flow it drives, with fake inference."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from kojo import factory, factory_spec
from kojo.factory_spec import FactoryError, parse, verdict_of

REAL = Path(__file__).resolve().parents[1]
LOOP = """
build    = luna6
refactor = opus55:high
review   = opus55:high
fix      = luna6
qa       = sonnet55
build -> refactor -> review
review -[fail, max 5]-> fix -> review
review -> qa
qa -[fail, max 2]-> build
qa -[pass]-> done
"""
REVIEW_LOOP = """
build    = luna6
refactor = opus55:high
review   = opus55:high
fix      = luna6
build -> refactor -> review
review -[fail, max 5]-> fix -> review
"""


class LanguageTests(unittest.TestCase):
    def test_stages_default_kind_effort_and_aliases(self):
        f = parse('build = luna6\\nchecker = review astra6:high\\nbuild -> checker'.replace('\\n', '\n'))
        self.assertEqual(f.stages['build'], factory_spec.Stage('build', 'build', 'gpt-6-luna', 'medium'))
        self.assertEqual(f.stages['checker'], factory_spec.Stage('checker', 'review', 'gpt-6-astra', 'high'))
        self.assertEqual(f.start, 'build')

    def test_arrows_carry_conditions_and_limits(self):
        f = parse(LOOP)
        self.assertEqual([(e.src, e.dst, e.when, e.limit) for e in f.edges][2:],
                         [('review', 'fix', 'fail', 5), ('fix', 'review', None, None), ('review', 'qa', None, None),
                          ('qa', 'build', 'fail', 2), ('qa', 'done', 'pass', None)])

    def test_a_lone_build_stage_needs_no_flow(self):
        self.assertEqual(parse('build = sonnet55:low').max_sessions(), 1)

    def test_bundled_factories_load(self):
        names = sorted(p.stem for p in (REAL/'configs/factories').glob('*.factory'))
        self.assertGreaterEqual(len(names), 5)
        for name in names:
            factory_spec.load(name)

    def test_worst_case_sessions(self):
        self.assertEqual(parse('build = luna6\nreview = astra6\nfix = luna6\nbuild -> review -> fix').max_sessions(), 3)
        # build, refactor, review, then 5 x (fix, review).
        self.assertEqual(parse(REVIEW_LOOP).max_sessions(), 13)

    def test_rejections(self):
        base = 'build = luna6\nreview = astra6\nfix = luna6\n'
        for text, message in [
            (base + 'build -> review -> fix -> review', 'no \\[max N\\]'),
            (base + 'build -[fail]-> review', 'gives no verdict'),
            (base + 'build -> fix', 'needs a review or qa'),
            (base + 'build -> review\nreview -> ghost', 'undefined stage'),
            (base + 'build -> review', 'unreachable'),
            ('review = astra6\nbuild = luna6\nreview -> build', 'start at a build'),
            ('build = luna7\nbuild -> done', 'unknown model'),
            ('build = sonnet55:max', 'supports efforts'),
            ('build = luna6\nbuild = luna6', 'defined twice'),
            ('polish = luna6', 'unknown kind'),
            (base + 'build -> review -[max 0]-> fix', 'unknown arrow option'),
            (base + 'build -> review -[soon]-> fix', 'unknown arrow option'),
            ('build = luna6\nnonsense here', 'expected'),
        ]:
            with self.subTest(text=text), self.assertRaisesRegex(FactoryError, message):
                parse(text)

    def test_load_resolves_names_and_refuses_bad_ones(self):
        with self.assertRaises(FactoryError):
            factory_spec.load('../etc')
        with self.assertRaisesRegex(FactoryError, 'No such factory'):
            factory_spec.load('nonesuch')

    def test_verdicts(self):
        self.assertEqual(verdict_of('Looks good.\nVERDICT: PASS'), 'pass')
        self.assertEqual(verdict_of('verdict: fail  \n\n'), 'fail')
        self.assertEqual(verdict_of('VERDICT: PASS\nbut then more'), 'fail')  # Only the last line counts.
        self.assertEqual(verdict_of(''), 'fail')


class FlowTests(unittest.TestCase):
    def walk(self, text, verdicts, checkpoint=1):
        """Run one checkpoint; read stages answer from the scripted verdicts."""
        flow = parse(text)
        script, calls = iter(verdicts), []
        with tempfile.TemporaryDirectory() as directory:
            def session(stage, n, source, feedback=None, attempt=1):
                calls.append((stage, attempt, feedback))
                run = Path(directory)/f'{stage}-{attempt}'
                run.mkdir()
                if not flow.stages[stage].edits:
                    (run/'answer.txt').write_text(f'report {len(calls)}\nVERDICT: {next(script)}')
                return run
            trace = []
            final = factory.run_flow(flow, session, checkpoint, None, trace)
        return calls, trace, final.parent.name if final else None

    def test_review_loop_stops_at_its_limit(self):
        text = REVIEW_LOOP.replace('max 5', 'max 2')
        calls, trace, final = self.walk(text, ['FAIL'] * 3)
        self.assertEqual([(s, a) for s, a, _ in calls],
                         [('build', 1), ('refactor', 1), ('review', 1), ('fix', 1), ('review', 2), ('fix', 2), ('review', 3)])
        self.assertEqual(final, 'fix-2')
        self.assertEqual(trace[-1]['next'], 'done')

    def test_review_loop_ends_early_on_pass(self):
        calls, _, final = self.walk(REVIEW_LOOP, ['FAIL', 'PASS'])
        self.assertEqual([s for s, _, _ in calls], ['build', 'refactor', 'review', 'fix', 'review'])
        self.assertEqual(final, 'fix-1')

    def test_fix_gets_review_text_and_only_the_next_edit_uses_it(self):
        calls, _, _ = self.walk(LOOP, ['FAIL', 'PASS', 'PASS'])
        feedback = {stage: fb for stage, _, fb in calls if stage in ('fix', 'refactor')}
        self.assertTrue(feedback['fix'].startswith('report 3'))
        self.assertIsNone(feedback['refactor'])

    def test_qa_failure_returns_to_build_with_its_report_then_gives_up(self):
        calls, _, _ = self.walk(LOOP, ['PASS', 'FAIL', 'PASS', 'FAIL', 'PASS', 'FAIL'])
        # review, qa fail -> build#2 (with the qa report), review, qa fail -> build#3, review, qa fail: cap spent.
        self.assertEqual([(s, a) for s, a, _ in calls if s in ('build', 'qa')],
                         [('build', 1), ('qa', 1), ('build', 2), ('qa', 2), ('build', 3), ('qa', 3)])
        builds = [fb for s, _, fb in calls if s == 'build']
        self.assertIsNone(builds[0])
        self.assertTrue(builds[1].startswith('report'))
        self.assertEqual(len(calls), 12)  # Three passes of build, refactor, review, qa; the second failure limit ends it.
        self.assertLessEqual(len(calls), parse(LOOP).max_sessions())

    def test_qa_pass_finishes(self):
        calls, trace, _ = self.walk(LOOP, ['PASS', 'PASS'])
        self.assertEqual([s for s, _, _ in calls], ['build', 'refactor', 'review', 'qa'])
        self.assertEqual(trace[-1]['verdict'], 'pass')


class ControllerTests(unittest.TestCase):
    def run_main(self, flow_text, answers, extra=()):
        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (base/'configs').mkdir()
        (base/'configs/quota.json').write_text('{}')
        shutil.copytree(REAL/'configs/factory-prompts', base/'configs/factory-prompts')
        path = base/'demo.factory'
        path.write_text(flow_text)
        calls, graded = [], []
        script = iter(answers)
        backend = SimpleNamespace(protocol='fixed', runtime=base/'runtime', python='/python')

        def inference(run, instructions, prompt, seconds, *args, work_path, model, effort, **kwargs):
            name = run.parents[1].name.removeprefix('training-')
            code = work_path/'code_search'
            text = code.read_text() if code.exists() else ''
            calls.append((name, run.name, model, effort, prompt))
            if name in ('review', 'qa'):
                (run/'answer.txt').parent.mkdir(parents=True, exist_ok=True)
                (run/'answer.txt').write_text(f'notes\nVERDICT: {next(script)}')
            else:
                code.write_text(text + f'{name}\n')
            run.mkdir(parents=True, exist_ok=True)
            for filename, value in [('run.json', {'status': 'complete', 'usage': {}, 'elapsed_seconds': 1, 'api_price_equivalent_usd': 0}),
                                    ('quota.json', []), ('verification.json', {}), ('transcript-verification.json', {})]:
                (run/filename).write_text(json.dumps(value))
            (run/'stock-instructions.md').write_text('stock')

        def score(rows):
            row = rows[0]
            graded.append(row['run'].parents[1].name + '/' + row['run'].name)
            (row['run']/'grading').mkdir()
            (row['run']/'grading/evaluation.json').write_text('{}')
            return [{'passed': 1, 'total': 1}]

        fake_meta = lambda name, repo=None: {'name': name, 'entry_file': 'code_search', 'checkpoints': [1, 2]}
        with contextlib.ExitStack() as stack:
            for name, value in [('BASE', base), ('protocol_digest', lambda: 'fixed'), ('preflight', lambda **kw: ({}, {'problems': {}})),
                                ('ChainBackend', lambda *a: backend), ('Experiment', lambda *a: SimpleNamespace(score=score, spec=lambda p, n: f'SPEC {n}')),
                                ('audit_external_sources', lambda *a: {'status': 'ok'}), ('metadata', fake_meta),
                                ('run_session', inference)]:
                stack.enter_context(patch.object(factory, name, value))
            stack.enter_context(patch.object(factory.claude_execution, 'run_session', inference))
            stack.enter_context(patch.object(factory, 'stage_prompt', lambda experiment, role, n, feedback, problem, verdict: f'{role}|{n}|{feedback}|{verdict}'))
            with contextlib.redirect_stdout(io.StringIO()):
                factory.main(['run', '--run-id', 'flow-test', '--factory', str(path), *extra])
        return calls, graded, base/'results/runs/flow-test'

    def test_factory_run_uses_each_stages_model_and_records_the_flow(self):
        text = 'build = luna6:high\nreview = sonnet55:low\nfix = astra6\nbuild -> review\nreview -[fail, max 3]-> fix -> review\n'
        calls, graded, root = self.run_main(text, ['FAIL', 'PASS', 'PASS'])
        # Checkpoint 1: build, review (fail), fix, review (pass). Checkpoint 2: build, review (pass).
        self.assertEqual([(c[0], c[1]) for c in calls],
                         [('build', 'checkpoint_1'), ('review', 'checkpoint_1'), ('fix', 'checkpoint_1'), ('review', 'checkpoint_1-2'),
                          ('build', 'checkpoint_2'), ('review', 'checkpoint_2')])
        self.assertEqual([c[2:4] for c in calls[:3]], [('gpt-6-luna', 'high'), ('claude-sonnet-5-5', 'low'), ('gpt-6-astra', 'medium')])
        self.assertTrue(calls[2][4].startswith('fix|1|notes'))
        self.assertTrue(all(c[4].endswith('|True') for c in calls if c[0] == 'review'))
        self.assertEqual(graded, ['training-build/checkpoint_1', 'training-fix/checkpoint_1', 'training-build/checkpoint_2'])
        manifest = json.loads((root/'manifest.json').read_text())
        self.assertEqual(manifest['condition'], 'custom-factory')
        self.assertEqual(manifest['max_sessions'], 2 * parse(text).max_sessions())
        self.assertEqual(manifest['effort_by_role'], {'build': 'high', 'review': 'low', 'fix': 'medium'})
        self.assertEqual(manifest['factory']['edges'][1], {'from': 'review', 'to': 'fix', 'when': 'fail', 'max': 3})
        self.assertEqual([t['stage'] for t in json.loads((root/'flow-trace.json').read_text())],
                         ['build', 'review', 'fix', 'review', 'build', 'review'])
        self.assertTrue((root/'fix/checkpoint_1/submission/code_search').exists())
        self.assertTrue((root/'build/checkpoint_2/evaluation.json').exists())

    def test_factory_conflicts_with_model_options(self):
        for flag in (['--build-model', 'gpt-6-luna'], ['--no-review'], ['--codex-effort', 'high']):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                factory.parse_args(['audit', '--run-id', 'x', '--factory', 'luna-sonnet-refactor', *flag])

    def test_unknown_factory_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            factory.parse_args(['audit', '--run-id', 'x', '--factory', 'nonesuch'])


class PromptTests(unittest.TestCase):
    def test_role_prompts_and_verdict_request(self):
        spec = SimpleNamespace(spec=lambda name, n: f'PUBLIC SPEC {n}')
        for role in ('refactor', 'revise', 'qa'):
            prompt = factory.stage_prompt(spec, role, 2, verdict=True)
            self.assertIn('PUBLIC SPEC 2', prompt)
            self.assertNotIn('PUBLIC SPEC 3', prompt)
            self.assertEqual('VERDICT: PASS' in prompt, role == 'qa')
        with self.assertRaises(ValueError):
            factory.stage_prompt(spec, 'fix', 2)
        self.assertNotIn('review feedback', factory.stage_prompt(spec, 'qa', 2, 'review feedback'))
        self.assertIn('review feedback', factory.stage_prompt(spec, 'refactor', 2, 'review feedback'))


if __name__ == '__main__':
    unittest.main()
