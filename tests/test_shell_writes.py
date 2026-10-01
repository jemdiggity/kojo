"""Native regression check; KOJO_NATIVE_TESTS=1 requires macOS sandbox access."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kojo.catalog import BASE
from kojo.execution import audit_shell_writes, command, permission_args, shell_environment


@unittest.skipUnless(os.environ.get('KOJO_NATIVE_TESTS') == '1', 'opt-in native sandbox test')
class ShellWriteTests(unittest.TestCase):
    def test_heredoc_regression_and_smoke_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='shell-regression-', dir=BASE/'intermediate') as d:
            work=Path(d)
            sandbox=['codex','sandbox',*permission_args(work,isolated_src=True),'-P','scb','-C',str(work)]
            env=shell_environment(work)
            cache=Path(env['NODE_COMPILE_CACHE']);self.assertTrue(cache.is_absolute() and not cache.is_relative_to(work))  # Shared, outside the workspace.
            env['TMPPREFIX']='/tmp/zsh'  # Old zsh default, even with a writable TMPDIR.
            failed=subprocess.run(sandbox+['/usr/bin/env',*[f'{k}={v}' for k,v in env.items()],
                '/bin/zsh','-lc',"cat > broken <<'EOF'\nhello\nEOF\n"],capture_output=True,text=True)
            self.assertNotEqual(failed.returncode,0)
            self.assertIn("can't create temp file for here document",failed.stderr)
            (work/'broken').unlink(missing_ok=True)
            audit_shell_writes(sandbox,work)
            self.assertEqual(list(work.iterdir()),[])


class RuntimePythonTests(unittest.TestCase):
    def test_runtime_bin_leads_path_and_login_shell_is_off(self):
        with tempfile.TemporaryDirectory() as d:
            work, runtime = Path(d) / 'work', Path(d) / 'venv'
            env = shell_environment(work, runtime)
            self.assertTrue(env['PATH'].startswith(f'{runtime}/bin{os.pathsep}'))
            self.assertEqual(env['VIRTUAL_ENV'], str(runtime))
            self.assertNotIn('PATH', shell_environment(work))
            args = command(Path(d) / 'run', None, runtime, isolated_src=True, work_path=work)
            self.assertIn('allow_login_shell=false', args)
            policy = next(a for a in args if a.startswith('shell_environment_policy.set='))
            self.assertIn(f'"VIRTUAL_ENV"="{runtime}"', policy)


if __name__=='__main__': unittest.main()
