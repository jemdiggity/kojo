"""Exercise setup without downloading dependencies or installing provider CLIs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / '.tmp'
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream = self.root / 'upstream'
        self.upstream.mkdir()
        self.git('init', '-q', str(self.upstream))
        self.git('config', 'user.email', 'setup@example.test')
        self.git('config', 'user.name', 'Setup Test')
        for value in ('old', 'pinned', 'newer'):
            (self.upstream / 'file').write_text(value)
            self.git('add', 'file')
            self.git('commit', '-qm', value)
            if value == 'pinned':
                self.pin = self.git('rev-parse', 'HEAD').stdout.strip()
        self.work = self.root / 'work'
        (self.work / 'scripts').mkdir(parents=True)
        script = (ROOT / 'scripts/scb_install.sh').read_text()
        for url in ('https://github.com/SprocketLab/slop-code-bench.git',
                    'https://github.com/gabeorlanski/scb-problems.git'):
            script = script.replace(url, self.upstream.as_uri())
        for pin in ('31ceea3add480edb33431e70475c4c70597e6b31',
                    '38d627ecf668a88f88f8d260f8df8df6116e9b03'):
            script = script.replace(pin, self.pin)
        self.script = self.work / 'scripts/scb_setup.sh'
        self.script.write_text(script)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.executable(self.bin / 'uname', '#!/bin/sh\necho Darwin\n')
        self.executable(self.bin / 'uv', '#!/bin/sh\nexit 0\n')
        self.executable(self.bin / 'npm', '''#!/bin/sh
set -eu
echo install >> npm-calls
mkdir -p intermediate/provider-cli/node_modules/.bin
printf '#!/bin/sh\necho "codex-cli 0.159.2"\n' > intermediate/provider-cli/node_modules/.bin/codex
printf '#!/bin/sh\necho "2.1.283 (Claude Code)"\n' > intermediate/provider-cli/node_modules/.bin/claude
chmod +x intermediate/provider-cli/node_modules/.bin/*
''')
        self.env = dict(os.environ, KOJO_DATA_DIR=str(self.work), PATH=f'{self.bin}{os.pathsep}{os.environ["PATH"]}')

    def executable(self, path, text):
        path.write_text(text)
        path.chmod(0o755)

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.upstream,
                              check=True, capture_output=True, text=True)

    def run_setup(self, success=True):
        result = subprocess.run(['sh', str(self.script)], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result

    def test_fresh_setup_fetches_only_pin_and_rerun_reuses_clis(self):
        self.run_setup()
        for name in ('slop-code-bench', 'scb-problems'):
            checkout = self.work / 'intermediate/vendor' / name
            self.assertEqual(self.git('rev-parse', 'HEAD', cwd=checkout).stdout.strip(), self.pin)
            self.assertEqual(self.git('rev-list', '--count', 'HEAD', cwd=checkout).stdout.strip(), '1')
            self.assertEqual((checkout / 'file').read_text(), 'pinned')
        # Existing checkouts and working CLIs can be reused without the remote.
        shutil.rmtree(self.upstream)
        self.run_setup()
        self.assertEqual((self.work / 'npm-calls').read_text().splitlines(), ['install'])
        cli = self.work / 'intermediate/provider-cli/node_modules/.bin/codex'
        self.executable(cli, '#!/bin/sh\necho "codex-cli outdated"\n')
        self.run_setup()
        self.assertEqual(len((self.work / 'npm-calls').read_text().splitlines()), 2)
        cli.unlink()
        self.run_setup()
        self.assertEqual(len((self.work / 'npm-calls').read_text().splitlines()), 3)

    def test_failed_fetch_is_clean_and_retryable(self):
        original = self.script.read_text()
        self.script.write_text(original.replace(self.pin, '0' * 40))
        self.run_setup(success=False)
        self.assertEqual(list((self.work / 'intermediate/vendor').iterdir()), [])
        self.script.write_text(original)
        self.run_setup()

    def test_existing_dirty_or_wrong_revision_is_rejected(self):
        self.run_setup()
        checkout = self.work / 'intermediate/vendor/slop-code-bench'
        (checkout / 'file').write_text('local edit')
        self.assertIn('Local edits', self.run_setup(success=False).stderr)
        self.git('checkout', '--', 'file', cwd=checkout)
        self.git('fetch', '--depth=1', 'origin', 'HEAD', cwd=checkout)
        self.git('checkout', '--detach', 'FETCH_HEAD', cwd=checkout)
        self.assertIn('Wrong revision', self.run_setup(success=False).stderr)
