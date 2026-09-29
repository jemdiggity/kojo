import importlib.util
import io
from pathlib import Path
import tokenize
import unittest
spec=importlib.util.spec_from_file_location('suite_quality',Path(__file__).resolve().parents[1]/'scripts/scb_quality_suite.py')
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
class QualitySuiteTests(unittest.TestCase):
    def test_unicode_separators_do_not_create_physical_lines(self):
        source='value = "a\u2028b\u2029c"\nprint(value)\n'
        compile(source,'fixture','exec')
        wrapped=q.PhysicalLines(source)
        self.assertEqual(str(wrapped),source)
        self.assertEqual(len(wrapped.splitlines()),2)
        tokens=list(tokenize.generate_tokens(iter(wrapped.splitlines(keepends=True)).__next__))
        self.assertTrue(any(t.string=='print' and t.start[0]==2 for t in tokens))
    def test_plain_lines_keep_normal_semantics(self):
        for s in ['', 'a', 'a\n', 'a\nb\n', 'a\n\n']:
            self.assertEqual(q.PhysicalLines(s).splitlines(),s.splitlines())
            self.assertEqual(q.PhysicalLines(s).splitlines(True),s.splitlines(True))
    def test_test_classification_is_explicit_and_conservative(self):
        for p in ['tests/helper.py','test_a.py','foo_test.py','conftest.py','smoke_test_server.py']:
            self.assertTrue(q.test_file(Path(p)))
        self.assertFalse(q.test_file(Path('src/latest.py')))
