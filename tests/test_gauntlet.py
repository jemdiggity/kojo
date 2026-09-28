"""Offline checks of split boundaries, revision selection, and paid-call safeguards."""

import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kojo.catalog import BASE, load_config, split_manifest
from kojo.gauntlet import (
    Backend,
    Experiment,
    SimulatedBackend,
    evaluation_score,
    skill_valid,
)


def fixture(directory):
    cfg = copy.deepcopy(load_config())
    cfg.update(
        training=["code_search"],
        validation=["etl_pipeline"],
        test=["xjq"],
        max_sessions=11,
    )
    recorded = json.loads((BASE / "configs/splits.json").read_text())
    manifest = {
        "problems": {
            n: copy.deepcopy(recorded["problems"][n])
            for n in ["code_search", "etl_pipeline", "xjq"]
        }
    }
    for value in manifest["problems"].values():
        value["checkpoints"] = [1]
    return SimulatedBackend(
        cfg, manifest, Path(directory) / "runs", Path(directory) / "results"
    )


class GauntletTests(unittest.TestCase):
    def test_split_overlap_and_near_duplicates_rejected(self):
        cfg = load_config()
        cfg["test"].append("code_search")
        with self.assertRaisesRegex(ValueError, "overlap"):
            split_manifest(cfg)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["a", "b"]:
                (root / name).mkdir()
                (root / name / "config.yaml").write_text("entry_file: run\n")
                (root / name / "checkpoint_1.md").write_text(
                    "Implement a command line tool that parses text and returns JSON records."
                )
            cfg.update(training=["a"], validation=[], test=["b"])
            with self.assertRaisesRegex(ValueError, "Near-duplicate"):
                split_manifest(cfg, root)

    def test_validation_selects_best_and_test_only_follows_freeze(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            backend = fixture(directory)
            experiment = Experiment(backend)
            with self.assertRaises(FileNotFoundError):
                experiment.evaluate()
            experiment.learn()
            freeze = json.loads((backend.output / "freeze.json").read_text())
            self.assertEqual(freeze["selected_revision"], "revision-1")
            self.assertEqual(len(list(backend.data.rglob("run.json"))), 8)
            inspection = json.loads(
                (backend.data / "writers/initial/work/inspection.json").read_text()
            )
            self.assertEqual(set(inspection), {"code_search"})
            for path in backend.data.glob("writers/revision-*/work/feedback.json"):
                feedback = json.loads(path.read_text())
                self.assertEqual({row["problem"] for row in feedback}, {"code_search"})
            original_grade = backend.grade

            def grade_after_generation(*args):
                # All three paired submissions must exist before the first test grading call.
                if "/test/" in str(args[-1]):
                    self.assertEqual(
                        len(list((backend.data / "test").rglob("snapshot.json"))), 3
                    )
                return original_grade(*args)

            with patch.object(backend, "grade", side_effect=grade_after_generation):
                experiment.evaluate()
            self.assertEqual(len(list(backend.data.rglob("run.json"))), 11)
            summary = json.loads((backend.output / "summary.json").read_text())
            self.assertTrue(summary["simulated"])
            self.assertEqual(len(summary["paired"]), 1)
            with self.assertRaisesRegex(RuntimeError, "locked"):
                experiment.learn()

    def test_frozen_skill_tampering_is_detected_before_test_calls(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            backend = fixture(directory)
            experiment = Experiment(backend)
            experiment.learn()
            (backend.output / "skills/learned/SKILL.md").write_text("modified")
            with self.assertRaisesRegex(RuntimeError, "Frozen skill changed"):
                experiment.evaluate()
            self.assertFalse((backend.data / "test").exists())

    def test_updater_rejects_nontraining_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = fixture(directory)
            experiment = Experiment(backend)
            with patch.object(backend, "session") as session:
                with self.assertRaisesRegex(RuntimeError, "Non-training"):
                    experiment.writer("revision-1", "skill", [{"name": "xjq"}])
                session.assert_not_called()

    def test_unapproved_session_never_reaches_model(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = Backend(
                load_config(), {}, Path(directory) / "runs", Path(directory) / "results"
            )
            with patch("kojo.gauntlet.run_session") as session:
                with self.assertRaisesRegex(RuntimeError, "not approved"):
                    backend.session(
                        Path(directory) / "attempt",
                        "instructions",
                        "prompt",
                        "solver",
                        "",
                    )
                session.assert_not_called()

    def test_changed_snapshot_cannot_resume(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            backend = fixture(directory)
            experiment = Experiment(backend)
            rows = experiment.solve_chain("training-1", "code_search", "")
            (rows[0]["run"] / "submission/implementation").write_text("tampered")
            with self.assertRaisesRegex(RuntimeError, "changed checkpoint"):
                experiment.solve_chain("training-1", "code_search", "")

    def test_infrastructure_failure_is_not_a_score(self):
        for row in [
            {"infrastructure_failure": True},
            {"infrastructure_failure": False, "pytest_collected": 0},
        ]:
            with self.assertRaisesRegex(RuntimeError, "infrastructure"):
                evaluation_score(row)

    def test_task_specific_or_oversized_skills_rejected(self):
        cfg = load_config()
        prefix = "---\nname: cli-software\ndescription: CLI work.\n---\n"
        for text in [prefix + "code_search", prefix + "x" * 6000, ""]:
            with self.assertRaises(ValueError):
                skill_valid(text, cfg)

    def test_agent_files_cannot_spoof_usage_receipts(self):
        from kojo.execution import session_paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "test/repeat-0/baseline/xjq/checkpoint_1/run.json"
            spoof = root / "test/repeat-0/baseline/xjq/checkpoint_1/work/run.json"
            real.parent.mkdir(parents=True)
            real.write_text("{}")
            spoof.parent.mkdir()
            spoof.write_text("{}")
            self.assertEqual(list(session_paths(root)), [real])
