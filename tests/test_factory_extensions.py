"""Factory language extensions: attributes, deterministic stages, new kinds and the reset arrow."""
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
from kojo import checks, factory, factory_spec
from kojo.factory_spec import FactoryError, Stage, parse
from kojo.gauntlet import copy_code, hashes, sync_workspace

REAL = Path(__file__).resolve().parents[1]
BASE = 'build = luna6:low\n'


class GrammarTests(unittest.TestCase):
    def test_attributes_in_any_order_with_and_without_kind(self):
        f = parse(BASE + 'tests = tester sol61:low\nfix = luna6 guard suite\nqa = qa sol61:low prompt review\n'
                  'tests -> build -> qa\nqa -[fail]-> fix -> done')
        self.assertEqual(f.stages['fix'], Stage('fix', 'fix', 'gpt-6-luna', 'medium', guard='suite'))
        self.assertEqual(f.stages['qa'].prompt, 'review')
        g = parse('tests = tester sol61:low\nbuild = luna6 by suite x3\ntests -> build')
        self.assertEqual((g.stages['build'].attempts, g.stages['build'].by), (3, 'suite'))
        h = parse('tests = tester sol61:low\nbuild = luna6:low x2 by smoke guard suite\ntests -> build')
        self.assertEqual((h.stages['build'].effort, h.stages['build'].attempts, h.stages['build'].guard), ('low', 2, 'suite'))

    def test_check_stage(self):
        f = parse(BASE + 'gate = check smoke\nbuild -> gate\ngate -[fail, max 3, reset]-> build\n')
        self.assertEqual(f.stages['gate'], Stage('gate', 'check', '', '', checker='smoke'))
        self.assertEqual(f.stages['gate'].verdicts, True)
        self.assertFalse(f.stages['gate'].edits)
        self.assertEqual((f.edges[1].when, f.edges[1].limit, f.edges[1].reset), ('fail', 3, True))
        d = f.to_dict()
        self.assertEqual(d['edges'][0], {'from': 'build', 'to': 'gate', 'when': None, 'max': None})
        self.assertEqual(d['edges'][1]['reset'], True)
        self.assertEqual(d['stages']['gate'], {'kind': 'check', 'model': '', 'effort': '', 'checker': 'smoke'})

    def test_check_diff_takes_a_branch_argument(self):
        f = parse('tests = tester sol61:low\nbuild = luna6\nalt = branch sol61:low\ncmp = check diff alt\ntests -> build -> alt -> cmp')
        self.assertEqual(f.stages['cmp'].arg, 'alt')
        self.assertFalse(f.stages['alt'].carries)
        self.assertTrue(f.stages['alt'].edits)

    def test_to_dict_of_a_plain_factory_is_unchanged(self):
        d = parse('build = luna6\nreview = astra6\nbuild -> review').to_dict()
        self.assertEqual(d['stages']['build'], {'kind': 'build', 'model': 'gpt-6-luna', 'effort': 'medium'})

    def test_new_kinds_and_start(self):
        f = parse('plan = plan sol61:low\nbuild = luna6\nplan -> build')
        self.assertEqual((f.start, f.stages['plan'].kind), ('plan', 'plan'))
        g = parse('tests = tester sol61:low\nplan = plan sol61:low\nbuild = luna6\ntests -> plan -> build')
        self.assertEqual(g.start, 'tests')

    def test_rejections(self):
        tests = 'tests = tester sol61:low\nbuild = luna6\nfix = luna6\nreview = astra6\n'
        for text, message in [
            (BASE + 'gate = check nonesuch\nbuild -> gate', 'unknown checker'),
            (BASE + 'gate = check diff\nbuild -> gate', 'exactly one argument'),
            (BASE + 'gate = check smoke extra\nbuild -> gate', 'exactly one argument'),
            (BASE + 'gate = check\nbuild -> gate', 'expected `stage = check'),
            (tests + 'cmp = check diff review\ntests -> build -> review -> cmp', 'needs .review. to be a branch'),
            (BASE + 'gate = check suite\nbuild -> gate', 'no tester stage'),
            ('build = luna6 by suite\n', 'xN needs'),
            ('build = luna6 x3\n', 'xN needs'),
            ('build = luna6 x1 by smoke\n', 'xN takes 2 to 10'),
            ('build = luna6 x2 by repro\n', 'needs a scoring checker'),
            ('build = luna6 guard\n', 'unexpected'),
            ('build = luna6 x2 x3 by smoke\n', 'given twice'),
            ('build = luna6 prompt review\n', 'upstream prompt'),
            ('build = luna6\nreview = astra6 prompt ghost\nbuild -> review', 'unknown prompt'),
            ('build = luna6\nreview = astra6 x2 by smoke\nbuild -> review', 'code-changing stages only'),
            ('build = luna6\nalt = branch luna6 x2 by smoke\nbuild -> alt', 'takes no xN'),
            (tests + 'tests -> build -> review -[fail]-> fix -> review', 'no \\[max N\\]'),
            (BASE + 'gate = check smoke\nbuild -> gate\ngate -[reset]-> gate', 'reset. must lead to'),
            (BASE + 'review = astra6\nbuild -> review -[reset]-> done', 'reset. must lead to'),
            (BASE + 'tests = tester sol61:low\nbuild -> tests -[fail]-> build', 'gives no verdict'),
            (BASE + 'plan = plan sol61:low\nbuild -> plan -[pass]-> build', 'gives no verdict'),
            ('tests = tester sol61:low\ntests -> done', 'no build stage is reachable'),
            ('gate = check smoke\nbuild = luna6\ngate -> build', 'start at a build'),
            ('plan = plan sol61:low\ngate = check smoke\nbuild = luna6\nplan -> gate -> build', 'runs before any code'),
            ('plan = plan sol61:low\nfix = luna6\nbuild = luna6\nplan -> fix -> build', 'needs a review'),
            ('plan = plan sol61:low\nrevise = luna6\nbuild = luna6\nplan -> revise -> build', 'first code-changing stage'),
            (BASE + 'gate = check smoke\ngate = check smoke\nbuild -> gate', 'defined twice'),
        ]:
            with self.subTest(text=text), self.assertRaisesRegex(FactoryError, message):
                parse(text)

    def test_errors_name_file_and_line(self):
        with self.assertRaisesRegex(FactoryError, r'demo:3: unknown checker'):
            parse('build = luna6\n\ngate = check nope\n', 'demo')
        with self.assertRaisesRegex(FactoryError, r'demo:2: xN needs|demo:2: xN takes'):
            parse('build = luna6\nfix = luna6 x1\n', 'demo')

    def test_a_check_can_gate_a_fix(self):
        f = parse(BASE + 'fix = luna6\ngate = check smoke\nbuild -> gate\ngate -[fail, max 2]-> fix -> gate')
        self.assertEqual(f.max_sessions(), 3)


