import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
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
            config=evaluation_environment(Path(sys.executable),Path(d)/'install.json',Path(d)/'venv')
            self.assertIn('scb_entrypoint.py',config['commands']['command'])
            self.assertTrue(config['commands']['command'].startswith('.venv/bin/python '))
            [command]=config['setup']['eval_commands']
            script=shlex.split(command)[2]
            for expected in ['-m venv',' -m pip install --disable-pip-version-check --no-input --no-cache-dir --report ','-r requirements.txt',' -m pip freeze > ','ln -s']:
                self.assertIn(expected,script)
            self.assertEqual(evaluation_environment(Path(sys.executable))['setup']['eval_commands'],[])

    def test_regrade_adapter_keeps_the_shared_environment_and_its_venv(self):
        regrade_spec=importlib.util.spec_from_file_location('scb_regrade',p.with_name('scb_regrade.py'))
        regrade=importlib.util.module_from_spec(regrade_spec);regrade_spec.loader.exec_module(regrade)
        with tempfile.TemporaryDirectory() as d:
            config=regrade.launcher_environment(Path(sys.executable),Path(d)/'install.json',Path(d)/'venv')
            self.assertTrue(config['commands']['command'].startswith(shlex.quote(sys.executable)+' ') or config['commands']['command'].startswith(sys.executable+' '))
            self.assertIn('scb_entrypoint.py',config['commands']['command'])
            [command]=config['setup']['eval_commands']
            self.assertIn(shlex.quote(str(Path(d)/'venv')),command)  # The snapshot's one environment, as in the factory.

    def test_snapshot_environment_is_built_once_and_linked_into_every_workspace(self):
        """The evaluator runs the setup command before each of its pytest spawns, in fresh workspace
        copies of the snapshot; the venv, the install and the receipts happen once per snapshot."""
        from kojo.gauntlet import evaluation_environment
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);log=root/'calls.log';fake=root/'python'
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> '+shlex.quote(str(log))+'\n'
                            'if [ "$1" = -m ] && [ "$2" = venv ]; then mkdir -p "$3/bin" && cp "$0" "$3/bin/python"; fi\n'
                            'if [ "$1" = -m ] && [ "$2" = pip ] && [ "$3" = install ] && [ -f "${KOJO_FAIL_INSTALL:-/nonexistent}" ]; then exit 9; fi\n'
                            'exit 0\n')
            fake.chmod(0o755)
            calls=lambda: log.read_text().splitlines() if log.exists() else []
            def spawn(command,workspace,requirements='pyyaml\n',env=None):
                workspace.mkdir(exist_ok=True)
                if requirements is not None:(workspace/'requirements.txt').write_text(requirements)
                return subprocess.run(shlex.split(command),cwd=workspace,capture_output=True,text=True,env={**os.environ,**(env or {})})
            venv=root/'venv';report=root/'dependency-install.json'
            [command]=evaluation_environment(fake,report,venv)['setup']['eval_commands']
            first=root/'collect'
            self.assertEqual(spawn(command,first).returncode,0)
            self.assertEqual([c.split()[:3] for c in calls()],[['-m','venv',str(venv)],['-m','pip','install'],['-m','pip','freeze']])
            self.assertIn(f'--report {report} -r requirements.txt',calls()[1])
            self.assertTrue((first/'.venv').is_symlink());self.assertEqual((first/'.venv').resolve(),venv.resolve())
            self.assertTrue((venv/'.kojo-ready').exists());self.assertTrue(report.with_name('dependency-freeze.txt').exists())
            self.assertEqual(spawn(command,first).returncode,0)  # The next spawn in the same workspace.
            second=root/'run';(second/'.venv').mkdir(parents=True)  # A fresh workspace copy for the test run.
            self.assertEqual(spawn(command,second).returncode,0)
            self.assertEqual(len(calls()),3)  # Nothing rebuilt; the shared environment is linked in.
            self.assertTrue((second/'.venv').is_symlink())
            # A failed install is reported to the evaluator, the tests still run, and the next spawn retries it.
            failing=root/'failing';venv2=root/'venv2';report2=root/'r2.json';marker=root/'fail';marker.write_text('')
            [command2]=evaluation_environment(fake,report2,venv2)['setup']['eval_commands']
            self.assertEqual(spawn(command2,failing,env={'KOJO_FAIL_INSTALL':str(marker)}).returncode,9)
            self.assertTrue((failing/'.venv').is_symlink());self.assertFalse((venv2/'.kojo-ready').exists())
            self.assertEqual(spawn(command2,root/'retry').returncode,0)
            self.assertTrue((venv2/'.kojo-ready').exists())
            # Without requirements there is nothing to install; the receipts still record the environment.
            venv3=root/'venv3';report3=root/'r3.json'
            [command3]=evaluation_environment(fake,report3,venv3)['setup']['eval_commands']
            before=len(calls())
            self.assertEqual(spawn(command3,root/'bare',requirements=None).returncode,0)
            self.assertEqual([c.split()[:3] for c in calls()[before:]],[['-m','venv',str(venv3)],['-m','pip','freeze']])
