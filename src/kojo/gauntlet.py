"""Fixed-budget skill learning and paired SCB evaluation; official grading stays external."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import time

from kojo.catalog import (
    BASE,
    REPO,
    check_repositories,
    digest,
    load_config,
    protocol_digest,
    split_manifest,
)
from kojo.execution import audit, run_session, save, session_paths

DATA = BASE / "intermediate/gauntlet"
OUTPUT = BASE / "results/gauntlet"
CONDITIONS = ["baseline", "initial", "learned"]
EXCLUDED = {
    "SPEC.md",
    "SKILL.md",
    "instructions.md",
    "specs",
    ".git",
    ".agents",
    ".claude",
    ".venv",
    "__pycache__",
    ".pytest_cache",
}


def read(path):
    return json.loads(path.read_text())


def skill_valid(text, cfg):
    if not text.strip() or len(text.encode()) > cfg["skill_max_bytes"]:
        raise ValueError("Empty or oversized skill")
    if not re.match(r"\A---\s*\nname:\s*cli-software\s*\ndescription:\s*\S", text):
        raise ValueError("Skill requires cli-software name and description frontmatter")
    if "\n---" not in text[4:]:
        raise ValueError("Unterminated skill frontmatter")
    # Reject benchmark identifiers; this is a guardrail, not a proof of semantic generality.
    for name in cfg["training"] + cfg["validation"] + cfg["test"]:
        if re.search(r"\b" + re.escape(name) + r"\b", text):
            raise ValueError("Task-specific identifier in reusable skill")
    return text


def hashes(directory, exclude_generated=False):
    result = {}
    environments={p.parent for p in directory.rglob('pyvenv.cfg')} if exclude_generated else set()
    for path in sorted(directory.rglob("*")):
        if exclude_generated and (any(part in EXCLUDED for part in path.relative_to(directory).parts) or path.name.endswith(".pyc") or any(path==env or env in path.parents for env in environments)):
            continue
        if path.is_symlink():
            raise RuntimeError("Symlinks are not allowed in frozen submissions")
        if path.is_file():
            result[str(path.relative_to(directory))] = digest(path)
    return result


def copy_code(source, target):
    def ignore(directory, names):
        return [n for n in names if n in EXCLUDED or n.endswith(".pyc") or (Path(directory)/n/'pyvenv.cfg').is_file() or (Path(directory)/n).is_socket()]

    if source:
        hashes(source, exclude_generated=True)
        shutil.copytree(source, target, ignore=ignore)
    else:
        target.mkdir(parents=True)


def evaluation_score(report):
    if report.get("infrastructure_failure") or report.get("pytest_collected", 0) == 0:
        raise RuntimeError("Evaluator infrastructure failure; not a model failure")
    total = sum(report["total_counts"].values())
    passed = sum(report["pass_counts"].values())
    return {
        "strict": int(passed == total),
        "passed": passed,
        "total": total,
        "fraction": passed / total,
    }


def split_counts(report, checkpoint):
    """Passed/total for this checkpoint's own tests (core, functionality, error) and, separately,
    for the regression tests carried over from earlier checkpoints."""
    counts = {"new": [0, 0], "regression": [0, 0]}
    for group, result in report.get("tests", {}).items():
        own = group.startswith(f"checkpoint_{checkpoint}-")
        bucket = counts["new" if own else "regression"]
        bucket[0] += len(result["passed"])
        bucket[1] += len(result["passed"]) + len(result["failed"]) + len(result.get("skipped", []))
    return {name: {"passed": p, "total": t} for name, (p, t) in counts.items()}


def test_diff(report, before):
    """(passing, broken, gained) against `before`, the tests passing after the previous session.
    A test is Core/Functionality/Error in its own checkpoint and Regression later, so tests are
    matched by checkpoint and name."""
    passing = {(g.split("-")[0], t) for g, r in report.get("tests", {}).items() for t in r["passed"]}
    failing = [(g, t) for g, r in report.get("tests", {}).items() for t in r["failed"]]
    broken = sorted(f for f in failing if (f[0].split("-")[0], f[1]) in before)
    return passing, broken, passing - before


def rank(rows):
    return (
        sum(r["strict"] for r in rows),
        sum(r["fraction"] for r in rows) / len(rows),
    )


def preflight(write=False, *, check_codex=True):
    cfg = load_config()
    check_repositories(cfg)
    if (cfg["model"], cfg["reasoning"]) != ("gpt-6-luna", "low"):
        raise RuntimeError("This adapter is pinned to Luna low reasoning")
    if sys.version.split()[0] != cfg["python"]:
        raise RuntimeError("Use Python " + cfg["python"])
    if check_codex and (
        subprocess.check_output(["codex", "--version"], text=True).strip()
        != "codex-cli " + cfg["codex_version"]
    ):
        raise RuntimeError("Wrong Codex CLI version")
    manifest = split_manifest(cfg)
    path = BASE / "configs/splits.json"
    if write and not path.exists():
        save(path, manifest)
    if not path.exists() or read(path) != manifest:
        raise RuntimeError("Recorded splits differ from pinned public catalog")
    runtime = BASE / cfg["runtime"]
    expected = dict(
        line.split("==")
        for line in (BASE / "configs/solver.in").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    )
    script = (
        "import json,importlib.metadata as m; print(json.dumps({p:m.version(p) for p in "
        + repr(list(expected))
        + "}))"
    )
    actual = json.loads(
        subprocess.check_output([str(runtime / "bin/python"), "-c", script], text=True)
    )
    if actual != expected:
        raise RuntimeError("Installed solver library versions differ from pins")
    return cfg, manifest


def plan(cfg, manifest):
    counts = manifest["checkpoint_counts"]
    learning = (
        1
        + counts["validation"]
        + cfg["learning_rounds"] * (counts["training"] + 1 + counts["validation"])
    )
    tests = counts["test"] * len(CONDITIONS) * cfg["test_repeats"]
    if learning + tests != cfg["max_sessions"]:
        raise RuntimeError("Session ceiling inconsistent with protocol")
    return {
        "model": cfg["model"],
        "writer_model": cfg["model"],
        "stronger_model_writer": False,
        "checkpoints": counts,
        "learning_sessions": learning,
        "test_sessions": tests,
        "max_sessions": learning + tests,
        "test_repeats": cfg["test_repeats"],
        "max_solver_seconds": cfg["solver_seconds"],
        "max_writer_seconds": cfg["writer_seconds"],
        "estimated_api_equivalent_usd_range": [0.3, 3.0],
        "actual_subscription_cash_cost_usd": None,
        "quota": read(BASE / "configs/quota.json"),
        "approval_required": True,
        "protocol_sha256": protocol_digest(),
    }


def evaluation_environment(python, dependency_report=None):
    """SCB local setup; network runs rebuild declared dependencies per snapshot."""
    commands=[]
    entry=str(python)
    if dependency_report is not None:
        report=shlex.quote(str(dependency_report))
        frozen=shlex.quote(str(dependency_report.with_name('dependency-freeze.txt')))
        commands=[shlex.quote(str(python))+' -m venv .venv',
                  'if [ -f requirements.txt ]; then .venv/bin/python -m pip install --disable-pip-version-check --no-input --no-cache-dir --report '+report+' -r requirements.txt; fi',
                  '.venv/bin/python -m pip freeze > '+frozen]
        commands = ['/bin/sh -c ' + shlex.quote(command) for command in commands]
        entry='.venv/bin/python'
    return {'type':'local','name':'gauntlet-python312','environment':{'include_os_env':True},
            'setup':{'commands':[],'eval_commands':commands},
            'commands':{'entry_file':'{entry_file}','command':shlex.join([entry,str(BASE/'scripts/scb_entrypoint.py')])}}


class Backend:
    simulated = False

    def __init__(self, cfg, manifest, data=DATA, output=OUTPUT):
        self.cfg = cfg
        self.manifest = manifest
        self.data = data
        self.output = output
        self.runtime = BASE / cfg["runtime"]
        self.python = Path(sys._base_executable).resolve()
        self.protocol = protocol_digest()

    def authorize(self):
        path = BASE / "configs/gauntlet-approval.json"
        approval = read(path) if path.exists() else {}
        if (
            approval.get("approved") is not True
            or approval.get("protocol_sha256") != self.protocol
        ):
            raise RuntimeError(
                "Paid experiment is not approved for this exact protocol"
            )
        if protocol_digest() != self.protocol:
            raise RuntimeError("Protocol changed during execution")
        if (self.data / "protocol.json").exists() and read(self.data / "protocol.json")[
            "sha256"
        ] != self.protocol:
            raise RuntimeError("Existing run directory belongs to a different protocol")
        if approval.get("max_sessions") != self.cfg["max_sessions"]:
            raise RuntimeError("Approval session ceiling does not match")

    def session(self, run, instructions, prompt, role, skill=None):
        self.authorize()
        ledger_path = self.data / "ledger.json"
        ledger = read(ledger_path) if ledger_path.exists() else []
        if len(ledger) >= self.cfg["max_sessions"]:
            raise RuntimeError("Session budget exhausted")
        if any(r["path"] == str(run.relative_to(self.data)) for r in ledger):
            raise RuntimeError(
                "Session already reserved; interrupted sessions require manual review"
            )
        ledger.append(
            {
                "path": str(run.relative_to(self.data)),
                "role": role,
                "reserved_at": time.time(),
            }
        )
        save(ledger_path, ledger)
        return run_session(
            run,
            instructions,
            prompt,
            self.cfg["solver_seconds"]
            if role == "solver"
            else self.cfg["writer_seconds"],
            self.runtime if role == "solver" else None,
            skill,
            sorted(
                [
                    sample
                    for receipt in session_paths(self.data)
                    if (receipt.parent / "quota.json").exists()
                    for sample in read(receipt.parent / "quota.json")
                ],
                key=lambda s: s["observed_at"],
            ),
        )

    def grade(self, submission, name, checkpoint, dest):
        check_repositories(self.cfg)
        if dest.exists():
            return evaluation_score(read(dest / "evaluation.json"))
        config = self.data / "local.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        install_dependencies=getattr(self,'install_dependencies',False)
        dependency_report=dest.parent/'dependency-install.json' if install_dependencies else None
        config.write_text(json.dumps(evaluation_environment(self.python,dependency_report),indent=2)+'\n')
        env = {
            **os.environ,
            "MSWEA_GLOBAL_CONFIG_DIR": str(self.data / "mswea"),
            "MSWEA_SILENT_STARTUP": "1",
            "SCBENCH_PROBLEMS_PATH": str(REPO),
            "UV_CONSTRAINT": str(BASE / "configs/gauntlet-grader.lock"),
            "UV_PYTHON": "3.12.8",
            "PYTEST_ADDOPTS": ".evaluation_tests",
            "PYTHONPATH": str(self.runtime / "lib/python3.12/site-packages"),
        }
        if install_dependencies:
            env.pop('PYTHONPATH',None)
        cmd = [
            str(BASE / "intermediate/scb-runner-venv/bin/slop-code"),
            "--quiet",
            "eval-snapshot",
            str(submission),
            "-o",
            str(dest),
            "-p",
            name,
            "-c",
            str(checkpoint),
            "-e",
            str(config),
            "--json",
        ]
        with dest.with_suffix(".log").open("w") as log:
            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                if process.wait(timeout=900):
                    raise RuntimeError("Evaluator command failed; inspect its log")
            except BaseException:
                if process.poll() is None:
                    import signal

                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
        return evaluation_score(read(dest / "evaluation.json"))


class SimulatedBackend(Backend):
    """Exercises orchestration only; fabricated scores must never be reported as benchmark results."""

    simulated = True

    def authorize(self):
        pass

    def session(self, run, instructions, prompt, role, skill=None):
        run.mkdir(parents=True, exist_ok=True)
        if (run / "run.json").exists():
            raise RuntimeError("Duplicate simulated session")
        calls = list(session_paths(self.data))
        if len(calls) >= self.cfg["max_sessions"]:
            raise RuntimeError("Session budget exhausted")
        if role == "solver":
            (run / "work/implementation").write_text("simulation only\n")
        else:
            version = "revision one" if "revision-1" in str(run) else "seed"
            (run / "work/SKILL.md").write_text(
                "---\nname: cli-software\ndescription: Implement CLI contracts.\n---\nInspect public interfaces. "
                + version
                + "\n"
            )
        row = {
            "status": "complete",
            "simulated": True,
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 10,
            },
            "elapsed_seconds": 0.01,
            "api_price_equivalent_usd": 0.0,
        }
        save(run / "run.json", row)
        save(run / "quota.json", [])
        (run / "events.jsonl").write_text(
            json.dumps({"type": "simulation", "message": "no inference"}) + "\n"
        )
        return row

    def grade(self, submission, name, checkpoint, dest):
        # Candidate 1 wins; candidate 2 does not improve. Proves retention/selection wiring.
        passed = 2 if "validation-revision-1" in str(dest) else 1
        report = {
            "infrastructure_failure": False,
            "pytest_collected": 2,
            "pass_counts": {"Core": passed},
            "total_counts": {"Core": 2},
            "tests": {
                f"checkpoint_{checkpoint}-Core": {
                    "passed": ["synthetic"] * passed,
                    "failed": ["synthetic"] * (2 - passed),
                    "skipped": [],
                }
            },
        }
        save(dest / "evaluation.json", report)
        return evaluation_score(report)


class Experiment:
    def __init__(self, backend):
        self.b = backend
        self.cfg = backend.cfg
        self.manifest = backend.manifest
        self.data = backend.data
        self.output = backend.output

    def spec(self, name, n):
        entry = self.manifest["problems"][name]["entry_file"]
        path = REPO / name / f"checkpoint_{n}.md"
        if digest(path) != self.manifest["problems"][name]["spec_sha256"][str(n)]:
            raise RuntimeError("Public specification changed after split recording")
        text = path.read_text()
        text = text.replace("%%%ENTRYPOINT:entry_file%%%", entry).replace(
            "%%%ENTRYPOINT:entry_command%%%", f"{self.b.python} {entry}"
        )
        if "%%%" in text:
            raise RuntimeError("Unsupported public-spec placeholder")
        return text

    def solve_chain(self, stage, name, skill):
        previous = None
        rows = []
        for n in self.manifest["problems"][name]["checkpoints"]:
            run = self.data / stage / name / f"checkpoint_{n}"
            submission = run / "submission"
            expected = hashlib.sha256(skill.encode()).hexdigest()
            if (run / "run.json").exists():
                row = read(run / "run.json")
                record = (
                    read(run / "snapshot.json")
                    if (run / "snapshot.json").exists()
                    else {}
                )
                if (
                    row["status"] not in ["complete", "budget_exhausted"]
                    or record.get("skill_sha256") != expected
                    or not submission.exists()
                    or record.get("files") != hashes(submission)
                ):
                    raise RuntimeError(
                        f"Incomplete or changed checkpoint {run}; no automatic retry"
                    )
                previous = submission
                rows.append({"name": name, "checkpoint": n, "run": run})
                continue
            work = run / "work"
            if work.exists():
                raise RuntimeError("Unrecorded workspace; inspect before retry")
            copy_code(previous, work)
            (work / "SPEC.md").write_text(self.spec(name, n))
            (work / "specs").mkdir()
            for prior in range(1, n):
                (work / f"specs/checkpoint_{prior}.md").write_text(
                    self.spec(name, prior)
                )
            for asset in self.manifest["problems"][name]["assets"]:
                if (work / asset).exists():
                    if (work / asset).is_dir():
                        shutil.rmtree(work / asset)
                    else:
                        (work / asset).unlink()
                shutil.copytree(REPO / name / asset, work / asset)
            entry = self.manifest["problems"][name]["entry_file"]
            instructions = (
                f"Implement the current public SPEC.md in this directory using Python 3.12. Entry file: {entry}. "
                f"Use {self.b.python} for running code. Installed libraries are PyYAML, lxml, cssselect, and tomli-w. "
                "Preserve prior public requirements in specs/ and existing behavior unless the current spec changes it. "
                "Use shell tools to inspect, edit, and check your code against public specifications. "
                "Do not read outside this directory for task information, use the internet, install packages, or seek benchmark tests/solutions. "
                "The designated reusable instructions below are the only skill supplied. Complete the implementation and summarize your own checks."
            )
            self.b.session(
                run,
                instructions,
                "Read SPEC.md, implement the checkpoint, and check it using public information.",
                "solver",
                skill,
            )
            copy_code(work, submission)
            save(
                run / "snapshot.json",
                {"skill_sha256": expected, "files": hashes(submission)},
            )
            previous = submission
            rows.append({"name": name, "checkpoint": n, "run": run})
            print(f"{stage}: {name} checkpoint {n} frozen", flush=True)
        return rows

    def score(self, rows):
        scores = []
        for row in rows:
            scores.append(
                {
                    **self.b.grade(
                        row["run"] / "submission",
                        row["name"],
                        row["checkpoint"],
                        row["run"] / "grading",
                    ),
                    "name": row["name"],
                    "checkpoint": row["checkpoint"],
                }
            )
        return scores

    def writer(self, version, current=None, training=None):
        target = self.output / "skills" / version / "SKILL.md"
        if (target.parent / "revision.json").exists() and read(
            target.parent / "revision.json"
        ).get("rejected"):
            return None
        if target.exists():
            meta = read(target.parent / "revision.json")
            if digest(target) != meta["sha256"]:
                raise RuntimeError("Skill revision modified")
            return skill_valid(target.read_text(), self.cfg)
        run = self.data / "writers" / version
        work = run / "work"
        if work.exists():
            raise RuntimeError("Writer already attempted; no automatic retry")
        work.mkdir(parents=True)
        if training is None:
            # ONLY public training specs/metadata. No existing code_search outcomes.
            inspection = {
                name: {
                    "metadata": self.manifest["problems"][name],
                    "public_specs": {
                        str(n): self.spec(name, n)
                        for n in self.manifest["problems"][name]["checkpoints"]
                    },
                }
                for name in self.cfg["training"]
            }
            save(work / "inspection.json", inspection)
            template = "initial"
        else:
            (work / "CURRENT_SKILL.md").write_text(current)
            feedback = []
            for item in training:
                if item["name"] not in self.cfg["training"]:
                    raise RuntimeError("Non-training feedback blocked")
                runpath = item["run"]
                report = read(runpath / "grading/evaluation.json")
                trace = (runpath / "events.jsonl").read_text()
                errors = runpath / "grading/evaluation/stdout.txt"
                limit = self.cfg["feedback_max_bytes_per_task"]
                feedback.append(
                    {
                        "problem": item["name"],
                        "checkpoint": item["checkpoint"],
                        "public_spec": self.spec(item["name"], item["checkpoint"]),
                        "test_outcomes": report,
                        "trace_excerpt": trace.encode()[-limit:].decode(
                            "utf-8", "ignore"
                        ),
                        "test_output_excerpt": errors.read_bytes()[-limit:].decode(
                            "utf-8", "ignore"
                        )
                        if errors.exists()
                        else "",
                        "trace_truncated": len(trace.encode()) > limit,
                    }
                )
            save(work / "feedback.json", feedback)
            template = "revise"
        instructions = (BASE / f"skills/prompts/{template}.md").read_text()
        self.b.session(
            run,
            instructions,
            "Write the requested SKILL.md using only supplied files.",
            "writer",
        )
        try:
            text = skill_valid((work / "SKILL.md").read_text(), self.cfg)
        except (ValueError, FileNotFoundError) as error:
            if version == "initial":
                raise RuntimeError(
                    "Initial skill writer failed; no automatic retry"
                ) from error
            save(
                target.parent / "revision.json",
                {
                    "rejected": True,
                    "reason": str(error),
                    "writer_run": str(run.relative_to(self.data)),
                },
            )
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        save(
            target.parent / "revision.json",
            {
                "sha256": digest(target),
                "source": "same-model CLI writer",
                "training_only": True,
                "simulated": self.b.simulated,
                "writer_run": str(run.relative_to(self.data)),
            },
        )
        return text

    def learn(self):
        if (self.data / "test").exists():
            raise RuntimeError("Learning is locked after held-out generation begins")
        freeze = self.output / "freeze.json"
        if freeze.exists():
            return self.check_freeze()
        initial = self.writer("initial")
        rows = [
            r
            for name in self.cfg["validation"]
            for r in self.solve_chain("validation-initial", name, initial)
        ]
        scores = self.score(rows)
        best = initial
        best_version = "initial"
        best_score = rank(scores)
        history = [
            {
                "version": "initial",
                "rank": best_score,
                "scores": scores,
                "retained": True,
            }
        ]
        save(self.output / "validation-selection.json", history)
        for n in range(1, self.cfg["learning_rounds"] + 1):
            training = [
                r
                for name in self.cfg["training"]
                for r in self.solve_chain(f"training-{n}", name, best)
            ]
            self.score(training)
            candidate = self.writer(f"revision-{n}", best, training)
            if candidate is None:
                history.append(
                    {"version": f"revision-{n}", "retained": False, "rejected": True}
                )
                save(self.output / "validation-selection.json", history)
                continue
            validation = [
                r
                for name in self.cfg["validation"]
                for r in self.solve_chain(f"validation-revision-{n}", name, candidate)
            ]
            scores = self.score(validation)
            score = rank(scores)
            retained = score > best_score
            history.append(
                {
                    "version": f"revision-{n}",
                    "rank": score,
                    "scores": scores,
                    "retained": retained,
                }
            )
            if retained:
                best = candidate
                best_version = f"revision-{n}"
                best_score = score
            save(self.output / "validation-selection.json", history)
        learned = self.output / "skills/learned/SKILL.md"
        learned.parent.mkdir(parents=True, exist_ok=True)
        learned.write_text(best)
        save(
            freeze,
            {
                "protocol_sha256": self.b.protocol,
                "initial_sha256": hashlib.sha256(initial.encode()).hexdigest(),
                "learned_sha256": digest(learned),
                "selected_revision": best_version,
                "simulated": self.b.simulated,
            },
        )
        return self.check_freeze()

    def check_freeze(self):
        freeze = read(self.output / "freeze.json")
        if (
            freeze["protocol_sha256"] != self.b.protocol
            or freeze["simulated"] != self.b.simulated
        ):
            raise RuntimeError("Freeze belongs to a different protocol or simulation")
        for condition in ["initial", "learned"]:
            path = self.output / f"skills/{condition}/SKILL.md"
            if digest(path) != freeze[f"{condition}_sha256"]:
                raise RuntimeError("Frozen skill changed")
        return freeze

    def evaluate(self):
        self.check_freeze()
        skills = {
            "baseline": "",
            **{
                c: (self.output / f"skills/{c}/SKILL.md").read_text()
                for c in ["initial", "learned"]
            },
        }
        all_rows = []
        orders = {}
        for repeat in range(self.cfg["test_repeats"]):
            for name in self.cfg["test"]:
                order = CONDITIONS.copy()
                random.Random(f"{self.cfg['seed']}:{repeat}:{name}").shuffle(order)
                orders[f"{repeat}/{name}"] = order
                for condition in order:
                    self.check_freeze()
                    stage = f"test/repeat-{repeat}/{condition}"
                    rows = self.solve_chain(stage, name, skills[condition])
                    all_rows.extend(
                        [{**r, "condition": condition, "repeat": repeat} for r in rows]
                    )
        save(self.output / "test-order.json", orders)
        # No test grading occurs until EVERY condition's implementations are frozen.
        scored = []
        for row in all_rows:
            scored.append(
                {
                    **self.score([row])[0],
                    "condition": row["condition"],
                    "repeat": row["repeat"],
                }
            )
            dest = (
                self.output
                / f"checkpoints/repeat-{row['repeat']}/{row['condition']}/{row['name']}/checkpoint_{row['checkpoint']}"
            )
            if not (dest / "submission").exists():
                copy_code(row["run"] / "submission", dest / "submission")
            if hashes(dest / "submission") != hashes(row["run"] / "submission"):
                raise RuntimeError("Published snapshot mismatch")
            for filename in ["run.json", "quota.json", "snapshot.json"]:
                shutil.copy2(row["run"] / filename, dest / filename)
            shutil.copy2(
                row["run"] / "grading/evaluation.json", dest / "evaluation.json"
            )
        save(self.output / "paired-results.json", scored)
        self.summarize(scored)

    def summarize(self, scored):
        summary = {"simulated": self.b.simulated, "conditions": {}, "paired": []}
        for condition in CONDITIONS:
            rows = [r for r in scored if r["condition"] == condition]
            sessions = [
                read(p)
                for p in session_paths(self.data)
                if p.relative_to(self.data).parts[0] == "test"
                and p.relative_to(self.data).parts[2] == condition
            ]
            known = all(r.get("usage") is not None for r in sessions)
            cost = (
                sum(r.get("api_price_equivalent_usd") or 0 for r in sessions)
                if known
                else None
            )
            wins = sum(r["strict"] for r in rows)
            summary["conditions"][condition] = {
                "strict_passes": wins,
                "checkpoints": len(rows),
                "elapsed_seconds": sum(r["elapsed_seconds"] for r in sessions),
                "tokens": {
                    key: sum(r["usage"].get(key, 0) for r in sessions)
                    for key in ["input_tokens", "cached_input_tokens", "output_tokens"]
                }
                if known
                else None,
                "api_price_equivalent_usd": cost,
                "api_equivalent_per_successful_checkpoint": cost / wins
                if wins and cost is not None
                else None,
            }
        learning = [
            read(p)
            for p in session_paths(self.data)
            if "test" not in p.relative_to(self.data).parts
        ]
        summary["learning_api_price_equivalent_usd"] = (
            sum(r.get("api_price_equivalent_usd") or 0 for r in learning)
            if all(r.get("usage") is not None for r in learning)
            else None
        )
        summary["learning_elapsed_seconds"] = sum(
            r["elapsed_seconds"] for r in learning
        )
        summary["learning_tokens"] = (
            {
                key: sum(r["usage"].get(key, 0) for r in learning)
                for key in ["input_tokens", "cached_input_tokens", "output_tokens"]
            }
            if all(r.get("usage") is not None for r in learning)
            else None
        )
        for condition, stats in summary["conditions"].items():
            complete = sum(
                all(
                    r["strict"]
                    for r in scored
                    if r["condition"] == condition
                    and r["name"] == name
                    and r["repeat"] == repeat
                )
                for repeat in range(self.cfg["test_repeats"])
                for name in self.cfg["test"]
            )
            stats["fully_passed_problem_chains"] = complete
            stats["problem_chains"] = len(self.cfg["test"]) * self.cfg["test_repeats"]
            stats["api_equivalent_per_successful_problem_chain"] = (
                stats["api_price_equivalent_usd"] / complete
                if complete and stats["api_price_equivalent_usd"] is not None
                else None
            )
        summary["stronger_assistant_setup_cost_usd"] = None
        summary["setup_cost_note"] = (
            "Harness preparation usage is not separately metered; shared account quota includes it."
        )
        for repeat in range(self.cfg["test_repeats"]):
            for name in self.cfg["test"]:
                for n in self.manifest["problems"][name]["checkpoints"]:
                    cells = {
                        r["condition"]: r["strict"]
                        for r in scored
                        if r["name"] == name
                        and r["checkpoint"] == n
                        and r["repeat"] == repeat
                    }
                    summary["paired"].append(
                        {
                            "problem": name,
                            "checkpoint": n,
                            "repeat": repeat,
                            "success": cells,
                            "learned_vs_baseline": cells["learned"] - cells["baseline"],
                            "learned_vs_initial": cells["learned"] - cells["initial"],
                        }
                    )
        summary["break_even_future_tasks"] = None
        summary["break_even_note"] = (
            "Not estimated: four dependent problem chains, one repeat, and preliminary checkpoint-level evidence do not establish stable future-task success/cost rates."
        )
        summary["actual_subscription_cash_cost_usd"] = None
        save(self.output / "summary.json", summary)
        lines = [
            "# SCB skill-learning pilot",
            "",
            "SIMULATION ONLY — no model calls or benchmark measurements."
            if self.b.simulated
            else "Same-model Luna skill learning; preliminary paired evaluation on four held-out problem chains.",
            "",
            "| Condition | Strict checkpoints passed | API-equivalent USD |",
            "|---|---:|---:|",
        ]
        for name, row in summary["conditions"].items():
            lines.append(
                f"| {name} | {row['strict_passes']}/{row['checkpoints']} | {row['api_price_equivalent_usd']} |"
            )
        lines += [
            "",
            f"Total learning API-equivalent USD: {summary['learning_api_price_equivalent_usd']}. Actual subscription cash cost is unavailable.",
            "",
            summary["break_even_note"],
            "",
            "See summary.json for tokens, elapsed time, cost per successful checkpoint, and paired improvements/regressions. Checkpoints are dependent, not independent samples.",
        ]
        (self.output / "RESULTS.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["prepare", "plan", "smoke", "audit", "learn", "evaluate"]
    )
    args = parser.parse_args(argv)
    cfg, manifest = preflight(write=args.action == "prepare")
    if args.action in ["prepare", "plan"]:
        print(json.dumps(plan(cfg, manifest), indent=2))
        return
    if args.action == "smoke":
        with tempfile.TemporaryDirectory(
            prefix="kojo-gauntlet-", dir=BASE / "intermediate"
        ) as tmp:
            backend = SimulatedBackend(
                cfg, manifest, Path(tmp) / "runs", Path(tmp) / "results"
            )
            experiment = Experiment(backend)
            experiment.learn()
            experiment.evaluate()
            calls = len(list(session_paths(backend.data)))
            if calls != cfg["max_sessions"]:
                raise RuntimeError("Simulation session count mismatch")
            print(
                f"SIMULATION: {calls} sessions, all phases complete, selected "
                + read(backend.output / "freeze.json")["selected_revision"]
                + "; zero model calls"
            )
        return
    if args.action == "audit":
        root = DATA / "offline-audit"
        audit(
            root / "solver",
            "Follow SPEC.md. Use only your working files.",
            BASE / cfg["runtime"],
            "---\nname: cli-software\ndescription: Offline audit skill.\n---\nAudit canary: designated instructions.\n",
        )
        audit(root / "writer", (BASE / "skills/prompts/revise.md").read_text())
        print(
            "Exact-request, runtime, skill, and private-file isolation checks passed; zero model calls"
        )
        return
    backend = Backend(cfg, manifest)
    backend.authorize()
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "execution.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        save(DATA / "protocol.json", {"sha256": backend.protocol, "manifest": manifest})
        experiment = Experiment(backend)
        try:
            if args.action == "learn":
                experiment.learn()
            else:
                experiment.evaluate()
        except BaseException as error:
            save(
                OUTPUT / "STOPPED.json",
                {"phase": args.action, "reason": str(error), "time": time.time()},
            )
            raise
        finally:
            sessions = [
                {"path": str(p.parent.relative_to(DATA)), **read(p)}
                for p in session_paths(DATA)
            ]
            save(
                OUTPUT / "accounting.json",
                {
                    "sessions": sessions,
                    "sessions_reserved": len(read(DATA / "ledger.json"))
                    if (DATA / "ledger.json").exists()
                    else 0,
                    "known_api_equivalent_usd": sum(
                        r.get("api_price_equivalent_usd") or 0 for r in sessions
                    ),
                    "unmetered_sessions": sum(r.get("usage") is None for r in sessions),
                    "actual_subscription_cash_cost_usd": None,
                },
            )


if __name__ == "__main__":
    main()
