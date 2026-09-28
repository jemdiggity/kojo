"""Offline checks for clean source directories and incremental prompt boundaries."""
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kojo.execution import command
from kojo.run_chain import compose_prompt


class SrcRunTests(unittest.TestCase):
    def test_prompt_configuration_leaves_source_empty(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d)
            cmd=command(run,'common instructions',skill='guidance',isolated_src=True)
            self.assertEqual(list((run/'src').iterdir()), [])
            self.assertIn('guidance',(run/'instructions.md').read_text())
            self.assertEqual(cmd[cmd.index('-C')+1],str(run/'src'))
            settings=' '.join(cmd)
            self.assertIn('\":root\"=\"deny\"',settings)
            self.assertIn('\":slash_tmp\"=\"deny\"',settings)
            self.assertIn('permissions.scb.network.enabled=false',settings)

    def test_prompt_does_not_include_future_checkpoints(self):
        class Specs:
            def spec(self,name,n):
                return f'Unique spec {n}'
        prompt=compose_prompt(Specs(),3)
        for n in [1,2,3]:self.assertIn(f'Unique spec {n}',prompt)
        for n in [4,5]:self.assertNotIn(f'Unique spec {n}',prompt)

if __name__ == '__main__':
    unittest.main()
