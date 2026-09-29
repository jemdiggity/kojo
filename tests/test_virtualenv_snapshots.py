"""A model-selected environment name must not break source export."""
import sys
from pathlib import Path
import tempfile
import socket
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kojo.gauntlet import hashes,copy_code

class VirtualenvSnapshotTests(unittest.TestCase):
    def test_named_environment_stays_live_but_is_not_submitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);src=root/'src';src.mkdir()
            (src/'code_search').write_text('source')
            env=src/'custom-env';(env/'bin').mkdir(parents=True)
            (env/'pyvenv.cfg').write_text('home = /runtime')
            (env/'bin/python').symlink_to('/usr/bin/python3')
            expected=hashes(src,exclude_generated=True)
            self.assertEqual(set(expected),{'code_search'})
            copy_code(src,root/'snapshot')
            self.assertEqual(hashes(root/'snapshot'),expected)
            self.assertTrue((env/'bin/python').is_symlink())

    def test_source_symlinks_still_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            src=Path(directory);(src/'link').symlink_to('/etc/hosts')
            with self.assertRaises(RuntimeError):hashes(src,exclude_generated=True)

    def test_live_sandbox_socket_is_not_exported(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            root=Path(directory);src=root/'src';src.mkdir()
            (src/'code_search').write_text('source')
            with socket.socket(socket.AF_UNIX) as ipc:
                ipc.bind(str(src/'sandbox.sock'))
                copy_code(src,root/'snapshot')
                self.assertEqual(set(hashes(root/'snapshot')),{'code_search'})
