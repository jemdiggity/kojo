"""Claude request and accounting checks without paid calls."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kojo import claude_execution as claude, factory
from kojo.external_access import audit_external_sources


class ClaudeTests(unittest.TestCase):
    def request(self):
        return {'model':claude.MODELS[0], 'system':[{'text':'stock prompt'}],
                'messages':[{'role':'user','content':'exact task'}],
                'output_config':{'effort':'high'},'thinking':{'type':'adaptive'},
                'tools':[{'name':t} for t in ['Bash','Read','Write','Edit','Glob','Grep']]}

    def test_request_rejects_drift_and_prompt_substrings(self):
        request=self.request()
        receipt,_=claude.verify_request(request,'exact task',claude.MODELS[0],'high')
        self.assertEqual(receipt['thinking'],{'type':'adaptive'})
        for key,value in [('model','another-model'),('output_config',{'effort':'low'}),
                          ('messages',[{'role':'user','content':'prefix exact task suffix'}]),
                          ('tools',[{'name':'Skill'}])]:
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                claude.verify_request({**request,key:value},'exact task',claude.MODELS[0],'high')

    def test_command_preserves_stock_and_fresh_conversation(self):
        with tempfile.TemporaryDirectory() as d, patch.object(claude.subprocess,'run'):
            root=Path(d)
            cmd=claude.command(root,root/'src',claude.MODELS[0],'high','unique-session')
            self.assertIn('--safe-mode',cmd)
            self.assertIn('--restricted',cmd)
            for forbidden in ['--bare','--system-prompt','--append-system-prompt','--resume','--continue']:
                self.assertNotIn(forbidden,cmd)
            self.assertIn('unique-session',cmd)

    def test_cancel_terminates_detached_model_process(self):
        process=Mock(pid=12345,returncode=-9)
        process.communicate.side_effect=KeyboardInterrupt
        process.poll.return_value=None
        with tempfile.TemporaryDirectory() as d, \
             patch.object(claude,'audit'), \
             patch.object(claude,'command',return_value=['claude']), \
             patch.object(claude,'capture',return_value={}), \
             patch.object(claude.subprocess,'Popen',return_value=process), \
             patch.object(claude.os,'killpg') as kill:
            with self.assertRaises(KeyboardInterrupt):
                claude.run_session(Path(d),None,'task',30,model='claude-sonnet-4-6')
            kill.assert_called_once_with(process.pid,claude.signal.SIGKILL)
            process.wait.assert_called_once()
            self.assertEqual(json.loads((Path(d)/'run.json').read_text())['status'],'interrupted')

    def test_memory_disabled_for_every_claude_run(self):
        self.assertIs(claude.settings(Path('/workspace'))['autoMemoryEnabled'],False)

    def test_native_version_avoids_mutable_cli_symlink(self):
        with tempfile.TemporaryDirectory() as d, patch.object(claude.Path,'home',return_value=Path(d)):
            self.assertEqual(claude.executable(),'claude')
            pinned=Path(d)/'.local/share/claude/versions'/claude.VERSION
            pinned.parent.mkdir(parents=True)
            pinned.touch()
            self.assertEqual(claude.executable(),str(pinned))

    def test_normalized_usage_includes_cache_creation_and_reads(self):
        usage=claude.usage_from_result({'usage':{'input_tokens':10,'cache_creation_input_tokens':20,
                                               'cache_read_input_tokens':30,'output_tokens':5}})
        self.assertEqual(usage['input_tokens'],60)
        self.assertEqual(usage['cached_input_tokens'],30)
        self.assertIsNone(claude.usage_from_result({}))

    def test_factory_selects_provider_without_changing_codex(self):
        self.assertIs(factory.adapter('gpt-6-luna')[1],factory.run_session)
        self.assertIs(factory.adapter('claude-sonnet-4-6')[1],claude.run_session)

    def test_claude_external_access_joins_tool_results(self):
        rows=[{'type':'assistant','message':{'content':[{'type':'tool_use','id':'one','name':'Bash',
                'input':{'command':'curl https://example.org/slop-code-bench/solution'}}]}},
              {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'one',
                'content':'fetched reference'}]}}]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'transcript.jsonl';path.write_text('\n'.join(json.dumps(r) for r in rows))
            report=audit_external_sources(path)
        self.assertEqual(report['tool_calls'],1)
        self.assertEqual(report['events'][0]['output_records'],[2])
        self.assertTrue(report['review_suggested'])