class ProgressGrammarTests(unittest.TestCase):
    def test_progress_option_parses_and_needs_a_check_source(self):
        f = parse('tests = tester sol61:low\nbuild = luna6\nfix = luna6\ngate = check safe\n'
                  'tests -> build -> gate\ngate -[fail, max 2, progress]-> fix -> gate')
        self.assertTrue(f.edges[2].progress)
        self.assertEqual(f.edges[2].limit, 2)
        self.assertEqual(f.to_dict()['edges'][2].get('progress'), True)
        with self.assertRaisesRegex(FactoryError, 'progress.*check'):
            parse('build = luna6\nqa = qa sol61:low\nfix = luna6\nbuild -> qa\nqa -[fail, max 2, progress]-> fix -> qa')

    def test_safe_needs_a_tester_like_suite(self):
        with self.assertRaisesRegex(FactoryError, 'test suite'):
            parse('build = luna6\nfix = luna6\ngate = check safe\nbuild -> gate\ngate -[fail, max 2]-> fix -> gate')

    def test_progress_is_not_an_eligibility_limit_for_worst_case_counts(self):
        f = factory_spec.load('luna-postcond-safe')
        self.assertEqual(f.max_sessions(), 1 + 1 + 3)  # tester + build + three fixes.


class AccountingTests(unittest.TestCase):
    def test_checks_are_free_and_attempts_count(self):
        f = parse(BASE + 'fix = luna6\ngate = check smoke\nbuild -> gate\ngate -[fail, max 3]-> fix -> gate\ngate -[pass]-> done')
        self.assertEqual((f.max_sessions(), f.max_checks()), (4, 4))
        g = parse('tests = tester sol61:low\nbuild = luna6 x3 by suite\ntests -> build')
        self.assertEqual((g.max_sessions(), g.max_checks()), (4, 3))
        h = parse('build = luna6\nfix = luna6 guard smoke\nqa = qa astra6\nbuild -> qa\nqa -[fail, max 2]-> fix -> qa')
        self.assertEqual((h.max_sessions(), h.max_checks()), (6, 4))

    def test_reset_loop_costs_each_reroll(self):
        f = parse(BASE + 'gate = check smoke\nbuild -> gate\ngate -[fail, max 3, reset]-> build\ngate -[pass]-> done')
        self.assertEqual(f.max_sessions(), 4)

    def test_existing_flows_count_as_before(self):
        self.assertEqual(parse('build = luna6\nreview = astra6\nfix = luna6\nbuild -> review -> fix').max_sessions(), 3)


class BundledTests(unittest.TestCase):
    def test_all_bundled_factories_load_and_report_sessions(self):
        for path in sorted((REAL/'configs/factories').glob('*.factory')):
            with self.subTest(factory=path.stem):
                f = factory_spec.load(path.stem)
                self.assertGreaterEqual(f.max_sessions(), 1)
                self.assertTrue(path.read_text().lstrip().startswith('#'), 'one-line comment first')
                for stage in f.stages.values():
                    if stage.role_file:
                        self.assertTrue((REAL/'configs/factory-prompts'/f'{stage.role_file}.md').is_file())


def result(verdict='pass', score=None, log='log', details=None):
    score = (1.0 if verdict == 'pass' else 0.0) if score is None else score
    return checks.CheckResult(verdict, int(score * 10), 10, score, log, details or {})


class Sim:
    """Fake sessions and checks over real directories, so code lineage and workspace invariants are exercised."""

    def __init__(self, tmp, text, answers=(), verdicts=(), scores=None, start=None, details=None, timeouts=()):
        self.tmp, self.flow = Path(tmp), parse(text)
        self.answers, self.verdicts = iter(answers), iter(verdicts)
        self.scores = scores or (lambda text: 1.0)
        self.details = details or (lambda text: {})  # Check details by code text, for safe/progress.
        self.timeouts = set(timeouts)  # (stage, visit) sessions that run out of time
        self.calls, self.checks, self.synced = [], [], []
        self.shared = self.tmp/'shared'
        self.shared.mkdir()
        self.source = None
        if start is not None:
            self.source = self.tmp/'start'
            self.source.mkdir()
            (self.source/'code.txt').write_text(start)
            sync_workspace(self.shared, self.source)

    def session(self, stage, n, source, feedback=None, attempt=1, **extra):
        spec = self.flow.stages[stage]
        self.calls.append({'stage': stage, 'visit': attempt, 'source': source, 'feedback': feedback, **extra})
        run = self.tmp/factory.label(n, attempt, extra.get('variant')).replace('checkpoint', stage)
        run.mkdir()
        if spec.edits:
            if spec.carries and 'variant' not in extra:
                assert hashes(self.shared, exclude_generated=True) == (hashes(source) if source else {}), f'{stage}: shared workspace out of sync'
                work = self.shared
            else:
                work = run/'src'
                copy_code(source, work)
            code = work/'code.txt'
            code.write_text((code.read_text() if code.exists() else '') + f'{stage}{attempt}{extra.get("variant", "")};')
            if (stage, attempt) in self.timeouts:  # Abandoned: the starting code is the submission, the edits are kept aside.
                copy_code(work, run/'interrupted-source')
                copy_code(source, run/'submission')
                (run/'timed-out').write_text('budget_exhausted')
            else:
                copy_code(work, run/'submission')
        elif spec.kind in ('review', 'qa'):
            (run/'answer.txt').write_text(f'report {len(self.calls)}\nVERDICT: {next(self.verdicts)}')
        else:
            (run/'answer.txt').write_text(next(self.answers, f'{stage} answer'))
        return run

    def check(self, spec, n, code, feedback, visit, ctx):
        self.checks.append({'stage': ctx['role'], 'checker': spec.checker, 'phase': ctx['phase'], 'variant': ctx['variant'], 'code': code,
                            'feedback': feedback, 'prior': ctx['prior_code'], 'side': ctx['side_codes']})
        text = (code/'code.txt').read_text() if code else ''
        if ctx['phase'].startswith('final-smoke'):
            return result('pass' if self.scores(text) > 0 else 'fail', score=self.scores(text))
        if ctx['phase'] != 'gate':
            return result(score=self.scores(text), details=self.details(text))
        verdict = next(self.verdicts)
        return result(verdict, log=f'check log {len(self.checks)}', details=self.details(text))

    def sync(self, code):
        self.synced.append(code)
        sync_workspace(self.shared, code)

    def run(self, checkpoint=1):
        self.trace = []
        self.final = factory.run_flow(self.flow, self.session, checkpoint, self.source, self.trace, self.check, self.sync)
        return self.final

    def text(self, code=None):
        return ((code or self.final)/'code.txt').read_text()

    def stages(self):
        return [c['stage'] for c in self.calls]


