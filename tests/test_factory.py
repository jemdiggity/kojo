"""Offline role input boundaries for the one-review factory."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kojo.factory import instructions, stage_prompt, run_checkpoint
from kojo.execution import command, cost
from kojo.gauntlet import copy_code, hashes
import tempfile

class FactoryTests(unittest.TestCase):
    def test_checkpoint_factory_order_feedback_and_carry_forward(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); calls=[]
            def session(role, checkpoint, source, feedback=None):
                calls.append((role,checkpoint,source,feedback))
                run=root/f'{role}-{checkpoint}';run.mkdir()
                if role=='review':
                    (run/'run.json').write_text(json.dumps({'status':'complete'}))
                    (run/'answer.txt').write_text(f'review {checkpoint}')
                return run
            first=run_checkpoint(session,1,None)
            second=run_checkpoint(session,2,first)
            self.assertEqual([(r,n) for r,n,_,_ in calls],
                             [('build',1),('review',1),('fix',1),('build',2),('review',2),('fix',2)])
            self.assertEqual(calls[2][2],root/'build-1/submission')
            self.assertEqual(calls[2][3],'review 1')
            self.assertEqual(calls[3][2],root/'fix-1/submission')
            self.assertEqual(second,root/'fix-2/submission')

    def test_checkpoint_factory_rejects_incomplete_review(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);calls=[]
            def session(role,checkpoint,source,feedback=None):
                calls.append(role)
                if role=='review':(root/'run.json').write_text('{"status":"budget_exhausted"}')
                return root
            with self.assertRaises(RuntimeError):run_checkpoint(session,3,None)
            self.assertEqual(calls,['build','review'])

    def test_checkpoint_review_and_fix_never_see_future_specs(self):
        spec=SimpleNamespace(spec=lambda name,n:f'PUBLIC SPEC {n}')
        for role in ['review','fix']:
            prompt=stage_prompt(spec,role,3,feedback='review feedback')
            for n in [1,2,3]:self.assertIn(f'PUBLIC SPEC {n}',prompt)
            for n in [4,5]:self.assertNotIn(f'PUBLIC SPEC {n}',prompt)

    def test_role_prompt_edit_changes_protocol_but_not_harness_hash(self):
        from kojo import catalog, factory
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);prompts=base/'configs/factory-prompts';prompts.mkdir(parents=True)
            for role in ['build','review','fix']:(prompts/f'{role}.md').write_text('')
            for name in ['scripts/kojo.py','scripts/scb_entrypoint.py','pyproject.toml','uv.lock','.python-version']:
                path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
            with patch.object(catalog,'BASE',base), patch.object(factory,'BASE',base), patch.object(factory,'DATA_ROOT',base):
                before=catalog.protocol_digest();harness=catalog.harness_digest()
                (prompts/'review.md').write_text('A changed reviewer request.\n')
                self.assertEqual(factory.instructions(None,'review'),'A changed reviewer request.')
                self.assertNotEqual(catalog.protocol_digest(),before)
                self.assertEqual(catalog.harness_digest(),harness)

    def test_model_override_and_cost_do_not_use_luna_for_astra(self):
        with tempfile.TemporaryDirectory() as d:
            cmd=command(Path(d),'instructions',isolated_src=True,model='gpt-6-astra')
            self.assertIn('model="gpt-6-astra"',cmd)
        usage={'input_tokens':1000,'cached_input_tokens':500,'output_tokens':100}
        self.assertAlmostEqual(cost(usage,'gpt-6-astra'),100*cost(usage))

    def test_pricing_table_covers_every_codex_model_and_rejects_unknown_ones(self):
        import re
        from kojo import execution
        allowed = re.search(r'model not in \(([^)]*)\)', Path(execution.__file__).read_text())[1]
        for model in re.findall(r'"([^"]+)"', allowed):
            with self.subTest(model=model):
                self.assertGreater(execution.pricing(model)['output'], 0)
        with self.assertRaises(ValueError):
            cost({'input_tokens':1,'output_tokens':1}, 'gpt-unknown')

    def test_sol_high_uses_requested_effort_and_default_output_limit(self):
        from kojo.factory import parse_args
        args, models, options = parse_args(['audit', '--run-id', 'sol-audit',
            '--build-model', 'gpt-5.6-sol', '--codex-effort', 'high', '--no-review'])
        self.assertEqual(options['build'], {'effort': 'high'})
        with tempfile.TemporaryDirectory() as d:
            cmd = command(Path(d), None, model=models['build'], **options['build'])
        self.assertIn('model="gpt-5.6-sol"', cmd)
        efforts = [v for v in cmd if v.startswith('model_reasoning_effort=')]
        self.assertEqual(efforts[-1], 'model_reasoning_effort="high"')
        self.assertFalse(any('max_output_tokens' in v for v in cmd))
        self.assertAlmostEqual(cost({'input_tokens':1000,'cached_input_tokens':500,
                                     'output_tokens':100}, 'gpt-5.6-sol'), .0042)

    def test_opus55_defaults_do_not_override_token_limits(self):
        from kojo.claude_execution import environment
        from kojo.factory import parse_args
        _, _, options = parse_args(['audit', '--run-id', 'opus-audit',
            '--build-model', 'claude-opus-5-5', '--claude-effort', 'high', '--no-review'])
        self.assertEqual(options['build'], {'effort': 'high'})
        env = environment('high', model='claude-opus-5-5')
        self.assertNotIn('MAX_THINKING_TOKENS', env)
        self.assertNotIn('CLAUDE_CODE_MAX_OUTPUT_TOKENS', env)

    def test_builder_uses_only_current_spec_and_upstream_renderer(self):
        spec=SimpleNamespace(spec=lambda name,n:f'PUBLIC SPEC {n}',b=SimpleNamespace(python='/python'))
        with patch('kojo.scb_prompt.render_checkpoint',return_value='upstream prompt') as render:
            self.assertEqual(stage_prompt(spec,'build',5),'upstream prompt')
            render.assert_called_once_with('PUBLIC SPEC 5',5,'/python')

    def test_fresh_commands_preserve_shared_checkpoint_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); work=root/'builder/src'; (work/'.venv').mkdir(parents=True)
            (work/'.venv/marker').write_text('environment persists')
            for n in [1,2]:
                cmd=command(root/f'checkpoint_{n}',None,isolated_src=True,work_path=work)
                self.assertEqual(cmd[cmd.index('-C')+1],str(work))
                self.assertNotIn('resume',cmd)
                self.assertEqual((work/'.venv/marker').read_text(),'environment persists')

    def test_snapshot_excludes_venv_symlinks_but_rejects_source_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'work';(work/'.venv/bin').mkdir(parents=True)
            (work/'.venv/bin/python').symlink_to(sys.executable)
            (work/'code_search').write_text('pass')
            (work/'node-compile-cache/v24').mkdir(parents=True);(work/'node-compile-cache/v24/0e90a45f').write_bytes(b'cache')
            (work/'__pycache__').mkdir();(work/'__pycache__/code_search.cpython-312.pyc').write_bytes(b'bytecode')
            copy_code(work,root/'snapshot')
            self.assertEqual(list(hashes(root/'snapshot')),['code_search'])
            self.assertEqual(list(hashes(work,exclude_generated=True)),['code_search'])
            (work/'leak').symlink_to('/etc/hosts')
            with self.assertRaises(RuntimeError):copy_code(work,root/'blocked')

    def test_frozen_snapshot_is_read_only_and_copies_of_it_are_writable(self):
        import os,subprocess
        from kojo.gauntlet import freeze,sync_workspace
        from kojo.quality import prepare
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);frozen=root/'submission';(frozen/'pkg').mkdir(parents=True)
            (frozen/'code_search').write_text('import pkg.helper\n');(frozen/'pkg/__init__.py').write_text('');(frozen/'pkg/helper.py').write_text('value=1\n')
            freeze(frozen);before=hashes(frozen)
            self.assertFalse(os.access(frozen,os.W_OK));self.assertFalse(os.access(frozen/'pkg/helper.py',os.W_OK))
            # Importing the frozen code in place, without PYTHONDONTWRITEBYTECODE, leaves no bytecode behind.
            env={k:v for k,v in os.environ.items() if k!='PYTHONDONTWRITEBYTECODE'}
            run=subprocess.run([sys.executable,'-c','import pkg.helper;print(pkg.helper.value)'],cwd=frozen,env=env,capture_output=True,text=True)
            self.assertEqual(run.stdout.strip(),'1',run.stderr)
            self.assertEqual(hashes(frozen),before);self.assertFalse((frozen/'pkg/__pycache__').exists())
            copy_code(frozen,root/'work')
            (root/'work/pkg/helper.py').write_text('value=2\n');(root/'work/new.py').write_text('')  # A workspace copy is writable.
            synced=root/'synced';sync_workspace(synced,frozen)
            (synced/'pkg/helper.py').write_text('value=3\n')
            self.assertEqual(prepare(frozen,root/'analysis','code_search',True),{'code_search':'code_search.py'})  # The analysis copy renames in place.
            self.assertEqual(hashes(frozen),before)

    def test_stock_command_does_not_override_base_instructions(self):
        with tempfile.TemporaryDirectory() as d:
            cmd=command(Path(d),None,isolated_src=True)
            self.assertNotIn('model_instructions_file',' '.join(cmd))
            self.assertFalse((Path(d)/'instructions.md').exists())
            self.assertEqual(list((Path(d)/'src').iterdir()),[])

    def test_review_has_full_specs_but_no_prior_feedback(self):
        spec=SimpleNamespace(spec=lambda name,n:f'PUBLIC SPEC {n}')
        review=stage_prompt(spec,'review')
        for n in range(1,6): self.assertIn(f'PUBLIC SPEC {n}',review)
        self.assertNotIn('Feedback from',review)
        self.assertIn('Do not implement fixes',instructions(SimpleNamespace(python='/python'),'review'))

    def test_fix_requires_review_and_carries_it_exactly(self):
        spec=SimpleNamespace(spec=lambda name,n:f'PUBLIC SPEC {n}')
        with self.assertRaises(ValueError): stage_prompt(spec,'fix')
        feedback='Observed defect at line 42.\nReproduce with example.'
        self.assertTrue(stage_prompt(spec,'fix',feedback=feedback).endswith(feedback))

if __name__=='__main__': unittest.main()
