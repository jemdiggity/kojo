"""One baseline sequence, fresh isolated CLI sessions; grading is a separate command."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parents[1]
DATA = BASE / "intermediate/runs/20260927-code-search-continuation-01"
PROBLEMS = BASE / "intermediate/vendor/scb-problems"
IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".git", ".venv", ".pytest_cache"
)


def snapshot(n):
    return BASE / f"results/runs/20260927-code-search-continuation-01/checkpoints/checkpoint_{n}/submission"


def generate():
    DATA.mkdir(parents=True, exist_ok=True)
    if not snapshot(1).exists():
        raise RuntimeError(
            "Missing frozen checkpoint-1 seed; preserve results/runs/20260927-code-search-continuation-01/checkpoints/checkpoint_1"
        )
    for n in range(2, 6):
        run = DATA / f"checkpoint_{n}"
        if (run / "run.json").exists():
            row = json.loads((run / "run.json").read_text())
            if row["status"] != "complete" or not snapshot(n).exists():
                raise RuntimeError(
                    f"Checkpoint {n} already attempted; manual review required, no automatic retry"
                )
            continue
        if snapshot(n).exists():
            raise RuntimeError(
                f"Frozen checkpoint {n} exists without a local attempt record; refusing overwrite or paid rerun"
            )
        work = run / "work"
        if work.exists():
            raise RuntimeError(
                f"Unrecorded workspace exists: {work}; inspect before proceeding"
            )
        shutil.copytree(snapshot(n - 1), work, ignore=IGNORE)
        (work / "specs").mkdir(exist_ok=True)
        for prior in range(1, n):
            text = (PROBLEMS / f"code_search/checkpoint_{prior}.md").read_text()
            text = text.replace("%%%ENTRYPOINT:entry_file%%%", "code_search").replace(
                "%%%ENTRYPOINT:entry_command%%%", "./code_search"
            )
            (work / f"specs/checkpoint_{prior}.md").write_text(text)
        env = {**os.environ, "SCB_CHECKPOINT": str(n)}
        for mode in ["audit", "run"]:
            subprocess.run(
                [sys.executable, str(BASE / "scripts/kojo.py"), "_agent", mode],
                env=env,
                check=True,
            )
        row = json.loads((run / "run.json").read_text())
        if row["status"] != "complete":
            raise RuntimeError(f"Checkpoint {n} did not complete")
        shutil.copytree(work, snapshot(n), ignore=IGNORE)
        hashes = {
            str(p.relative_to(snapshot(n))): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in snapshot(n).rglob("*")
            if p.is_file()
        }
        (snapshot(n).parent / "sha256.json").write_text(
            json.dumps(hashes, indent=2) + "\n"
        )
        shutil.copy2(run / "run.json", snapshot(n).parent / "run.json")
        shutil.copy2(run / "usage.json", snapshot(n).parent / "quota.json")
        shutil.copy2(
            run / "verification.json", snapshot(n).parent / "verification.json"
        )
        print(f"CHECKPOINT {n} FROZEN", flush=True)


def grade():
    env = {
        **os.environ,
        "MSWEA_GLOBAL_CONFIG_DIR": str(DATA / "mswea"),
        "MSWEA_SILENT_STARTUP": "1",
        "SCBENCH_PROBLEMS_PATH": str(PROBLEMS),
        "UV_CONSTRAINT": str(BASE / "configs/grader.lock"),
        "UV_PYTHON": "3.12.8",
        "PYTEST_ADDOPTS": ".evaluation_tests",
    }
    for n in range(1, 6):
        dest = BASE / f"results/runs/20260927-code-search-continuation-01/checkpoints/checkpoint_{n}/grading"
        if dest.exists():
            raise RuntimeError(f"Grading output already exists: {dest}")
        command = [
            str(BASE / "intermediate/scb-runner-venv/bin/slop-code"),
            "--quiet",
            "eval-snapshot",
            str(snapshot(n)),
            "-o",
            str(dest),
            "-p",
            "code_search",
            "-c",
            str(n),
            "-e",
            str(BASE / "configs/local.yaml"),
            "--json",
        ]
        with (DATA / f"grade_{n}.log").open("w") as log:
            subprocess.run(
                command,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=300,
            )
        row = json.loads((dest / "evaluation.json").read_text())
        if row["infrastructure_failure"]:
            raise RuntimeError(
                f"Checkpoint {n}: infrastructure failure; not a task failure"
            )
        print(n, json.dumps({k: v for k, v in row.items() if k != "tests"}), flush=True)


if __name__ == "__main__":
    {"generate": generate, "grade": grade}[sys.argv[1]]()
