"""Native session log checks must bind identity and actual recorded input content."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kojo.transcripts import inspect_transcript
from kojo.execution import command, freeze_model_catalog


class TranscriptTests(unittest.TestCase):
    def test_catalog_is_frozen_and_reused_by_audit_and_live_commands(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            catalog = {'models': [{'slug': 'gpt-6.1-sol', 'base_instructions': 'stock sol instructions'}]}
            with patch('kojo.execution.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(catalog))) as fetch:
                path = freeze_model_catalog(run, 'gpt-6.1-sol')
                audited = command(run, None, model='gpt-6.1-sol', persist=True)
                freeze_model_catalog(run, 'gpt-6.1-sol')
                live = command(run, None, model='gpt-6.1-sol', persist=True)
                fetch.assert_called_once()
            self.assertEqual(json.loads(path.read_text()), catalog)
            self.assertEqual(audited, live)
            self.assertIn('model_catalog_json=' + json.dumps(str(path.resolve())), live)
            self.assertFalse(any('model_instructions_file=' in arg for arg in live))

    def test_missing_model_metadata_fails_before_inference(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            with patch('kojo.execution.subprocess.run', return_value=SimpleNamespace(stdout='{"models": []}')):
                with self.assertRaisesRegex(RuntimeError, 'refusing fallback metadata'):
                    freeze_model_catalog(run, 'gpt-6.1-sol')
            self.assertFalse((run / 'model-catalog.json').exists())

    def fixture(self, root, base='common\nguide', prompt='task', thread='thread-id'):
        p = Path(root) / 'transcript.jsonl'
        p.write_text('\n'.join(json.dumps(r) for r in [
            {'type':'session_meta','payload':{'id':thread,'base_instructions':{'text':base}}},
            {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':prompt}]}},
        ])+'\n')
        return p

    def test_native_input_verification(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.fixture(d)
            self.assertTrue(inspect_transcript(p,'thread-id','common\nguide','task','guide')['exact_user_prompt_in_session'])

    def test_missing_guidance_wrong_prompt_or_identity_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            for fields in [{'base':'common'},{'prompt':'wrong'},{'thread':'other'}]:
                with self.subTest(fields=fields), self.assertRaises(RuntimeError):
                    inspect_transcript(self.fixture(d,**fields),'thread-id','common\nguide','task','guide')

    def test_stock_provenance_required(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.fixture(d,base='stock base')
            with self.assertRaises(RuntimeError):
                inspect_transcript(p,'thread-id',None,'task','')
            rows=[json.loads(x) for x in p.read_text().splitlines()]
            rows[0]['payload']['base_instructions']['provenance']={'type':'model','model':'gpt-6-luna'}
            p.write_text('\n'.join(map(json.dumps,rows)))
            self.assertTrue(inspect_transcript(p,'thread-id',None,'task','')['stock_base_instructions_present'])
            rows[0]['payload']['base_instructions']['provenance']={'type':'custom'}
            p.write_text('\n'.join(map(json.dumps,rows)))
            with self.assertRaises(RuntimeError):
                inspect_transcript(p,'thread-id',None,'task','')

    def test_persistence_does_not_resume_or_populate_src(self):
        with tempfile.TemporaryDirectory() as d:
            cmd=command(Path(d),'instructions',isolated_src=True,persist=True)
            self.assertNotIn('--ephemeral',cmd)
            self.assertNotIn('resume',cmd)
            self.assertEqual(list((Path(d)/'src').iterdir()),[])