class FlowMechanismTests(unittest.TestCase):
    def sim(self, *args, **kwargs):
        return Sim(self.enterContext(tempfile.TemporaryDirectory()), *args, **kwargs)

    def test_check_stage_costs_no_session_and_its_log_reaches_the_fix(self):
        sim = self.sim('build = luna6\nfix = luna6\ngate = check smoke\nbuild -> gate\ngate -[fail, max 2]-> fix -> gate\ngate -[pass]-> done',
                       verdicts=['fail', 'fail', 'pass'])
        sim.run()
        self.assertEqual(sim.stages(), ['build', 'fix', 'fix'])
        self.assertEqual([c['feedback'] for c in sim.calls], [None, 'check log 1', 'check log 2'])
        self.assertEqual([c.get('origin') for c in sim.calls], [None, 'check', 'check'])
        self.assertEqual([(t['stage'], t['verdict']) for t in sim.trace], [('build', None), ('gate', 'fail'), ('fix', None), ('gate', 'fail'), ('fix', None), ('gate', 'pass')])
        gate = sim.trace[1]
        self.assertEqual((gate['kind'], gate['checker'], gate['score'], gate['total']), ('check', 'smoke', 0.0, 10))
        self.assertEqual(sim.text(), 'build1;fix1;fix2;')
        self.assertEqual(sim.synced, [])  # A plain loop never needs the workspace re-synced.

    def test_reroll_restores_the_checkpoints_start_code_without_feedback(self):
        sim = self.sim('build = luna6\ngate = check smoke\nbuild -> gate\ngate -[fail, max 3, reset]-> build\ngate -[pass]-> done',
                       verdicts=['fail', 'fail', 'pass'], start='base;')
        sim.run(2)
        self.assertEqual(sim.stages(), ['build'] * 3)
        self.assertEqual([c['source'] for c in sim.calls], [sim.source] * 3)
        self.assertEqual([c['feedback'] for c in sim.calls], [None] * 3)
        self.assertEqual(sim.text(), 'base;build3;')  # Not build1;build2; stacked on the start.
        self.assertEqual([t.get('reset') for t in sim.trace], [None, True, None, True, None, None])
        self.assertEqual(hashes(sim.shared, exclude_generated=True), hashes(sim.final))

    def test_reroll_in_the_first_checkpoint_restarts_from_nothing(self):
        sim = self.sim('build = luna6\ngate = check smoke\nbuild -> gate\ngate -[fail, max 1, reset]-> build', verdicts=['fail', 'pass'])
        sim.run()
        self.assertEqual(sim.text(), 'build2;')
        self.assertEqual(sim.synced[0], None)

    def test_reset_sync_keeps_environment_files(self):
        sim = self.sim('build = luna6\ngate = check smoke\nbuild -> gate\ngate -[fail, max 1, reset]-> build', verdicts=['fail', 'pass'], start='base;')
        (sim.shared/'venv').mkdir()
        (sim.shared/'venv/pyvenv.cfg').write_text('home')
        (sim.shared/'__pycache__').mkdir()
        sim.run()
        self.assertTrue((sim.shared/'venv/pyvenv.cfg').exists())

    def test_guard_rolls_back_a_stage_that_lowers_the_score(self):
        text = 'tests = tester sol61:low\nbuild = luna6\nqa = qa astra6\nfix = luna6 guard suite\ntests -> build -> qa\nqa -[fail]-> fix'
        sim = self.sim(text, verdicts=['FAIL'], scores=lambda t: 0.5 if 'fix1' in t else 1.0, start='base;')
        sim.run(2)
        self.assertEqual(sim.text(), 'base;build1;')  # The fix's result was rolled back.
        guard = sim.trace[-1]['guard']
        self.assertEqual((guard['before'], guard['after'], guard['rolled_back']), (1.0, 0.5, True))
        self.assertEqual(sim.synced[-1], sim.final)  # The shared workspace matches what carries forward.
        self.assertEqual(hashes(sim.shared, exclude_generated=True), hashes(sim.final))
        self.assertEqual([(c['phase'], c['checker']) for c in sim.checks], [('guard-before', 'suite'), ('guard-after', 'suite')])

    def test_guard_keeps_an_equal_or_better_result(self):
        text = 'tests = tester sol61:low\nbuild = luna6\nqa = qa astra6\nfix = luna6 guard suite\ntests -> build -> qa\nqa -[fail]-> fix'
        for scores in (lambda t: 0.7, lambda t: 0.9 if 'fix1' in t else 0.5):
            sim = self.sim(text, verdicts=['FAIL'], scores=scores, start='base;')
            sim.run(2)
            self.assertEqual(sim.text(), 'base;build1;fix1;')
            self.assertFalse(sim.trace[-1]['guard']['rolled_back'])

    def test_guard_on_the_first_checkpoint_has_nothing_to_roll_back_to(self):
        sim = self.sim('tests = tester sol61:low\nbuild = luna6 x2 by smoke guard suite\ntests -> build', scores=lambda t: 0.4)
        sim.run()
        self.assertIsNone(sim.trace[-1]['guard']['before'])
        self.assertFalse(sim.trace[-1]['guard']['rolled_back'])

    def test_safe_guard_rolls_back_a_fix_that_breaks_a_passing_case_even_if_the_score_rises(self):
        text = ('tests = tester sol61:low\nbuild = luna6\nqa = qa astra6\nfix = luna6 guard safe\n'
                'tests -> build -> qa\nqa -[fail]-> fix')
        details = lambda t: {'smoke_ok': True, 'failing': ['b', 'c', 'd'] if 'fix1' in t else ['a', 'b']}
        sim = self.sim(text, verdicts=['FAIL'], scores=lambda t: 0.9 if 'fix1' in t else 0.8, details=details, start='base;')
        sim.run(2)
        self.assertEqual(sim.text(), 'base;build1;')  # Two cases newly fail and one was repaired.
        self.assertTrue(sim.trace[-1]['guard']['rolled_back'])

    def test_safe_guard_keeps_a_fix_that_repairs_as_many_as_it_breaks(self):
        text = ('tests = tester sol61:low\nbuild = luna6\nqa = qa astra6\nfix = luna6 guard safe\n'
                'tests -> build -> qa\nqa -[fail]-> fix')
        details = lambda t: {'smoke_ok': True, 'failing': ['b', 'c'] if 'fix1' in t else ['a', 'b']}
        sim = self.sim(text, verdicts=['FAIL'], details=details, start='base;')
        sim.run(2)
        self.assertEqual(sim.text(), 'base;build1;fix1;')

    def test_safe_guard_keeps_a_fix_that_makes_a_non_starting_program_start(self):
        text = ('tests = tester sol61:low\nbuild = luna6\nqa = qa astra6\nfix = luna6 guard safe\n'
                'tests -> build -> qa\nqa -[fail]-> fix')
        details = lambda t: {'smoke_ok': 'fix1' in t, 'failing': ['x', 'y'] if 'fix1' in t else []}
        sim = self.sim(text, verdicts=['FAIL'], scores=lambda t: 0.5 if 'fix1' in t else 0.0, details=details, start='base;')
        sim.run(2)
        self.assertEqual(sim.text(), 'base;build1;fix1;')  # Its failing cases are not "new": the old code had no suite result.
        self.assertFalse(sim.trace[-1]['guard']['rolled_back'])

    def test_a_timed_out_fix_is_abandoned_and_the_run_goes_on(self):
        text = 'build = luna6\nfix = luna6\ngate = check smoke\nbuild -> gate\ngate -[fail, max 2]-> fix -> gate\ngate -[pass]-> done'
        sim = self.sim(text, verdicts=['fail', 'fail', 'pass'], timeouts={('fix', 1)}, start='base;')
        sim.run(2)
        self.assertEqual(sim.stages(), ['build', 'fix', 'fix'])
        self.assertEqual(sim.text(), 'base;build1;fix2;')  # The first fix's edits are gone; the second builds on the build.
        self.assertTrue(sim.trace[2]['timed_out'])
        self.assertEqual(hashes(sim.shared, exclude_generated=True), hashes(sim.final))
        self.assertEqual(sim.calls[2]['source'], sim.calls[1]['source'])

    def test_a_program_that_does_not_start_is_replaced_by_the_last_one_that_does(self):
        text = 'build = luna6\nfix = luna6\ngate = check smoke\nbuild -> gate\ngate -[fail, max 2]-> fix -> gate\ngate -[pass]-> done'
        sim = self.sim(text, verdicts=['fail', 'fail', 'fail'], scores=lambda t: 0.0 if 'fix2' in t else 1.0, start='base;')
        sim.run(2)
        self.assertEqual(sim.text(), 'base;build1;fix1;')  # fix2 left a broken program; fix1 started.
        last = sim.trace[-1]
        self.assertEqual((last['stage'], last['fallback_to'], last['abandoned']),
                         ('final-smoke', {'stage': 'fix', 'attempt': 1}, [{'stage': 'fix', 'attempt': 2, 'winner': None}]))
        self.assertEqual(hashes(sim.shared, exclude_generated=True), hashes(sim.final))

    def test_the_final_smoke_only_runs_in_factories_with_a_check_stage(self):
        sim = self.sim('build = luna6\nfix = luna6\nqa = qa astra6\nbuild -> qa\nqa -[fail]-> fix', verdicts=['FAIL'], scores=lambda t: 0.0)
        sim.run()
        self.assertEqual([c for c in sim.checks if c['phase'].startswith('final-smoke')], [])
        self.assertEqual(sim.text(), 'build1;fix1;')

    def test_safe_guard_keeps_a_fix_that_only_repairs(self):
        text = ('tests = tester sol61:low\nbuild = luna6\nqa = qa astra6\nfix = luna6 guard safe\n'
                'tests -> build -> qa\nqa -[fail]-> fix')
        details = lambda t: {'smoke_ok': True, 'failing': ['b'] if 'fix1' in t else ['a', 'b']}
        sim = self.sim(text, verdicts=['FAIL'], details=details, start='base;')
        sim.run(2)
        self.assertEqual(sim.text(), 'base;build1;fix1;')
        self.assertFalse(sim.trace[-1]['guard']['rolled_back'])

    def test_safe_guard_rolls_back_a_fix_that_breaks_the_program(self):
        text = ('tests = tester sol61:low\nbuild = luna6\nqa = qa astra6\nfix = luna6 guard safe\n'
                'tests -> build -> qa\nqa -[fail]-> fix')
        details = lambda t: {'smoke_ok': 'fix1' not in t, 'failing': []}
        sim = self.sim(text, verdicts=['FAIL'], details=details, start='base;')
        sim.run(2)
        self.assertEqual(sim.text(), 'base;build1;')

    def test_progress_arrow_stops_when_a_fix_changes_nothing(self):
        text = ('tests = tester sol61:low\nbuild = luna6\nfix = luna6 guard safe\ngate = check safe\n'
                'tests -> build -> gate\ngate -[fail, max 3, progress]-> fix -> gate\ngate -[pass]-> done')
        same = lambda t: {'smoke_ok': True, 'failing': ['a']}  # The fix never changes what fails.
        sim = self.sim(text, verdicts=['fail'] * 5, details=same, start='base;')
        sim.run(2)
        self.assertEqual(sim.stages().count('fix'), 1)  # Second gate fails identically: no more fixes.
        self.assertEqual([t.get('stalled') for t in sim.trace if t['stage'] == 'gate'], [None, True])
        self.assertEqual(sim.trace[-1]['next'], 'done')

    def test_progress_arrow_continues_while_failures_change(self):
        text = ('tests = tester sol61:low\nbuild = luna6\nfix = luna6\ngate = check suite\n'
                'tests -> build -> gate\ngate -[fail, max 3, progress]-> fix -> gate\ngate -[pass]-> done')
        details = lambda t: {'regressions': [], 'failures': ['x' * t.count('fix')]}
        sim = self.sim(text, verdicts=['fail', 'fail', 'fail', 'pass'], details=details, start='base;')
        sim.run(2)
        self.assertEqual(sim.stages().count('fix'), 3)
        self.assertNotIn(True, [t.get('stalled') for t in sim.trace])

    def test_best_of_n_keeps_the_best_and_all_attempts_start_from_the_same_code(self):
        scores = {'build11': 0.2, 'build12': 0.9, 'build13': 0.9}
        sim = self.sim('tests = tester sol61:low\nbuild = luna6 x3 by suite\ntests -> build', start='base;',
                       scores=lambda t: next(v for k, v in scores.items() if k in t))
        sim.run(2)
        builds = [c for c in sim.calls if c['stage'] == 'build']
        self.assertEqual([c['variant'] for c in builds], [1, 2, 3])
        self.assertEqual({c['source'] for c in builds}, {sim.source})
        self.assertEqual(sim.text(), 'base;build12;')  # Tie between 2 and 3 goes to the earliest.
        entry = sim.trace[-1]
        self.assertEqual((entry['winner'], [a['score'] for a in entry['attempts']]), (2, [0.2, 0.9, 0.9]))
        self.assertEqual(sim.synced[-1], sim.final)
        self.assertEqual(hashes(sim.shared, exclude_generated=True), hashes(sim.final))
        self.assertEqual([c['variant'] for c in sim.checks], [1, 2, 3])

    def test_the_next_stage_after_best_of_n_builds_on_the_winner(self):
        sim = self.sim('tests = tester sol61:low\nbuild = luna6 x2 by smoke\nqa = qa astra6\nfix = luna6\ntests -> build -> qa\nqa -[fail]-> fix',
                       verdicts=['FAIL'], scores=lambda t: 1.0 if 'build12' in t else 0.0)
        sim.run()
        self.assertEqual(sim.text(), 'build12;fix1;')  # Shared workspace was synced to the winner first.

    def test_tester_runs_without_code_and_its_answer_is_not_forwarded(self):
        sim = self.sim('tests = tester sol61:low\nbuild = luna6\ntests -> build', answers=['I added 40 cases'], start='base;')
        sim.run(2)
        tester, build = sim.calls
        self.assertIsNone(tester['source'])
        self.assertEqual((build['feedback'], build.get('notes'), build.get('origin')), (None, None, None))
        self.assertEqual(sim.trace[0]['kind'], 'tester')

    def test_plan_notes_reach_the_build_and_only_the_build(self):
        sim = self.sim('plan = plan sol61:low\nbuild = luna6\nqa = qa astra6\nfix = luna6\nplan -> build -> qa\nqa -[fail]-> fix',
                       answers=['PLAN: do x'], verdicts=['FAIL'])
        sim.run()
        self.assertEqual(sim.stages(), ['plan', 'build', 'qa', 'fix'])
        self.assertEqual(sim.calls[1]['notes'], 'PLAN: do x')
        self.assertNotIn('notes', sim.calls[3])
        self.assertEqual(sim.calls[1]['feedback'], None)
        self.assertEqual(sim.calls[0]['source'], None)  # Nothing built yet at the first checkpoint.

    def test_branch_builds_from_the_start_code_and_stays_aside(self):
        text = ('tests = tester sol61:low\nbuild = luna6\nalt = branch sol61:low\ncmp = check diff alt\nfix = luna6\n'
                'tests -> build -> alt -> cmp\ncmp -[fail, max 1]-> fix -> cmp\ncmp -[pass]-> done')
        sim = self.sim(text, verdicts=['fail', 'pass'], start='base;')
        sim.run(2)
        alt = next(c for c in sim.calls if c['stage'] == 'alt')
        self.assertEqual((alt['source'], alt['feedback']), (sim.source, None))
        self.assertEqual(sim.text(), 'base;build1;fix1;')  # The branch's code never carries forward.
        side = sim.checks[0]['side']
        self.assertEqual(list(side), ['alt'])
        self.assertTrue((side['alt']/'code.txt').read_text().endswith('alt1;'))
        self.assertNotIn('alt1', sim.text())
        self.assertEqual(sim.calls[-1]['feedback'], 'check log 1')  # The fix sees the disagreement log.
        self.assertEqual(sim.calls[-1]['origin'], 'check')
        self.assertEqual(sim.checks[0]['prior'], sim.source)
        self.assertEqual(hashes(sim.shared, exclude_generated=True), hashes(sim.final))
        self.assertEqual(sim.trace[2]['kind'], 'branch')

    def test_side_codes_are_per_checkpoint(self):
        sim = self.sim('tests = tester sol61:low\nbuild = luna6\nalt = branch sol61:low\ncmp = check diff alt\ntests -> build -> alt -> cmp', verdicts=['pass'])
        sim.run()
        self.assertEqual(sim.checks[0]['side'].keys(), {'alt'})

    def test_repro_check_receives_the_review_text(self):
        sim = self.sim('build = luna6\nreview = astra6\nverify = check repro\nfix = luna6\nbuild -> review -> verify\nverify -[fail, max 1]-> fix',
                       verdicts=['FAIL', 'fail'])
        sim.run()
        self.assertTrue(sim.checks[0]['feedback'].startswith('report 2'))
        self.assertEqual(sim.calls[-1]['feedback'], 'check log 1')

    def test_existing_stages_get_no_new_arguments(self):
        sim = self.sim('build = luna6\nreview = astra6\nfix = luna6\nbuild -> review\nreview -[fail]-> fix', verdicts=['FAIL'])
        sim.run()
        for call in sim.calls:
            self.assertEqual(set(call) - {'stage', 'visit', 'source', 'feedback'}, set())


