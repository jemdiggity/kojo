"""Deterministic checks, against tiny fake programs written into temp dirs."""
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from kojo import checks, factory_spec
from kojo.checks import Context, run_check

REAL = Path(__file__).resolve().parents[1]
CIRCUIT = REAL/'intermediate/vendor/scb-problems/circuit_eval'

PROGRAM = '''#!/usr/bin/env python3
import json, os, sys, time
args = sys.argv[1:]
if args == ['--help']:
    print('usage: prog COMMAND'); sys.exit(0)
if args == ['--version']:
    print('1.0'); sys.exit(0)
cmd = args[0] if args else ''
if cmd == 'say':
    print(' '.join(args[1:]))
elif cmd == 'add':
    print(sum(int(a) for a in args[1:]))
elif cmd == 'fail':
    print('boom', file=sys.stderr); sys.exit(3)
elif cmd == 'upper':
    sys.stdout.write(sys.stdin.read().upper())
elif cmd == 'write':
    open(args[1], 'w').write('hello world\\n')
elif cmd == 'hang':
    time.sleep(60)
elif cmd == 'flood':
    sys.stdout.write('x' * 500000)
elif cmd == 'env':
    print(json.dumps(sorted(os.environ)))
elif cmd == 'json':
    print(json.dumps({'ok': True, 'n': 2, 'items': [1, 2]}, indent=2))
elif cmd == 'eval':
    text = open(args[1]).read()
    print('cout=1\\nsum=0' if 'XOR' in text else 'no circuit')
elif cmd == 'check':
    sig = lambda *names: [{'name': n, 'msb': 0, 'lsb': 0} for n in names]
    print(json.dumps({'ok': True, 'command': 'check', 'format': 'circ', 'inputs': sig('a', 'b', 'cin'), 'outputs': sig('cout', 'sum')}, indent=1))
else:
    print('unknown command', file=sys.stderr); sys.exit(1)
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def code(self, text=PROGRAM, name='code', extra=None, entry='prog'):
        directory = self.tmp/name
        directory.mkdir(parents=True, exist_ok=True)
        (directory/entry).write_text(text)
        for filename, body in (extra or {}).items():
            (directory/filename).write_text(body)
        return directory

    def ctx(self, code=None, entry='prog', **kwargs):
        kwargs.setdefault('timeout', 5)
        return Context(code_dir=code or self.code(), entry_file=entry, python=Path(sys.executable), **kwargs)

    def suite(self, cases, files=None):
        directory = self.tmp/'suite'
        directory.mkdir(exist_ok=True)
        (directory/'cases.json').write_text(cases if isinstance(cases, str) else json.dumps(cases))
        for name, body in (files or {}).items():
            (directory/name).parent.mkdir(parents=True, exist_ok=True)
            (directory/name).write_text(body)
        return directory


def case(name, argv, **expect):
    return {'name': name, 'argv': argv, 'expect': expect, 'source': 'postcondition'}


class RegistryTests(unittest.TestCase):
    def test_registry_matches_the_language(self):
        self.assertEqual(checks.CHECKERS, factory_spec.CHECKERS)
        self.assertTrue(set(factory_spec.SCORING) <= set(checks.CHECKERS))

    def test_unknown_check(self):
        with self.assertRaises(ValueError):
            run_check('nope', Context(Path('.'), 'x', Path(sys.executable)))

    def test_checker_bugs_never_fail_the_code(self):
        with patch.dict(checks.CHECKS, {'smoke': lambda ctx: 1 / 0}):
            got = run_check('smoke', Context(Path('.'), 'x', Path(sys.executable)))
        self.assertEqual((got.verdict, got.total, got.score), ('pass', 0, 1.0))
        self.assertIn('could not run', got.log)


class SafeTests(Base):
    CASES = [case('say', ['say', 'hi'], stdout='hi'), case('add', ['add', '1', '1'], stdout='2')]

    def test_a_working_program_passing_the_suite_passes(self):
        got = run_check('safe', self.ctx(suite_dir=self.suite(self.CASES)))
        self.assertEqual((got.verdict, got.passed, got.total, got.score), ('pass', 2, 2, 1.0))
        self.assertEqual((got.details['smoke_ok'], got.details['failing']), (True, []))

    def test_a_broken_program_fails_with_score_zero_and_only_the_smoke_log(self):
        broken = self.code('if True:\nprint(1)\n', name='broken')
        got = run_check('safe', self.ctx(broken, suite_dir=self.suite(self.CASES)))
        self.assertEqual((got.verdict, got.score, got.details['smoke_ok']), ('fail', 0.0, False))
        self.assertIn('do not compile', got.log)

    def test_failing_cases_are_named_sorted(self):
        cases = self.CASES + [case('bad', ['add', '1'], stdout='9'), case('bad2', ['say', 'x'], stdout='y')]
        got = run_check('safe', self.ctx(suite_dir=self.suite(cases)))
        self.assertEqual((got.verdict, got.details['failing']), ('fail', ['bad', 'bad2']))
        self.assertEqual(checks.failure_signature(got), ('cases', ('bad', 'bad2'), True))

    def test_guard_rule(self):
        def found(smoke_ok=True, failing=(), score=1.0):
            return checks.CheckResult('pass', 0, 0, score, '', {'smoke_ok': smoke_ok, 'failing': list(failing)})
        self.assertFalse(checks.guard_rolls_back('safe', None, found()))
        self.assertTrue(checks.guard_rolls_back('safe', found(), found(smoke_ok=False)))
        self.assertTrue(checks.guard_rolls_back('safe', found(failing='a', score=.5), found(failing='ab', score=.9)))  # New failure, higher score.
        self.assertFalse(checks.guard_rolls_back('safe', found(failing='ab'), found(failing='a')))
        self.assertFalse(checks.guard_rolls_back('safe', found(smoke_ok=False, score=0.0), found(failing='ab', score=.4)))  # Now it starts.
        self.assertFalse(checks.guard_rolls_back('safe', found(failing='ab'), found(failing='bc')))  # One repaired, one broken.
        self.assertTrue(checks.guard_rolls_back('safe', found(failing='a', score=.9), found(failing='b', score=.8)))  # Score fell.
        self.assertTrue(checks.guard_rolls_back('suite', found(score=.9), found(score=.8)))
        self.assertFalse(checks.guard_rolls_back('suite', found(score=.8), found(score=.8)))


class ChangedTests(Base):
    def test_unchanged_code_fails_and_edited_code_passes(self):
        start = self.code(name='start')
        same = self.code(name='same')
        edited = self.code(PROGRAM + '\n# edited\n', name='edited')
        added = self.code(name='added', extra={'helper.py': 'x = 1\n'})
        self.assertEqual(run_check('changed', self.ctx(same, prior_code=start)).verdict, 'fail')
        for code in (edited, added):
            got = run_check('changed', self.ctx(code, prior_code=start))
            self.assertEqual((got.verdict, got.passed, got.total, got.details['changed']), ('pass', 1, 1, True))

    def test_caches_and_environments_do_not_count_as_a_change(self):
        start = self.code(name='start')
        noisy = self.code(name='noisy', extra={'prog.pyc': 'x'})
        (noisy/'__pycache__').mkdir()
        (noisy/'__pycache__/prog.cpython-312.pyc').write_bytes(b'0')
        (noisy/'.venv').mkdir()
        (noisy/'.venv/pyvenv.cfg').write_text('home')
        self.assertEqual(run_check('changed', self.ctx(noisy, prior_code=start)).verdict, 'fail')

    def test_the_first_checkpoint_needs_some_program_files(self):
        empty = self.tmp/'empty'
        empty.mkdir()
        self.assertEqual(run_check('changed', self.ctx(empty)).verdict, 'fail')
        self.assertEqual(run_check('changed', self.ctx(self.code(name='built'))).verdict, 'pass')


class SuiteCopyTests(Base):
    def make(self, name, files):
        directory = self.tmp/name
        for relative, body in files.items():
            (directory/relative).parent.mkdir(parents=True, exist_ok=True)
            (directory/relative).write_text(body)
        return directory

    def test_an_oversized_suite_leaves_the_previous_one_untouched(self):
        previous = self.make('previous', {'cases.json': '[1]', 'a.py': 'x'})
        big = self.make('big', {'cases.json': '[2]', 'data.json': '0' * 100})
        with patch.object(checks, 'SUITE_BYTES', 50), self.assertRaises(checks.SuiteTooLarge):
            checks.copy_suite(big, previous)
        self.assertEqual(sorted(p.name for p in previous.iterdir()), ['a.py', 'cases.json'])
        self.assertEqual((previous/'cases.json').read_text(), '[1]')
        self.assertFalse((self.tmp/'.previous.staging').exists())

    def test_too_many_files_is_rejected_whole_not_truncated(self):
        many = self.make('many', {f'f{i}.txt': 'x' for i in range(5)})
        target = self.tmp/'target'
        with patch.object(checks, 'SUITE_FILES', 3), self.assertRaises(checks.SuiteTooLarge):
            checks.copy_suite(many, target)
        self.assertFalse(target.exists())

    def test_a_fitting_suite_replaces_the_old_one_completely(self):
        target = self.make('target', {'old.txt': 'old'})
        checks.copy_suite(self.make('new', {'cases.json': '[]'}), target)
        self.assertEqual([p.name for p in target.iterdir()], ['cases.json'])

    def test_a_missing_data_file_inside_the_suite_is_a_script_bug(self):
        suite = self.tmp/'suite'
        cases = [{'name': 'reads', 'script': 'checks/reads.py'}, {'name': 'other', 'script': 'checks/other.py'}]
        files = {'checks/reads.py': 'import os\nopen(os.environ["SUITE_DIR"] + "/data.json")\n',
                 'checks/other.py': 'open("/definitely/not/there.txt")\n'}
        got = run_check('suite', self.ctx(suite_dir=self.suite(cases, files)))
        self.assertEqual([e['name'] for e in got.details['invalid']], ['reads'])
        self.assertEqual(got.details['failures'], ['other'])  # A path outside the suite stays the program's problem.

    def test_an_empty_or_unreadable_suite_is_flagged(self):
        self.assertTrue(run_check('suite', self.ctx(suite_dir=self.suite('{not json'))).details['suite_missing'])
        self.assertTrue(run_check('safe', self.ctx(suite_dir=self.suite([]))).details['suite_missing'])
        self.assertFalse(run_check('suite', self.ctx()).details.get('suite_missing'))  # No suite wanted at all.


class SmokeTests(Base):
    def test_a_working_program_passes(self):
        got = run_check('smoke', self.ctx())
        self.assertEqual((got.verdict, got.passed, got.total, got.score), ('pass', 2, 2, 1.0))
        self.assertIn('no model involved', got.log)
        json.dumps(got.details)

    def test_version_is_checked_when_a_spec_mentions_it(self):
        got = run_check('smoke', self.ctx(specs={1: 'The `--version` flag prints a version.'}))
        self.assertEqual(got.total, 3)

    def test_syntax_error_in_a_module_is_caught_even_when_help_works(self):
        got = run_check('smoke', self.ctx(self.code(extra={'helper.py': 'def broken(:\n    pass\n'})))
        self.assertEqual(got.verdict, 'fail')
        self.assertIn('helper.py line 1', got.log)
        self.assertIn('SyntaxError', got.log)

    def test_indentation_error_in_the_entry_file(self):
        got = run_check('smoke', self.ctx(self.code('#!/usr/bin/env python3\nimport sys\nif True:\nprint(1)\n')))
        self.assertEqual(got.verdict, 'fail')
        self.assertIn('IndentationError', got.log)
        self.assertEqual(got.passed, 0)

    def test_crash_on_help(self):
        got = run_check('smoke', self.ctx(self.code('#!/usr/bin/env python3\nimport nonexistent_module_xyz\n')))
        self.assertEqual(got.verdict, 'fail')
        self.assertIn('Traceback', got.log)

    def test_traceback_with_exit_zero_and_nonzero_exit_both_fail(self):
        for body in ('#!/usr/bin/env python3\nimport sys\nsys.exit(2)\n',
                     '#!/usr/bin/env python3\nprint("Traceback (most recent call last):")\n'):
            with self.subTest(body=body):
                self.assertEqual(run_check('smoke', self.ctx(self.code(body))).verdict, 'fail')

    def test_help_timeout(self):
        got = run_check('smoke', self.ctx(self.code('#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n'), timeout=1))
        self.assertEqual(got.verdict, 'fail')
        self.assertIn('timed out', got.log)

    def test_missing_entry_file(self):
        directory = self.tmp/'empty'
        directory.mkdir()
        got = run_check('smoke', Context(directory, 'prog', Path(sys.executable)))
        self.assertEqual((got.verdict, got.total), ('fail', 1))

    def test_venv_and_cache_directories_are_not_compiled(self):
        code = self.code()
        (code/'venv/lib').mkdir(parents=True)
        (code/'venv/pyvenv.cfg').write_text('')
        (code/'venv/lib/bad.py').write_text('def (:\n')
        self.assertEqual(run_check('smoke', self.ctx(code)).verdict, 'pass')

    def test_running_does_not_touch_the_code_directory(self):
        code = self.code(extra={'helper.py': 'X = 1\n'})
        before = sorted(p.name for p in code.rglob('*'))
        run_check('smoke', self.ctx(code))
        self.assertEqual(sorted(p.name for p in code.rglob('*')), before)


class ExecutionTests(Base):
    def test_environment_is_scrubbed(self):
        with patch.dict(os.environ, {'SECRET_API_TOKEN': 'sk-123', 'OPENAI_API_KEY': 'x'}):
            run = checks.execute(self.ctx(), self.ctx().code_dir, ['env'])
        names = json.loads(run.stdout)
        self.assertFalse({'SECRET_API_TOKEN', 'OPENAI_API_KEY'} & set(names))
        self.assertIn('HOME', names)

    def test_output_is_truncated_and_timeouts_reported(self):
        ctx = self.ctx(timeout=1)
        run = checks.execute(ctx, ctx.code_dir, ['flood'])
        self.assertLess(len(run.stdout), checks.OUTPUT_LIMIT + 100)
        self.assertIn('truncated', run.stdout)
        hung = checks.execute(ctx, ctx.code_dir, ['hang'])
        self.assertTrue(hung.timed_out)
        self.assertIsNone(hung.exit)

    def test_runs_in_a_fresh_temp_dir_with_the_given_files(self):
        ctx = self.ctx()
        run = checks.execute(ctx, ctx.code_dir, ['write', 'out.txt'], files={'in/data.txt': 'x'}, read=['out.txt', 'nope.txt'])
        self.assertEqual(run.files, {'out.txt': 'hello world\n', 'nope.txt': None})
        self.assertIn('unsafe', checks.execute(ctx, ctx.code_dir, ['say'], files={'../evil': 'x'}).error)
        self.assertEqual(checks.execute(ctx, ctx.code_dir, ['upper'], stdin='abc').stdout, 'ABC')

    def test_extensionless_and_missing_interpreters_do_not_crash(self):
        run = checks.execute(self.ctx(self.code('not python at all (\n')), self.tmp/'code', ['x'])
        self.assertEqual(run.exit, 1)  # The interpreter's own SyntaxError.


class ExampleTests(Base):
    def rendered(self, upto):
        return {n: (CIRCUIT/f'checkpoint_{n}.md').read_text().replace('%%%ENTRYPOINT:entry_command%%%', f'{sys.executable} circopt')
                for n in range(1, upto + 1)}

    @unittest.skipUnless(CIRCUIT.is_dir(), 'vendor specs not set up')
    def test_extraction_on_the_real_circuit_eval_specs(self):
        cases, skipped = checks.extract_examples(self.rendered(3), 'circopt')
        names = [c['argv'] for c in cases]
        self.assertIn(['eval', 'adder.circ', '--set', 'a=1', '--set', 'b=0', '--set', 'cin=1'], names)
        adder = next(c for c in cases if c['argv'][:2] == ['eval', 'adder.circ'])
        self.assertIn('XOR(a, b)', adder['files']['adder.circ'])  # A fixture from checkpoint 1's spec.
        self.assertEqual(adder['expect'], {'exit': None, 'stdout': 'cout=1\nsum=0\n', 'stdout_regex': None, 'stdout_contains': [], 'stdout_json': None, 'files': {}})
        error = next(c for c in cases if c['argv'][:2] == ['eval', 'mux4.circ'] and '--set' in c['argv'] and 'a=0b1' in c['argv'])
        self.assertEqual((error['expect']['exit'], error['expect']['stdout']), (3, None))
        self.assertTrue(any('illustrative' in s['reason'] for s in skipped))  # The parse error with "..." message.
        self.assertEqual(len(cases), 6)

    @unittest.skipUnless(CIRCUIT.is_dir(), 'vendor specs not set up')
    def test_extraction_counts_per_checkpoint_and_never_uses_future_specs(self):
        for upto, expected in [(1, 1), (2, 2), (4, 13), (8, 23)]:
            with self.subTest(upto=upto):
                cases, _ = checks.extract_examples(self.rendered(upto), 'circopt')
                self.assertEqual(len(cases), expected)
        early, _ = checks.extract_examples(self.rendered(2), 'circopt')
        self.assertFalse(any(c['argv'][0] in ('lint', 'stats', 'opt') for c in early))
        raw = {n: (CIRCUIT/f'checkpoint_{n}.md').read_text() for n in (1, 2)}  # The unrendered placeholder works too.
        self.assertEqual(len(checks.extract_examples(raw, 'circopt')[0]), 2)

    def test_synthetic_specs(self):
        spec = textwrap.dedent('''
            # Part 1
            `a.txt`
            ```text
            hello
            ```

            ```bash
            $ prog say hi there
            hi there
            # exit 0
            $ prog cat a.txt
            hello
            $ prog cat missing.txt
            data
            $ prog say <name>
            x
            $ prog say hi | tr a b
            hi
            $ prog say "a b" 'c d'
            a b c d
            $ prog fail
            # exit 3
            $ prog noinfo
            $ other-tool say hi
            hi
            $ prog say ...
            hi
            ```
            ''')
        cases, skipped = checks.extract_examples({1: spec}, 'prog')
        self.assertEqual([c['argv'] for c in cases], [['say', 'hi', 'there'], ['cat', 'a.txt'], ['say', 'a b', 'c d'], ['fail']])
        self.assertEqual(cases[1]['files'], {'a.txt': 'hello\n'})
        reasons = ' | '.join(s['reason'] for s in skipped)
        for word in ('not defined', 'placeholder', 'shell syntax', 'no expected', 'not a command'):
            self.assertIn(word, reasons)

    def test_later_specs_replace_and_redefine(self):
        one = '`f.txt`\n```text\nold\n```\n```bash\n$ prog cat f.txt\nold\n$ prog say a\nfirst\n```\n'
        two = '`f.txt`\n```text\nnew\n```\n```bash\n$ prog say a\nsecond\n```\n'
        cases, skipped = checks.extract_examples({1: one, 2: two}, 'prog')
        self.assertEqual([(c['argv'], c['expect']['stdout']) for c in cases], [(['say', 'a'], 'second\n')])
        reasons = ' | '.join(s['reason'] for s in skipped)
        self.assertIn('redefined by a later checkpoint', reasons)
        self.assertIn('superseded', reasons)

    def test_a_problem_without_examples_passes_with_total_zero(self):
        got = run_check('examples', self.ctx(specs={1: '# A spec with no examples\n\nJust prose and `inline` code.\n'}))
        self.assertEqual((got.verdict, got.total, got.score), ('pass', 0, 1.0))
        self.assertIn('No runnable examples', got.log)
        self.assertEqual(run_check('examples', self.ctx()).total, 0)

    @unittest.skipUnless(CIRCUIT.is_dir(), 'vendor specs not set up')
    def test_running_examples_passes_and_reports_mismatches(self):
        specs = self.rendered(2)
        ok = run_check('examples', self.ctx(self.code(entry='circopt'), entry='circopt', specs=specs))
        self.assertEqual((ok.verdict, ok.passed, ok.total), ('pass', 2, 2))  # `check` prints indented JSON: equal JSON counts as equal.
        broken = self.code(PROGRAM.replace("cout=1\\nsum=0", "cout=0\\nsum=0"), name='broken', entry='circopt')
        bad = run_check('examples', self.ctx(broken, entry='circopt', specs=specs))
        self.assertEqual((bad.verdict, bad.passed, bad.total), ('fail', 1, 2))
        self.assertIn('spec example mismatch (checkpoint 2)', bad.log)
        self.assertIn('-cout=1', bad.log)
        self.assertIn('+cout=0', bad.log)

    def test_exit_code_only_examples(self):
        spec = '```bash\n$ prog fail\n# exit 3\n$ prog say x\n# exit 4\n```\n'
        got = run_check('examples', self.ctx(specs={1: spec}))
        self.assertEqual((got.passed, got.total), (1, 2))
        self.assertIn('exit code 0, expected 4', got.log)


class SuiteTests(Base):
    def test_pass_fail_and_score(self):
        directory = self.suite([case('say', ['say', 'hi'], exit=0, stdout='hi\n'), case('add', ['add', '2', '3'], stdout='6'),
                                case('fails', ['fail'], exit=3)])
        got = run_check('suite', self.ctx(suite_dir=directory))
        self.assertEqual((got.verdict, got.passed, got.total), ('fail', 2, 3))
        self.assertAlmostEqual(got.score, 2 / 3)
        self.assertIn('FAILURES', got.log)
        self.assertIn('add 2 3', got.log)
        self.assertNotIn('REGRESSIONS', got.log)
        self.assertEqual(got.details['failures'], ['add'])

    def test_all_pass(self):
        got = run_check('suite', self.ctx(suite_dir=self.suite([case('say', ['say', 'hi'], stdout='hi')])))
        self.assertEqual((got.verdict, got.score), ('pass', 1.0))

    def test_regressions_come_first(self):
        prior = self.code(name='prior')
        now = self.code(PROGRAM.replace("print(' '.join(args[1:]))", "print('nope')").replace('print(sum(int(a) for a in args[1:]))', 'print(-1)'), name='now')
        cases = [case('say', ['say', 'hi'], stdout='hi'), case('add', ['add', '1', '1'], stdout='2'), case('new', ['add', '5'], stdout='7')]
        directory = self.suite(cases)
        got = run_check('suite', self.ctx(now, prior_code=prior, suite_dir=directory))
        self.assertEqual(got.details['regressions'], ['say', 'add'])
        self.assertEqual(got.details['failures'], ['new'])  # Failed on the prior code too: an ordinary failure.
        self.assertLess(got.log.index('REGRESSIONS'), got.log.index('FAILURES'))
        self.assertTrue(got.details['prior_ran'])
        self.assertEqual(got.passed, 0)

    def test_invalid_cases_are_not_builder_failures(self):
        cases = [case('good', ['say', 'a'], stdout='a'), {'name': 'no-argv', 'expect': {'exit': 0}}, {'name': 'empty', 'argv': ['say']},
                 {'name': 'bad-regex', 'argv': ['say'], 'expect': {'stdout_regex': '('}}, 'junk',
                 {'name': 'evil-file', 'argv': ['say'], 'files': {'/etc/x': 'y'}, 'expect': {'exit': 0}},
                 {'name': 'no-script', 'script': 'checks/missing.py'}]
        got = run_check('suite', self.ctx(suite_dir=self.suite(cases)))
        self.assertEqual((got.verdict, got.passed, got.total), ('pass', 1, 1))
        self.assertEqual(len(got.details['invalid']), 6)
        self.assertIn('INVALID SUITE CASES', got.log)
        self.assertIn('no-argv', got.log)

    def test_malformed_suite_files(self):
        for text in ('{not json', '{"a": 1}', '"x"'):
            with self.subTest(text=text):
                got = run_check('suite', self.ctx(suite_dir=self.suite(text)))
                self.assertEqual((got.verdict, got.total), ('pass', 0))
                self.assertTrue(got.details['errors'])
        self.assertEqual(run_check('suite', self.ctx()).total, 0)
        self.assertEqual(run_check('suite', self.ctx(suite_dir=self.tmp/'absent')).verdict, 'pass')

    def test_object_form_and_every_expectation_kind(self):
        cases = {'cases': [
            {'name': 'json', 'argv': ['json'], 'expect': {'stdout_json': {'ok': True, 'items': [1, 2]}}},
            {'name': 'json-mismatch', 'argv': ['json'], 'expect': {'stdout_json': {'ok': 1}}},
            {'name': 'regex', 'argv': ['say', 'abc123'], 'expect': {'stdout_regex': r'c\d+$'}},
            {'name': 'contains', 'argv': ['say', 'one two'], 'expect': {'stdout_contains': ['one', 'two']}},
            {'name': 'stdin', 'argv': ['upper'], 'stdin': 'shout', 'expect': {'stdout': 'SHOUT'}},
            {'name': 'file', 'argv': ['write', 'o.txt'], 'expect': {'files': {'o.txt': {'regex': '^hello', 'not_regex': 'bye', 'equals': 'hello world'}}}},
            {'name': 'file-missing', 'argv': ['say'], 'expect': {'files': {'o.txt': {'regex': 'x'}}}},
            {'name': 'infile', 'argv': ['eval', 'c.circ'], 'files': {'c.circ': 'y = XOR(a,b)'}, 'expect': {'stdout': 'cout=1\nsum=0'}},
        ]}
        got = run_check('suite', self.ctx(suite_dir=self.suite(cases)))
        self.assertEqual(sorted(got.details['failures']), ['file-missing', 'json-mismatch'])
        self.assertEqual(got.total, 8)

    def test_script_cases(self):
        cases = [{'name': 'absorb', 'script': 'checks/absorb.py', 'args': ['x']},
                 {'name': 'bad-logic', 'script': 'checks/bad.py'},
                 {'name': 'bad-syntax', 'script': 'checks/syntax.py'}]
        files = {'checks/absorb.py': 'import os, json, subprocess, sys\nargv = json.loads(os.environ["ENTRY_ARGV_JSON"])\n'
                                     'out = subprocess.run(argv + ["say", sys.argv[1]], capture_output=True, text=True).stdout\n'
                                     'assert out.strip() == "x", out\n',
                 'checks/bad.py': 'import sys\nprint("checking", file=sys.stderr)\nassert 1 == 2, "wrong answer"\n',
                 'checks/syntax.py': 'def (:\n'}
        got = run_check('suite', self.ctx(suite_dir=self.suite(cases, files)))
        self.assertEqual((got.passed, got.total), (1, 2))
        self.assertEqual(got.details['failures'], ['bad-logic'])
        self.assertEqual(len(got.details['invalid']), 1)
        self.assertIn('wrong answer', got.log)

    def test_script_bugs_are_tester_errors_but_raised_failures_count(self):
        cases = [{'name': 'ok', 'script': 'checks/ok.py'}, {'name': 'undefined', 'script': 'checks/undefined.py'},
                 {'name': 'raises', 'script': 'checks/raises.py'}, {'name': 'parse', 'script': 'checks/parse.py'}]
        files = {'checks/ok.py': 'pass\n', 'checks/undefined.py': 'print(nope_not_defined)\n',
                 'checks/raises.py': 'raise RuntimeError("the program is wrong")\n',
                 'checks/parse.py': 'import json\njson.loads("not json")\n'}
        got = run_check('suite', self.ctx(suite_dir=self.suite(cases, files)))
        self.assertEqual((got.passed, got.total), (1, 3))  # The NameError script is dropped from the count.
        self.assertEqual(sorted(got.details['failures']), ['parse', 'raises'])
        self.assertEqual([e['name'] for e in got.details['invalid']], ['undefined'])
        self.assertIn('script crashed (NameError', got.log)

    def test_script_path_cannot_escape_the_suite(self):
        (self.tmp/'outside.py').write_text('print(1)\n')
        got = run_check('suite', self.ctx(suite_dir=self.suite([{'name': 'esc', 'script': '../outside.py'}])))
        self.assertEqual(got.total, 0)
        self.assertEqual(len(got.details['invalid']), 1)

    def test_hanging_case_times_out_quickly(self):
        directory = self.suite([case('hang', ['hang'], exit=0), case('ok', ['say', 'a'], stdout='a')])
        got = run_check('suite', self.ctx(suite_dir=directory, timeout=1))
        self.assertEqual(got.details['failures'], ['hang'])
        self.assertIn('timed out', got.log)

    def test_log_is_capped_and_states_its_source(self):
        cases = [case(f'c{i}', ['say', 'y' * 300], stdout='z' * 300) for i in range(40)]
        got = run_check('suite', self.ctx(suite_dir=self.suite(cases)))
        self.assertLessEqual(len(got.log), checks.LOG_LIMIT + 60)
        self.assertIn('run by the harness', got.log)

    def test_copy_suite_skips_links_caches_and_pyc(self):
        source = self.tmp/'src-suite'
        (source/'checks/__pycache__').mkdir(parents=True)
        (source/'cases.json').write_text('[]')
        (source/'checks/a.py').write_text('x')
        (source/'checks/__pycache__/a.pyc').write_text('x')
        (source/'link').symlink_to(source/'cases.json')
        target = self.tmp/'dst'
        self.assertEqual(checks.copy_suite(source, target), 2)
        self.assertEqual(sorted(str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()), ['cases.json', 'checks/a.py'])
        self.assertEqual(checks.copy_suite(self.tmp/'nothing', self.tmp/'dst2'), 0)


class ReproTests(Base):
    def review(self, *cases, extra=''):
        return 'Findings.\n\n```json\n' + json.dumps(list(cases)) + '\n```\n' + extra

    def test_confirmed_and_unconfirmed(self):
        feedback = self.review(case('wrong', ['add', '2', '2'], stdout='5'), case('right', ['say', 'a'], stdout='a'),
                               case('exit', ['fail'], exit=0)) + '\nSuspicion (not verified): the parser may be slow.'
        got = run_check('repro', self.ctx(feedback=feedback))
        self.assertEqual((got.verdict, got.passed, got.total), ('fail', 1, 3))
        self.assertEqual(got.details['confirmed'], ['wrong', 'exit'])
        self.assertIn('add 2 2', got.log)
        self.assertNotIn('right', got.log.replace('the right', ''))
        self.assertNotIn('parser may be slow', got.log)

    def test_all_unconfirmed_passes(self):
        got = run_check('repro', self.ctx(feedback=self.review(case('right', ['say', 'a'], stdout='a'))))
        self.assertEqual((got.verdict, got.total, got.passed), ('pass', 1, 1))

    def test_no_parseable_repros_passes_with_total_zero(self):
        for feedback in (None, '', 'No repros.', '```json\n{oops\n```', '```json\n{"cases": "no"}\n```'):
            with self.subTest(feedback=feedback):
                got = run_check('repro', self.ctx(feedback=feedback))
                self.assertEqual((got.verdict, got.total), ('pass', 0))

    def test_object_form_multiple_blocks_and_invalid_claims(self):
        text = ('```json\n{"cases": [{"name": "a", "argv": ["add", "1"], "expect": {"stdout": "9"}}]}\n```\n'
                '```json\n[{"name": "junk"}, {"name": "script", "script": "x.py"}]\n```')
        got = run_check('repro', self.ctx(feedback=text))
        self.assertEqual((got.verdict, got.total, got.details['unparseable']), ('fail', 1, 2))


class DiffTests(Base):
    FUZZ = ('import os, shlex, subprocess, sys\n'
            'def run(var, *args):\n'
            '    return subprocess.run(shlex.split(os.environ[var]) + list(args), capture_output=True, text=True).stdout\n'
            'for n in ("1", "2", "3"):\n'
            '    a, b = run("ENTRY_A", "add", n, n), run("ENTRY_B", "add", n, n)\n'
            '    if a != b:\n'
            '        print(f"add {n} {n}: A={a!r} B={b!r}"); sys.exit(1)\n')

    def ctx_diff(self, side_text=None, fuzz=FUZZ):
        side = self.code(side_text or PROGRAM, name='alt')
        directory = self.tmp/'suite'
        (directory/'fuzz').mkdir(parents=True, exist_ok=True)
        (directory/'fuzz/add.py').write_text(fuzz)
        return self.ctx(suite_dir=directory, side_codes={'alt': side}, arg='alt')

    def test_agreement(self):
        got = run_check('diff', self.ctx_diff())
        self.assertEqual((got.verdict, got.passed, got.total), ('pass', 1, 1))

    def test_disagreement_is_logged(self):
        got = run_check('diff', self.ctx_diff(PROGRAM.replace('print(sum(int(a) for a in args[1:]))', 'print(sum(int(a) for a in args[1:]) + 1)')))
        self.assertEqual((got.verdict, got.passed, got.total), ('fail', 0, 1))
        self.assertIn('DISAGREE', got.log)
        self.assertIn("A='2\\n' B='3\\n'", got.log)

    def test_nothing_to_compare(self):
        self.assertEqual(run_check('diff', self.ctx(arg='alt')).total, 0)
        ctx = self.ctx_diff()
        (ctx.suite_dir/'fuzz/add.py').unlink()
        got = run_check('diff', ctx)
        self.assertEqual((got.verdict, got.total), ('pass', 0))
        ctx = self.ctx_diff()
        ctx.side_codes.clear()
        self.assertEqual(run_check('diff', ctx).verdict, 'pass')

    def test_broken_fuzz_scripts_are_invalid_not_disagreements(self):
        got = run_check('diff', self.ctx_diff(fuzz='def (:\n'))
        self.assertEqual((got.verdict, got.total, len(got.details['invalid'])), ('pass', 0, 1))


if __name__ == '__main__':
    unittest.main()
