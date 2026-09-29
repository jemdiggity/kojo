"""Exercise the actual factory controller with fake inference and grading."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from kojo import factory


class FactoryChainTests(unittest.TestCase):
    def exercise_chain(self, flagged=False, audit_error=False, claude=False, timed_out=False, problem="code_search", count=5):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);(base/'configs').mkdir();(base/'configs/quota.json').write_text('{}')
            prompts=base/'configs/factory-prompts';prompts.mkdir()
            for role in ['build','review','fix']:
                (prompts/f'{role}.md').write_text(factory.instructions(None,role))
            calls=[];graded=[]
            backend=SimpleNamespace(protocol='fixed',runtime=base/'runtime',python='/python')
            def inference(run,instructions,prompt,seconds,*args,work_path,**kwargs):
                self.assertEqual(seconds,600)
                self.assertTrue(kwargs['network_enabled'])
                role=run.parents[1].name.removeprefix('training-');n=int(run.name.split('_')[-1])
                code=work_path/'code_search';text=code.read_text() if code.exists() else ''
                calls.append((role,n,text))
                self.assertNotIn('reviewer mutation',text)
                if role=='build' and n>1:self.assertTrue(text.endswith(f'fix-{n-1}\n'))
                if role=='fix':self.assertTrue((work_path/'.venv/marker').exists())
                if role=='review':code.write_text('reviewer mutation')
                else:
                    code.write_text(text+f'{role}-{n}\n')
                    (work_path/'.venv').mkdir(exist_ok=True)
                    (work_path/'.venv/marker').write_text('environment')
                run.mkdir(parents=True,exist_ok=True)
                for name,value in [('run.json',{'status':'budget_exhausted' if timed_out else 'complete','usage':{},'elapsed_seconds':1,'api_price_equivalent_usd':0}),('quota.json',[]),('verification.json',{}),('transcript-verification.json',{})]:
                    (run/name).write_text(json.dumps(value))
                (run/'answer.txt').write_text(f'feedback {n}')
                (run/'stock-instructions.md').write_text('stock')
            def score(rows):
                self.assertEqual(len(calls),3*count)  # No grade-driven feedback between sessions.
                row=rows[0];graded.append((row['role'],row['checkpoint']))
                (row['run']/'grading').mkdir();(row['run']/'grading/evaluation.json').write_text('{}')
                return [{'passed':1,'total':1,'checkpoint':row['checkpoint']}]
            experiment=SimpleNamespace(score=score)
            with contextlib.ExitStack() as stack:
                for name,value in [('BASE',base),('protocol_digest',lambda:'fixed'),('preflight',lambda **kw:({}, {'problems':{}})),('ChainBackend',lambda *a:backend),('Experiment',lambda *a:experiment),('audit_external_sources',lambda *a:{'review_suggested':flagged,'status':'suspected_benchmark_access' if flagged else 'no_benchmark_access_observed'}),('stage_prompt',lambda *a,**kw:f'prompt'),('run_session',inference)]:
                    stack.enter_context(patch.object(factory,name,value))
                if claude:
                    stack.enter_context(patch.object(factory.claude_execution,'run_session',inference))
                if audit_error:
                    stack.enter_context(patch.object(factory,'audit_external_sources',side_effect=ValueError('bad evidence')))
                with contextlib.redirect_stdout(io.StringIO()):
                    argv=['run','--run-id','test-chain','--problem',problem]+(['--build-model','claude-opus-4-6','--review-model','claude-sonnet-4-6','--claude-effort','high','--claude-max-budget-usd','3'] if claude else [])
                    if timed_out:
                        with self.assertRaisesRegex(RuntimeError,'Incomplete checkpoint'):factory.main(argv)
                    else:factory.main(argv)
            if timed_out:
                self.assertEqual([(r,n) for r,n,_ in calls],[('build',1)])
                self.assertEqual(graded,[])
                self.assertTrue((base/'results/runs/test-chain/STOPPED.json').exists())
                return
            self.assertEqual([(r,n) for r,n,_ in calls],[(r,n) for n in range(1,count+1) for r in ['build','review','fix']])
            self.assertEqual(len(graded),2*count)
            root=base/'results/runs/test-chain'
            self.assertFalse((root/'VALIDITY.json').exists())
            self.assertFalse((root/'STOPPED.json').exists())
            report=json.loads((root/'build/checkpoint_1/external-access.json').read_text())
            self.assertEqual(report['status'],'audit_error' if audit_error else ('suspected_benchmark_access' if flagged else 'no_benchmark_access_observed'))
            manifest=json.loads((root/'manifest.json').read_text())
            self.assertEqual(manifest['max_sessions'],3*count)
            self.assertEqual(manifest['seconds_per_session'],600)
            if claude:self.assertEqual(set(manifest['effort_by_role'].values()),{'high'})
            self.assertEqual((root/f'fix/checkpoint_{count}/submission/code_search').read_text(), ''.join(f'build-{n}\nfix-{n}\n' for n in range(1,count+1)))

    def test_repaired_code_and_environment_flow_forward_without_reviewer_edits(self):
        self.exercise_chain()

    def test_external_access_flag_is_reported_without_interrupting_chain(self):
        self.exercise_chain(flagged=True)

    def test_audit_error_is_reported_without_interrupting_chain(self):
        self.exercise_chain(audit_error=True)

    def test_claude_uses_same_checkpoint_review_fix_and_grading_chain(self):
        self.exercise_chain(claude=True)

    def test_timeout_never_reaches_reviewer_or_next_checkpoint(self):
        self.exercise_chain(timed_out=True)

    def test_eight_checkpoint_problem(self):
        self.exercise_chain(problem="circuit_eval", count=8)

    def test_four_checkpoint_problem(self):
        self.exercise_chain(problem="dynamic_config_service_api", count=4)
