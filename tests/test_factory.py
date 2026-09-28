"""Offline role input boundaries for the one-review factory."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kojo.factory import instructions, stage_prompt
from kojo.execution import command, cost
from kojo.gauntlet import copy_code, hashes
import tempfile

class FactoryTests(unittest.TestCase):
    def test_model_override_and_cost_do_not_use_luna_for_astra(self):
        with tempfile.TemporaryDirectory() as d:
            cmd=command(Path(d),'instructions',isolated_src=True,model='gpt-6-astra')
            self.assertIn('model="gpt-6-astra"',cmd)
        usage={'input_tokens':1000,'cached_input_tokens':500,'output_tokens':100}
        self.assertAlmostEqual(cost(usage,'gpt-6-astra'),100*cost(usage))

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
            copy_code(work,root/'snapshot')
            self.assertEqual(list(hashes(root/'snapshot')),['code_search'])
            (work/'leak').symlink_to('/etc/hosts')
            with self.assertRaises(RuntimeError):copy_code(work,root/'blocked')

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
