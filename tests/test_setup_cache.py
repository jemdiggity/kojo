import concurrent.futures
import fcntl
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scb_setup', ROOT / 'scripts/scb_setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupCacheTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in setup.INPUTS:
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / name).read_bytes())
        self.cache = self.root / 'cache' / 'entry'
        self.cache.parent.mkdir()

    def populate(self, *args, **kwargs):
        for name in ('scb-runner-venv/bin/python', 'scb-runner-venv/bin/slop-code',
                     'provider-cli/node_modules/.bin/codex',
                     'provider-cli/node_modules/.bin/claude'):
            path = self.cache / 'intermediate' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def test_cache_fill_is_serialized_and_reused(self):
        def slow_install(*args, **kwargs):
            time.sleep(0.05)
            self.populate()
        with patch.object(setup, 'run', side_effect=slow_install) as install:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(setup.prepare_cache, self.root, self.cache, {}) for _ in range(2)]
                for future in futures:
                    future.result()
            self.assertEqual(install.call_count, 1)
            setup.prepare_cache(self.root, self.cache, {})
            self.assertEqual(install.call_count, 1)

    def test_failure_is_not_published_and_next_attempt_rebuilds(self):
        with patch.object(setup, 'run', side_effect=RuntimeError('install failed')):
            with self.assertRaisesRegex(RuntimeError, 'install failed'):
                setup.prepare_cache(self.root, self.cache, {})
        self.assertFalse((self.cache / 'ready').exists())
        stale = self.cache / 'partial-install'
        stale.touch()
        with patch.object(setup, 'run', side_effect=self.populate):
            setup.prepare_cache(self.root, self.cache, {})
        self.assertFalse(stale.exists())
        self.assertTrue((self.cache / 'ready').exists())

    def test_changed_inputs_invalidate_cache(self):
        original = setup.cache_key(self.root)
        lock = self.root / 'configs/solver.lock'
        lock.write_text(lock.read_text() + '\n# changed\n')
        self.assertNotEqual(setup.cache_key(self.root), original)

    def test_damaged_ready_cache_is_not_rebuilt_under_existing_users(self):
        with patch.object(setup, 'run', side_effect=self.populate):
            setup.prepare_cache(self.root, self.cache, {})
        (self.cache / 'intermediate/scb-runner-venv/bin/python').unlink()
        with patch.object(setup, 'run') as install:
            with self.assertRaisesRegex(RuntimeError, 'Incomplete setup cache'):
                setup.prepare_cache(self.root, self.cache, {})
            install.assert_not_called()

    def test_ordinary_checkout_uses_normal_setup_without_cache(self):
        with patch.object(setup, 'ROOT', self.root), patch.object(setup.platform, 'system', return_value='Darwin'), \
             patch.object(setup, 'linked_worktree', return_value=False), patch.object(setup, 'run') as run, \
             patch.object(setup, 'prepare_cache') as cache:
            setup.main()
            run.assert_called_once_with('sh', str(self.root / 'scripts/scb_install.sh'), cwd=self.root)
            cache.assert_not_called()

    def test_worktree_uses_cache_and_keeps_active_run_guard(self):
        with patch.object(setup, 'ROOT', self.root), patch.object(setup.platform, 'system', return_value='Darwin'), \
             patch.object(setup, 'linked_worktree', return_value=True), patch.object(setup, 'run') as run, \
             patch.object(setup, 'prepare_cache') as cache, patch.object(setup, 'attach') as attach, \
             patch.dict(os.environ, {'KOJO_SETUP_CACHE': str(self.cache.parent)}):
            setup.main()
            cache.assert_called_once()
            attach.assert_called_once()
            run.assert_called_once()
            self.assertEqual(run.call_args.args, ('uv', 'sync', '--frozen'))
            lock_path = self.root / 'intermediate/runs/active/launcher.lock'
            lock_path.parent.mkdir(parents=True)
            with lock_path.open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with self.assertRaisesRegex(RuntimeError, 'Active run'):
                    setup.main()
            self.assertEqual(cache.call_count, 1)

    def test_detects_linked_git_worktree(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Test', '-c',
                        'user.email=test@example.test', 'commit', '--allow-empty', '-qm', 'fixture'], check=True)
        linked = self.root / 'linked'
        subprocess.run(['git', '-C', str(self.root), 'worktree', 'add', '--detach', str(linked)],
                       check=True, capture_output=True)
        self.assertFalse(setup.linked_worktree(self.root))
        self.assertTrue(setup.linked_worktree(linked))

    @unittest.skipUnless(os.uname().sysname == 'Darwin', 'macOS copy-on-write')
    def test_vendor_copies_are_isolated_and_dirty_edits_preserved(self):
        for name in setup.VENDORS:
            repo = self.cache / 'intermediate/vendor' / name
            repo.mkdir(parents=True)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            (repo / 'source').write_text('original')
            subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c',
                            'user.email=test@example.test', 'commit', '-qm', 'fixture'], check=True)
        def local_run(*args, **kwargs):
            if args[0] == 'cp':
                subprocess.run(args, check=True)
        with patch.object(setup, 'run', side_effect=local_run):
            setup.attach(self.root, self.cache, {})
            for name in setup.SHARED:
                self.assertTrue((self.root / 'intermediate' / name).is_symlink())
            local = self.root / 'intermediate/vendor/slop-code-bench/source'
            local.write_text('local edit')
            self.assertEqual((self.cache / 'intermediate/vendor/slop-code-bench/source').read_text(), 'original')
            with self.assertRaisesRegex(RuntimeError, 'Local edits'):
                setup.attach(self.root, self.cache, {})
            self.assertEqual(local.read_text(), 'local edit')