class SyncTests(unittest.TestCase):
    def tree(self, root, files):
        for name, text in files.items():
            (root/name).parent.mkdir(parents=True, exist_ok=True)
            (root/name).write_text(text)

    def test_sync_makes_tracked_files_equal_and_keeps_generated_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.tree(root/'source', {'a.py': 'A', 'pkg/b.py': 'B', 'keep/c.txt': 'C'})
            self.tree(root/'work', {'a.py': 'old', 'extra.py': 'x', 'pkg/gone.py': 'g', 'pkg/b.py': 'B', 'tmpdir/inner/f.txt': 'f',
                                    'venv/pyvenv.cfg': '', 'venv/lib/x.py': 'x', '__pycache__/a.pyc': 'p', '.pytest_cache/x': 'y'})
            sync_workspace(root/'work', root/'source')
            self.assertEqual(hashes(root/'work', exclude_generated=True), hashes(root/'source'))
            self.assertTrue((root/'work/venv/lib/x.py').exists())
            self.assertTrue((root/'work/__pycache__/a.pyc').exists())
            self.assertFalse((root/'work/tmpdir').exists())  # An emptied directory the source lacks.
            sync_workspace(root/'work', root/'source')  # Idempotent.
            self.assertEqual(hashes(root/'work', exclude_generated=True), hashes(root/'source'))

    def test_sync_handles_file_directory_swaps_and_empty_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.tree(root/'source', {'x/inner.py': 'I', 'y': 'file'})
            self.tree(root/'work', {'x': 'was a file', 'y/deep.py': 'was a dir'})
            sync_workspace(root/'work', root/'source')
            self.assertEqual(hashes(root/'work', exclude_generated=True), hashes(root/'source'))
            self.tree(root/'work', {'venv/pyvenv.cfg': ''})
            sync_workspace(root/'work', None)
            self.assertEqual(hashes(root/'work', exclude_generated=True), {})
            self.assertTrue((root/'work/venv/pyvenv.cfg').exists())
            sync_workspace(root/'fresh', None)
            self.assertTrue((root/'fresh').is_dir())

    def test_labels_never_collide(self):
        names = [factory.label(3), factory.label(3, 2), factory.label(3, 1, 1), factory.label(3, 1, 2), factory.label(3, 2, 1), factory.label(4)]
        self.assertEqual(names, ['checkpoint_3', 'checkpoint_3-2', 'checkpoint_3-attempt1', 'checkpoint_3-attempt2', 'checkpoint_3-2-attempt1', 'checkpoint_4'])
        self.assertEqual(len(set(names)), len(names))


