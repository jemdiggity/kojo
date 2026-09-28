"""Check recorded provenance and recorded submission integrity without inference."""

import hashlib
import json
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parents[1]
RESULTS = BASE / "results/runs/20260927-code-search-continuation-01"


class ArtifactTests(unittest.TestCase):
    def test_recorded_dependency_and_seed_hashes(self):
        pins = json.loads((RESULTS / "pins.json").read_text())
        migrations = json.loads((BASE / "results/runs/relocations.json").read_text())["moves"]
        for name, expected in pins["sha256"].items():
            for move in migrations:
                if name.startswith(move["from"] + "/"):
                    name = move["to"] + name[len(move["from"]):]
                    break
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((BASE / name).read_bytes()).hexdigest(), expected
                )

    def test_frozen_submissions_and_test_accounting(self):
        for n in range(1, 6):
            path = RESULTS / f"checkpoints/checkpoint_{n}"
            for name, expected in json.loads(
                (path / "sha256.json").read_text()
            ).items():
                with self.subTest(checkpoint=n, file=name):
                    self.assertEqual(
                        hashlib.sha256(
                            (path / "submission" / name).read_bytes()
                        ).hexdigest(),
                        expected,
                    )
            report = json.loads((path / "grading/evaluation.json").read_text())
            self.assertFalse(report["infrastructure_failure"])
            count = sum(
                len(ids) for group in report["tests"].values() for ids in group.values()
            )
            self.assertEqual(count, report["pytest_collected"])

    def test_reporting_reproduces_recorded_metrics(self):
        import contextlib
        import io
        import sys

        sys.path.insert(0, str(BASE / "src"))
        from kojo import report
        import shutil
        import tempfile
        from unittest.mock import patch

        before = json.loads((RESULTS / "results.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "results"
            shutil.copytree(RESULTS, target)
            with (
                patch.object(report, "ROOT", target),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                report.main()
            self.assertEqual(json.loads((target / "results.json").read_text()), before)

    def test_existing_snapshot_cannot_trigger_paid_rerun(self):
        import sys
        import tempfile
        from unittest.mock import patch

        sys.path.insert(0, str(BASE / "src"))
        from kojo import sequence

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(sequence, "DATA", Path(directory)),
                patch.object(sequence.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "refusing overwrite or paid rerun"
                ):
                    sequence.generate()
                run.assert_not_called()
