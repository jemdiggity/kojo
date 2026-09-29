"""Skill condition freezing and provider discovery controls, without inference."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from kojo import skill_sets, execution, claude_execution, factory
from kojo.gauntlet import copy_code


def fixture(root, name='testing'):
    root.mkdir(parents=True, exist_ok=True)
    (root/'SKILL.md').write_text(f'---\nname: {name}\ndescription: Verify behavior with tests.\n---\nRead resources/example.txt before testing.\n')
    (root/'resources').mkdir()
    (root/'resources/example.txt').write_text('A supporting resource.\n')
    return root


class SkillSetsTests(unittest.TestCase):
    def test_freeze_preserves_resources_and_does_not_follow_original_edits(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=fixture(root/'input')
            before=skill_sets.describe(source)
            frozen=skill_sets.freeze_sets(root/'frozen',[before])[0]
            (source/'resources/example.txt').write_text('Changed')
            self.assertEqual(skill_sets.describe(frozen['path'])['sha256'],before['sha256'])
            self.assertNotEqual(skill_sets.describe(source)['sha256'],before['sha256'])
            self.assertEqual((Path(frozen['path'])/'resources/example.txt').read_text(),'A supporting resource.\n')

    def test_native_installs_are_separate_and_cannot_silently_mutate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=fixture(root/'input')
            for provider in ['codex','claude']:
                work=root/provider
                receipt=skill_sets.install(work,source,provider)
                installed=Path(receipt['installed_root'])/'testing/resources/example.txt'
                self.assertTrue(installed.exists())
                skill_sets.install(work,source,provider)
                installed.write_text('tampered')
                with self.assertRaises(RuntimeError):skill_sets.install(work,source,provider)

    def test_parallel_runs_have_private_copies_even_with_identical_skill_names(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            a=fixture(root/'set-a', 'testing')
            b=fixture(root/'set-b', 'testing')
            (b/'resources/example.txt').write_text('Condition B')
            for provider in ['codex','claude']:
                jobs=[(root/provider/'run-a',a), (root/provider/'run-b',b),
                      (root/provider/'run-a-repeat',a)]
                with ThreadPoolExecutor(max_workers=3) as pool:
                    receipts=list(pool.map(lambda pair:skill_sets.install(*pair,provider),jobs))
                paths=[Path(r['installed_root'])/'testing/resources/example.txt' for r in receipts]
                self.assertEqual(len({p.resolve() for p in paths}),3)
                self.assertEqual(len({p.stat().st_ino for p in paths}),3)
                paths[0].write_text('Run A changed its own copy')
                self.assertEqual(paths[1].read_text(),'Condition B')
                self.assertEqual(paths[2].read_text(),'A supporting resource.\n')
                self.assertEqual((a/'resources/example.txt').read_text(),'A supporting resource.\n')
                with self.assertRaises(RuntimeError):skill_sets.install(*jobs[0],provider)
                for work,source in jobs[1:]:skill_sets.install(work,source,provider)

    def test_baseline_empty_set_and_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);empty=root/'empty';empty.mkdir()
            self.assertEqual(skill_sets.describe(empty)['skills'],[])
            source=fixture(root/'input')
            with self.assertRaises(ValueError):skill_sets.describe_sets([source,source])
            (source/'escape').symlink_to(root)
            with self.assertRaises(ValueError):skill_sets.describe(source)
            (source/'escape').unlink()
            (source/'SKILL.md').write_text('Missing frontmatter')
            with self.assertRaises(ValueError):skill_sets.describe(source)

    def test_skill_files_not_carried_into_submissions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=fixture(root/'input');work=root/'src'
            skill_sets.install(work,source,'codex')
            skill_sets.install(work,source,'claude')
            (work/'solution.py').write_text('print(42)')
            copy_code(work,root/'snapshot')
            self.assertEqual([p.name for p in (root/'snapshot').iterdir()],['solution.py'])

    def test_commands_enable_only_native_discovery_without_prompt_override(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=fixture(root/'input')
            codex=execution.command(root/'codex',None,isolated_src=True,native_skill_set=source)
            self.assertIn('features.skip_host_skill_discovery=false',codex)
            self.assertFalse(any('model_instructions_file' in x for x in codex))
            with patch.object(claude_execution.subprocess,'run'):
                claude=claude_execution.command(root/'claude',root/'claude/src','claude-sonnet-5-5','medium','session',native_skill_set=source)
            self.assertIn('--plugin-dir',claude)
            self.assertNotIn('--disable-slash-commands',claude)
            self.assertNotIn('--system-prompt',claude)
            self.assertIn('Skill',claude[claude.index('--tools')+1])
            self.assertIn('--setting-sources',claude)
            self.assertEqual(claude[claude.index('--setting-sources')+1],'')

    def test_factory_rejects_changed_frozen_contents_before_launch(self):
        with tempfile.TemporaryDirectory() as d:
            source=fixture(Path(d)/'input');digest=skill_sets.describe(source)['sha256']
            flags=['audit','--run-id','skills-audit','--skill-set',str(source),'--skill-set-sha256',digest]
            args,_,_=factory.parse_args(flags)
            self.assertEqual(args.skill_manifest['sha256'],digest)
            (source/'resources/example.txt').write_text('Changed')
            with patch('sys.stderr'),self.assertRaises(SystemExit):factory.parse_args(flags)
