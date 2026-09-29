from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from kojo import known_skill_sets as known


class KnownSkillSetsTest(unittest.TestCase):
    def test_unknown_names_are_paths(self):
        self.assertEqual(known.resolve('./mine', '/cache'), Path('./mine'))

    def test_known_sets_are_pinned_to_full_commits(self):
        for name, (url, revision, subpath) in known.KNOWN.items():
            self.assertRegex(revision, r'^[0-9a-f]{40}$', name)
            self.assertTrue(url.startswith('https://'), name)

    def test_cached_set_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            revision = known.KNOWN['karpathy'][1]
            dest = Path(tmp) / revision[:12] / 'karpathy'
            dest.mkdir(parents=True)
            self.assertEqual(known.resolve('karpathy', tmp), dest)


if __name__ == '__main__':
    unittest.main()
