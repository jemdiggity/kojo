"""External-source audit fixtures: targeted contamination and ordinary source access."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kojo.external_access import audit_external_sources


class ExternalAccessTests(unittest.TestCase):
    def audit(self,command,output='',name='exec'):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'transcript.jsonl'
            rows=[{'type':'response_item','payload':{'type':'custom_tool_call','call_id':'one','name':name,'input':command}},
                  {'type':'response_item','payload':{'type':'custom_tool_call_output','call_id':'one','output':output}}]
            path.write_text('\n'.join(json.dumps(r) for r in rows))
            return audit_external_sources(path)

    def test_dependency_sources_are_inventoried(self):
        r=self.audit('python -m pip install tree-sitter','Downloading https://files.pythonhosted.org/packages/parser.whl')
        self.assertFalse(r['review_required'])
        self.assertEqual(r['events'][0]['kind'],'package_operation')
        self.assertIn('https://files.pythonhosted.org/packages/parser.whl',r['events'][0]['urls_in_output'])

    def test_benchmark_search_is_flagged_without_claiming_retrieval(self):
        r=self.audit('curl "https://www.google.com/search?q=SCBench+code_search+solutions"','curl: DNS failure')
        self.assertTrue(r['review_required'])
        self.assertEqual(r['status'],'suspected_benchmark_access')
        self.assertIn('benchmark_targeted_access_attempt',r['events'][0]['flags'])

    def test_clone_of_benchmark_is_flagged(self):
        r=self.audit('git clone https://github.com/SprocketLab/scb-problems.git','done')
        self.assertTrue(r['review_required'])

    def test_nested_web_search_is_captured(self):
        r=self.audit('text(await tools.web__run({search_query:[{q:"SCBench solutions"}]}));','result')
        self.assertTrue(r['review_required'])

    def test_unknown_target_with_benchmark_result_is_flagged(self):
        r=self.audit('curl https://example.org/resource','SlopCodeBench reference solution')
        self.assertTrue(r['review_required'])

    def test_docs_fetch_and_url_credentials_redaction(self):
        r=self.audit('curl https://user:password@docs.python.org/3/?token=private&q=ast','documentation')
        self.assertFalse(r['review_required'])
        rendered=json.dumps(r)
        self.assertNotIn('password',rendered)
        self.assertNotIn('private',rendered)
        self.assertIn('docs.python.org',rendered)

    def test_local_fixture_url_and_benchmark_prompt_are_not_fetches(self):
        r=self.audit('cat code_search', 'const url="https://example.org/SCBench/solution";')
        self.assertEqual(r['events'],[])
        self.assertFalse(r['review_required'])

    def test_missing_or_malformed_transcript_requires_review(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'missing.jsonl'
            self.assertTrue(audit_external_sources(path)['review_required'])
            path.write_text('{broken')
            self.assertTrue(audit_external_sources(path)['review_required'])

    def test_native_web_search_record(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'native.jsonl'
            path.write_text(json.dumps({'type':'response_item','payload':{'type':'web_search_call','id':'search','action':{'type':'search','query':'slop-code-bench code_search solution'}}}))
            self.assertTrue(audit_external_sources(path)['review_required'])
