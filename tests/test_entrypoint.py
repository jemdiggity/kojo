import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
p=Path(__file__).resolve().parents[1]/'scripts/scb_entrypoint.py'
spec=importlib.util.spec_from_file_location('entrypoint',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class EntrypointTests(unittest.TestCase):
    def test_real_launch_preserves_arguments_for_python_sh_and_bash(self):
        sources=['import sys; print(sys.argv[1]); sys.exit(7)', '#!/bin/sh\nprintf "%s\\n" "$1"\nexit 7\n', '#!/usr/bin/env bash\na=("$1"); printf "%s\\n" "${a[0]}"; exit 7\n']
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'entry'
            for source in sources:
                target.write_text(source)
                r=subprocess.run([sys.executable,str(p),str(target),'a b; echo nope'],cwd=d,capture_output=True,text=True)
                self.assertEqual(r.returncode,7,r.stderr);self.assertEqual(r.stdout,'a b; echo nope\n')
    def test_python_directory_entrypoint(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/"package";target.mkdir()
            with self.assertRaises(ValueError):module.interpreter(target,Path(sys.executable))
            (target/"helper.py").write_text("value=7")
            (target/"__main__.py").write_text("from .helper import value; import sys; print(sys.argv[1]); sys.exit(value)")
            r=subprocess.run([sys.executable,str(p),str(target),"a b"],cwd=d,capture_output=True,text=True)
            self.assertEqual(r.returncode,7,r.stderr);self.assertEqual(r.stdout,"a b\n")

    def test_unknown_language_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'entry';target.write_text('#!/usr/bin/env ruby\nputs 1')
            with self.assertRaises(ValueError):module.interpreter(target,Path('/python'))

    def test_shared_grader_uses_launcher_and_preserves_dependency_setup(self):
        from kojo.gauntlet import evaluation_environment
        with tempfile.TemporaryDirectory() as d:
            config=evaluation_environment(Path(sys.executable),Path(d)/'install.json')
            self.assertIn('scb_entrypoint.py',config['commands']['command'])
            self.assertTrue(config['commands']['command'].startswith('.venv/bin/python '))
            self.assertEqual(len(config['setup']['eval_commands']),3)
