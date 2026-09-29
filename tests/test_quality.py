"""Analysis-copy coverage must not mutate or double-count an entrypoint."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('quality',Path(__file__).resolve().parents[1]/'scripts/scb_quality.py')
quality=importlib.util.module_from_spec(spec);spec.loader.exec_module(quality)

class QualityTests(unittest.TestCase):
    def test_extensionless_entrypoint_is_renamed_only_in_copy(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();(source/'circopt').write_text('print(1)\n')
            mapping=quality.prepare(source,root/'analysis','circopt',True)
            self.assertEqual(mapping,{'circopt':'circopt.py'})
            self.assertTrue((source/'circopt').exists())
            self.assertFalse((root/'analysis/circopt').exists())
            self.assertEqual((root/'analysis/circopt.py').read_bytes(),(source/'circopt').read_bytes())

    def test_does_not_overwrite_existing_python_module(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();(source/'tool').write_text('pass');(source/'tool.py').write_text('pass')
            with self.assertRaisesRegex(RuntimeError,'collision'):quality.prepare(source,root/'analysis','tool',True)

    def test_every_code_changing_stage_is_analyzed_in_run_order(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            run=Path(d)
            for order,(stage,label,frozen) in enumerate([('build','checkpoint_1',True),('review','checkpoint_1',False),('fix','checkpoint_1',True),
                                                          ('build','checkpoint_2',True),('refactor','checkpoint_2',True),('skill-set','checkpoint_9',False)]):
                directory=run/stage/label;directory.mkdir(parents=True)
                (directory/'run.json').write_text('{}');os.utime(directory/'run.json',(order,order))
                if frozen:(directory/'snapshot.json').write_text('{}')
            self.assertEqual([(c.parent.name,c.name) for c in quality.frozen_snapshots(run)],
                             [('build','checkpoint_1'),('fix','checkpoint_1'),('build','checkpoint_2'),('refactor','checkpoint_2')])
