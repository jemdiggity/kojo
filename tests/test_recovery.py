import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from kojo.execution import observe_usage
from kojo.factory import last_completed_checkpoint
from kojo.gauntlet import hashes

class RecoveryTests(unittest.TestCase):
    def test_unavailable_usage_is_optional_but_enforcement_remains_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory); meta=Mock();meta.usage.side_effect=TimeoutError('offline');samples=[]
            self.assertIsNone(observe_usage(meta,samples,run))
            self.assertEqual(samples,[])
            self.assertEqual(json.loads((run/'quota-errors.json').read_text())[0]['error_type'],'TimeoutError')
            with self.assertRaises(TimeoutError):observe_usage(meta,samples,run,required=True)
            meta.usage.side_effect=None;meta.usage.return_value={'available':True}
            self.assertEqual(observe_usage(meta,samples,run),{'available':True})

    def test_resume_stops_at_incomplete_and_rejects_modified_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cp=root/'build/checkpoint_1';(cp/'submission').mkdir(parents=True)
            (cp/'submission/main.py').write_text('complete')
            (cp/'run.json').write_text(json.dumps({'status':'complete','model':'model','reasoning':'medium'}))
            (cp/'transcript-verification.json').write_text('{}')
            (cp/'snapshot.json').write_text(json.dumps(hashes(cp/'submission')))
            failed=root/'build/checkpoint_2';failed.mkdir();(failed/'run.json').write_text('{"status":"interrupted"}')
            self.assertEqual(last_completed_checkpoint(root,'model','medium',5),1)
            (cp/'submission/main.py').write_text('partial')
            with self.assertRaisesRegex(RuntimeError,'snapshot'):last_completed_checkpoint(root,'model','medium',5)

    def test_claude_synthetic_error_does_not_hide_real_model_drift(self):
        from kojo.claude_execution import capture
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'run';run.mkdir();project=root/'config/projects/test';project.mkdir(parents=True)
            rows=[{'type':'user','message':{'content':'task'}},
                  {'attachment':{'type':'prompt_snapshot','systemPrompt':['stock']}},
                  {'type':'assistant','effort':'medium','message':{'model':'claude-opus-5'}},
                  {'type':'assistant','message':{'model':'<synthetic>','content':'API Error: 522'}}]
            source=project/'session.jsonl'
            source.write_text('\n'.join(json.dumps(r) for r in rows))
            capture(run,root/'config','session','task','claude-opus-5','medium')
            rows[2]['effort']='high';source.write_text('\n'.join(json.dumps(r) for r in rows))
            with self.assertRaisesRegex(RuntimeError,'model/effort'):capture(run,root/'config','session','task','claude-opus-5','medium')

    def test_usage_outage_does_not_prevent_completion_or_transcript_capture(self):
        import sys
        from kojo import execution, transcripts
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);meta=Mock();meta.usage.side_effect=TimeoutError('offline');meta.audit_skills.return_value={'enabled':0}
            event={'type':'turn.completed','usage':{'input_tokens':2,'output_tokens':1}}
            cmd=[sys.executable,'-c',f'import sys;sys.stdin.read();print({json.dumps(event)!r})']
            with patch.object(execution,'audit'),patch.object(execution,'command',return_value=cmd),patch.object(execution,'Metadata',return_value=meta),patch.object(transcripts,'capture',return_value={'verified':True}) as capture:
                row=execution.run_session(run,None,'task',10,monitor_only=True)
            self.assertEqual(row['status'],'complete')
            self.assertEqual(row['transcript'],{'verified':True})
            capture.assert_called_once()
            self.assertEqual(len(json.loads((run/'quota-errors.json').read_text())),2)