class PromptExtensionTests(unittest.TestCase):
    SPEC = SimpleNamespace(spec=lambda name, n: f'PUBLIC SPEC {n}', manifest={'problems': {'p': {'entry_file': 'prog'}}}, b=SimpleNamespace(python='/py'))

    def test_a_build_without_notes_is_the_stock_prompt(self):
        stock = factory.stage_prompt(self.SPEC, 'build', 2, problem='p')
        self.assertEqual(factory.stage_prompt(self.SPEC, 'build', 2, None, 'p', False, None, None, None), stock)
        self.assertEqual(factory.stage_prompt(self.SPEC, 'branch', 2, problem='p'), stock)
        self.assertNotIn('Planning notes', stock)
        planned = factory.stage_prompt(self.SPEC, 'build', 2, problem='p', notes='step one')
        self.assertTrue(planned.startswith(stock))
        self.assertTrue(planned.endswith('# Planning notes for this checkpoint\nstep one'))

    def test_check_feedback_gets_its_own_heading(self):
        for role in ('build', 'fix'):
            with self.subTest(role=role):
                prompt = factory.stage_prompt(self.SPEC, role, 2, 'LOG', 'p', origin='check')
                self.assertIn('# Deterministic check results\nLOG', prompt)
                self.assertNotIn('independent reviewer', prompt)
        self.assertIn('# Feedback from the independent reviewer\nR', factory.stage_prompt(self.SPEC, 'fix', 2, 'R', 'p'))

    def test_new_roles_see_specs_up_to_the_checkpoint_only(self):
        for role in ('tester', 'plan'):
            with self.subTest(role=role):
                prompt = factory.stage_prompt(self.SPEC, role, 2, 'ignored feedback', 'p', verdict=True)
                self.assertIn('PUBLIC SPEC 2', prompt)
                self.assertNotIn('PUBLIC SPEC 3', prompt)
                self.assertNotIn('ignored feedback', prompt)
                self.assertNotIn('VERDICT', prompt)  # Only review and qa are asked for a verdict.
        self.assertIn('VERDICT: PASS', factory.stage_prompt(self.SPEC, 'review', 2, None, 'p', True, prompt='review-repro'))

    def test_prompt_attribute_replaces_the_kind_request(self):
        plain = factory.stage_prompt(self.SPEC, 'tester', 1, problem='p')
        post = factory.stage_prompt(self.SPEC, 'tester', 1, problem='p', prompt='tester-postcond')
        self.assertNotEqual(plain, post)
        self.assertIn('fuzz', post)
        self.assertEqual(factory.instructions(None, 'branch'), factory.instructions(None, 'build'))
        with self.assertRaises(ValueError):
            factory.instructions(None, 'check')
        with self.assertRaises(ValueError):
            factory.instructions(None, 'review', '../secret')

    def test_prompt_files_state_the_information_rules(self):
        for name in ('tester', 'tester-postcond'):
            text = factory.instructions(None, 'tester', name)
            self.assertIn('INTERMEDIATE NAMED', text)
            self.assertRegex(text, r'(?i)do not read or ask for any code')
            self.assertIn('cases.json', text)
        self.assertIn('json', factory.instructions(None, 'review', 'review-repro'))
        self.assertIn('do not implement', factory.instructions(None, 'plan').lower())

    def test_hashes_cover_new_prompt_files(self):
        from kojo import catalog
        self.assertEqual(set(catalog.factory_instruction_hashes(['tester', 'plan', 'review-repro'])), {'tester', 'plan', 'review-repro'})
        self.assertEqual(set(catalog.factory_instruction_hashes()), {'build', 'review', 'fix'})


