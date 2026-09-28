"""Native session log checks must bind identity and actual recorded input content."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kojo.transcripts import inspect_transcript
from kojo.execution import command


class TranscriptTests(unittest.TestCase):
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

    def test_persistence_does_not_resume_or_populate_src(self):
        with tempfile.TemporaryDirectory() as d:
            cmd=command(Path(d),'instructions',isolated_src=True,persist=True)
            self.assertNotIn('--ephemeral',cmd)
            self.assertNotIn('resume',cmd)
            self.assertEqual(list((Path(d)/'src').iterdir()),[])
