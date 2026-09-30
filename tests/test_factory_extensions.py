"""Factory language extensions: attributes, deterministic stages, new kinds and the reset arrow."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from kojo import factory_spec
from kojo.factory_spec import FactoryError, Stage, parse

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


if __name__ == '__main__':
    unittest.main()