class ControllerExtensionTests(unittest.TestCase):
    """main() with fake inference and fake checks: directories, receipts, grading and the manifest."""

    def run_main(self, flow_text, outcomes=(), checkpoints=2):
        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (base/'configs').mkdir()
        (base/'configs/quota.json').write_text('{}')
        shutil.copytree(REAL/'configs/factory-prompts', base/'configs/factory-prompts')
        path = base/'demo.factory'
        path.write_text(flow_text)
        flow = parse(flow_text)
        self.calls, self.prompts, self.graded, self.contexts = [], [], [], []
        script = iter(outcomes)
        backend = SimpleNamespace(protocol='fixed', runtime=base/'runtime', python='/python')

        def inference(run, instructions, prompt, seconds, *args, work_path, model, effort, **kwargs):
            name = run.parents[1].name.removeprefix('training-')
            kind = flow.stages[name].kind
            self.calls.append((name, run.name, sorted(p.name for p in work_path.iterdir())))
            run.mkdir(parents=True, exist_ok=True)
            if kind == 'tester':
                cases = work_path/'suite/cases.json'
                old = json.loads(cases.read_text()) if cases.exists() else []
                self.calls[-1] += (len(old),)
                cases.parent.mkdir(exist_ok=True)
                cases.write_text(json.dumps(old + [{'name': f'case{len(old)}'}]))
                (run/'answer.txt').write_text('added a case')
            elif kind in ('review', 'qa', 'plan'):
                (run/'answer.txt').write_text('notes\nVERDICT: PASS')
            else:
                code = work_path/'code_search'
                code.write_text((code.read_text() if code.exists() else '') + f'{name}\n')
            for filename, value in [('run.json', {'status': 'complete', 'usage': {}, 'elapsed_seconds': 1, 'api_price_equivalent_usd': 0}),
                                    ('quota.json', []), ('verification.json', {}), ('transcript-verification.json', {})]:
                (run/filename).write_text(json.dumps(value))
            (run/'stock-instructions.md').write_text('stock')

        def score(rows):
            row = rows[0]
            self.graded.append(row['run'].parents[1].name + '/' + row['run'].name)
            (row['run']/'grading').mkdir()
            (row['run']/'grading/evaluation.json').write_text('{}')
            return [{'passed': 1, 'total': 1}]

        def run_check(name, ctx):
            self.contexts.append((name, ctx))
            verdict, value = next(script)
            return checks.CheckResult(verdict, int(value * 10), 10, value, f'{name} log', {'n': len(self.contexts)})

        fake_meta = lambda name, repo=None: {'name': name, 'entry_file': 'code_search', 'checkpoints': list(range(1, checkpoints + 1))}
        fake_prompt = lambda experiment, role, n, feedback, problem, verdict, **kw: f'{role}|{n}|{feedback}|{sorted(kw.items())}'
        with contextlib.ExitStack() as stack:
            for name, value in [('BASE', base), ('DATA_ROOT', base), ('protocol_digest', lambda: 'fixed'), ('preflight', lambda **kw: ({}, {'problems': {}})),
                                ('ChainBackend', lambda *a: backend), ('Experiment', lambda *a: SimpleNamespace(score=score, spec=lambda p, n: f'SPEC {n}')),
                                ('audit_external_sources', lambda *a: {'status': 'ok'}), ('metadata', fake_meta), ('run_session', inference),
                                ('analyze_snapshot', lambda *a: []), ('stage_prompt', fake_prompt)]:
                stack.enter_context(patch.object(factory, name, value))
            stack.enter_context(patch.object(factory.claude_execution, 'run_session', inference))
            stack.enter_context(patch.object(factory.checks, 'run_check', run_check))
            with contextlib.redirect_stdout(io.StringIO()):
                factory.main(['run', '--run-id', 'flow-test', '--factory', str(path), '--no-quality'])
        return base/'results/runs/flow-test', base

    def test_tester_suite_check_and_fix_loop(self):
        text = ('tests = tester sol61:low prompt tester-postcond\nbuild = luna6:low\nfix = luna6:low\ngate = check suite\n'
                'tests -> build -> gate\ngate -[fail, max 2]-> fix -> gate\ngate -[pass]-> done\n')
        root, base = self.run_main(text, [('fail', 0.5), ('pass', 1.0), ('pass', 1.0), ('pass', 1.0), ('pass', 1.0)])  # gates, and a final smoke per checkpoint
        self.assertEqual([(c[0], c[1]) for c in self.calls],
                         [('tests', 'checkpoint_1'), ('build', 'checkpoint_1'), ('fix', 'checkpoint_1'), ('tests', 'checkpoint_2'), ('build', 'checkpoint_2')])
        self.assertEqual(self.calls[0][2], ['suite'])  # A tester sees only the suite, no builder code.
        self.assertEqual(self.calls[3][2], ['suite'])
        self.assertEqual([c[3] for c in self.calls if c[0] == 'tests'], [0, 1])  # The suite accumulates across checkpoints.
        self.assertEqual(json.loads((base/'intermediate/runs/flow-test/gauntlet/suite/cases.json').read_text()), [{'name': 'case0'}, {'name': 'case1'}])
        self.assertEqual(len(json.loads((root/'tests/checkpoint_1/suite/cases.json').read_text())), 1)
        self.assertEqual(len(json.loads((root/'tests/checkpoint_2/suite/cases.json').read_text())), 2)
        self.assertIn('fuzz', (root/'tests/checkpoint_1/instructions.md').read_text())
        self.assertEqual(self.graded, ['training-build/checkpoint_1', 'training-fix/checkpoint_1', 'training-build/checkpoint_2'])
        # Receipts of each check visit, and the context the checker was given.
        self.assertEqual(json.loads((root/'gate/checkpoint_1/result.json').read_text())['verdict'], 'fail')
        self.assertEqual((root/'gate/checkpoint_1/log.txt').read_text(), 'suite log')
        self.assertTrue((root/'gate/checkpoint_1-2/result.json').exists())
        self.assertTrue((root/'gate/checkpoint_2/result.json').exists())
        first, second = self.contexts[0][1], self.contexts[3][1]
        self.assertEqual((first.checkpoint, sorted(first.specs), first.prior_code, first.entry_file), (1, [1], None, 'code_search'))
        self.assertEqual((second.checkpoint, sorted(second.specs)), (2, [1, 2]))
        self.assertEqual(second.prior_code, base/'intermediate/runs/flow-test/gauntlet/training-fix/code_search/checkpoint_1/submission')  # The previous checkpoint's accepted code.
        self.assertEqual(first.suite_dir, base/'intermediate/runs/flow-test/gauntlet/suite')
        self.assertTrue((first.code_dir/'code_search').exists())
        self.assertEqual(self.contexts[1][1].feedback, None)
        manifest = json.loads((root/'manifest.json').read_text())
        self.assertEqual(manifest['max_sessions'], 2 * parse(text).max_sessions())
        self.assertEqual(manifest['max_checks'], 2 * 3)
        self.assertEqual(manifest['factory']['stages']['gate'], {'kind': 'check', 'model': '', 'effort': '', 'checker': 'suite'})
        self.assertEqual(manifest['factory']['stages']['tests']['prompt'], 'tester-postcond')
        self.assertEqual(sorted(manifest['role_instruction_sha256']), ['build', 'fix', 'tester-postcond'])
        self.assertEqual(sorted(manifest['models']), ['build', 'fix', 'tests'])
        self.assertNotIn('gate', manifest['effort_by_role'])
        trace = json.loads((root/'flow-trace.json').read_text())
        self.assertEqual([(t['stage'], t['verdict']) for t in trace if t['checkpoint'] == 1], [('tests', None), ('build', None), ('gate', 'fail'), ('fix', None), ('gate', 'pass')])
        self.assertEqual(trace[2]['score'], 0.5)
        self.assertFalse((root/'tests/checkpoint_1/quality.json').exists())

    def test_plan_notes_and_check_feedback_reach_the_prompts(self):
        text = 'plan = plan sol61:low\nbuild = luna6:low\nfix = luna6:low\ngate = check smoke\nplan -> build -> gate\ngate -[fail, max 1]-> fix'
        root, _ = self.run_main(text, [('fail', 0.0), ('pass', 1.0)], checkpoints=1)
        self.assertIn("('notes', 'notes\\nVERDICT: PASS')", (root/'build/checkpoint_1/prompt.md').read_text())
        self.assertIn("('origin', 'check')", (root/'fix/checkpoint_1/prompt.md').read_text())
        self.assertIn('smoke log', (root/'fix/checkpoint_1/prompt.md').read_text())
        self.assertNotIn("('notes'", (root/'fix/checkpoint_1/prompt.md').read_text())

    def test_attempts_branch_and_reset_are_labelled_graded_and_flagged(self):
        text = ('build = luna6:low x2 by smoke\nalt = branch sol61:low\ngate = check smoke\n'
                'build -> alt -> gate\ngate -[fail, max 1, reset]-> build\ngate -[pass]-> done')
        outcomes = [('pass', 0.2), ('pass', 0.8), ('fail', 0.0), ('pass', 0.5), ('pass', 0.9), ('pass', 1.0), ('pass', 1.0)]
        root, _ = self.run_main(text, outcomes, checkpoints=1)
        self.assertEqual([(c[0], c[1]) for c in self.calls][:3], [('build', 'checkpoint_1-attempt1'), ('build', 'checkpoint_1-attempt2'), ('alt', 'checkpoint_1')])
        self.assertEqual(len(set(c[:2] for c in self.calls)), len(self.calls))  # No directory collides.
        self.assertEqual(sorted(self.graded), sorted(f'training-{c[0]}/{c[1]}' for c in self.calls))  # Every code-changing session is graded.
        scores = {(r['role'], r['label']): r for r in json.loads((root/'scores.json').read_text())}
        self.assertTrue(scores[('build', 'checkpoint_1-attempt1')].get('aside'))
        self.assertFalse(scores[('build', 'checkpoint_1-attempt2')].get('aside'))
        self.assertTrue(scores[('alt', 'checkpoint_1')].get('aside'))
        trace = json.loads((root/'flow-trace.json').read_text())
        self.assertEqual(trace[0]['winner'], 2)
        self.assertTrue(trace[2]['reset'])
        self.assertTrue((root/'build/checkpoint_1-attempt1/score/result.json').exists())
        # The reroll started from nothing: its attempts' workspaces were empty.
        self.assertEqual(self.calls[3][2], [])


if __name__ == '__main__':
    unittest.main()
