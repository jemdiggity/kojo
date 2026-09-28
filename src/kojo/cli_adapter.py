"""One SCB checkpoint; CLI generation separated from upstream pytest grading."""

import http.server
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parents[1]
CHECKPOINT = int(os.environ.get("SCB_CHECKPOINT", "2"))
assert 2 <= CHECKPOINT <= 5
RUN = BASE / f"intermediate/scb-sequence/checkpoint_{CHECKPOINT}"
WORK = RUN / "work"
REPO = BASE / "intermediate/vendor/scb-problems"
COMMIT = "38d627ecf668a88f88f8d260f8df8df6116e9b03"
from kojo.codex import Metadata, enforce, overrides


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def setup():
    assert (
        subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
        ).strip()
        == COMMIT
    )
    assert (
        subprocess.check_output(["codex", "--version"], text=True).strip()
        == "codex-cli 0.157.1"
    )
    assert sys.version.split()[0] == "3.12.8"
    WORK.mkdir(parents=True, exist_ok=True)
    spec = (REPO / f"code_search/checkpoint_{CHECKPOINT}.md").read_text()
    spec = spec.replace("%%%ENTRYPOINT:entry_file%%%", "code_search").replace(
        "%%%ENTRYPOINT:entry_command%%%", "./code_search"
    )
    (WORK / "SPEC.md").write_text(spec)
    (WORK / "instructions.md").write_text(
        "Extend the existing implementation to satisfy SPEC.md in this working directory. "
        "Preserve the behavior required by previous public specifications in specs/. "
        "Use Python 3.12 and its standard library. Create an executable ./code_search. "
        "You may use the shell to write files and test your implementation against the public specification. "
        "Do not search the internet or read outside this working directory for task information. "
        "Benchmark tests and reference solutions are withheld. Do not attempt to access them. "
        "No reusable skill instructions are supplied. Complete the implementation and briefly report your own checks.\n"
    )
    args = overrides(ignore_user_config=True)
    args += [
        "-c",
        "features.shell_tool=true",
        "-c",
        "features.unified_exec=true",
        "-c",
        "features.code_mode_host=true",
        "-c",
        "model_instructions_file=" + json.dumps(str(WORK / "instructions.md")),
    ]
    args += permission_args()
    return [
        "codex",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        *args,
        "-C",
        str(WORK),
        "-o",
        str(RUN / "answer.txt"),
        "-",
    ]


def permission_args():
    return [
        "-c",
        'default_permissions="scb"',
        "-c",
        'permissions.scb.extends=":workspace"',
        "-c",
        "permissions.scb.filesystem={"
        + json.dumps(str(BASE))
        + '="deny",'
        + json.dumps(str(WORK))
        + '="write"}',
    ]


def audit():
    command = setup()
    q = queue.Queue()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            q.put(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                b'{"error":{"message":"OFFLINE AUDIT: no inference","type":"invalid_request_error"}}'
            )

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    extra = [
        "-c",
        'model_provider="audit"',
        "-c",
        'model_providers.audit.name="Offline"',
        "-c",
        "model_providers.audit.base_url="
        + json.dumps(f"http://127.0.0.1:{server.server_port}/v1"),
        "-c",
        'model_providers.audit.wire_api="responses"',
        "-c",
        "model_providers.audit.requires_openai_auth=false",
        "-c",
        "model_catalog_json="
        + json.dumps(str(Path.home() / ".codex/models_cache.json")),
        "-c",
        "features.enable_request_compression=false",
    ]
    with (RUN / "audit-stderr.log").open("w") as err:
        p = subprocess.Popen(
            command[:-1] + extra + ["-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=err,
            text=True,
        )
        p.stdin.write("Read SPEC.md and implement it.")
        p.stdin.close()
        try:
            payload = q.get(timeout=30)
            text = json.dumps(payload)
            assert (
                "Available skills" not in text
                and "/.agents/skills/" not in text
                and "/.codex/skills/" not in text
            )
            catalog = payload.get("tools", []) + [
                t
                for item in payload.get("input", [])
                if item.get("type") == "additional_tools"
                for t in item.get("tools", [])
            ]
            tools = [x.get("name") or x.get("type") for x in catalog]
            save(RUN / "audit-request.json", payload)
            assert "exec_command" in json.dumps(
                catalog
            ) or "shell_command" in json.dumps(catalog)
            sandbox = [
                "codex",
                "sandbox",
                *permission_args(),
                "-P",
                "scb",
                "-C",
                str(WORK),
            ]
            public = subprocess.run(
                sandbox + ["/bin/cat", "SPEC.md"], capture_output=True
            )
            assert public.returncode == 0 and public.stdout, public.stderr
            write = subprocess.run(
                sandbox + ["/bin/sh", "-c", "echo ok > .probe"], capture_output=True
            )
            assert write.returncode == 0, write.stderr
            (WORK / ".probe").unlink()
            canary = subprocess.run(
                sandbox + ["/bin/cat", str(REPO / "code_search/config.yaml")],
                capture_output=True,
            )
            assert canary.returncode != 0 and not canary.stdout
            save(
                RUN / "verification.json",
                {
                    "inference_calls": 0,
                    "skill_catalog_present": False,
                    "tools": tools,
                    "private_repository_read_blocked": True,
                },
            )
            print(
                "Offline exact-request and filesystem isolation checks passed:", tools
            )
        finally:
            p.terminate()
            p.wait(timeout=5)
            server.shutdown()


def run():
    assert not (RUN / "run.json").exists(), "One attempt only; never silently retry."
    assert json.loads((RUN / "verification.json").read_text())[
        "private_repository_read_blocked"
    ]
    command = setup()
    cfg = json.loads((BASE / "configs/quota.json").read_text())
    meta = Metadata()
    observations = []
    p = None
    start = time.monotonic()
    row = {
        "model": "gpt-6-luna",
        "reasoning": "low",
        "condition": "baseline",
        "status": "started",
        "checkpoint": f"code_search/checkpoint_{CHECKPOINT}",
        "commit": COMMIT,
        "max_seconds": 300,
    }
    try:
        before = meta.usage()
        observations.append(before)
        enforce(before, cfg, observations, True)
        row["skills_audit"] = meta.audit_skills(WORK)
        save(RUN / "run.json", row)
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in [
                "OPENAI_API_KEY",
                "CODEX_API_KEY",
                "OPENAI_BASE_URL",
                "OPENAI_ORG_ID",
                "OPENAI_PROJECT_ID",
            ]
        }
        with (
            (RUN / "events.jsonl").open("w") as out,
            (RUN / "stderr.log").open("w") as err,
        ):
            p = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=out,
                stderr=err,
                text=True,
                env=env,
                start_new_session=True,
            )
            p.stdin.write(
                "Read SPEC.md and implement the complete checkpoint. Test your implementation using the public specification."
            )
            p.stdin.close()
            while p.poll() is None:
                try:
                    p.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    snapshot = meta.usage()
                    observations.append(snapshot)
                    save(RUN / "usage.json", observations)
                    enforce(snapshot, cfg, observations, True)
                    if time.monotonic() - start >= 300:
                        raise RuntimeError("Five-minute session budget reached")
        row["returncode"] = p.returncode
        row["status"] = (
            "complete"
            if p.returncode == 0 and (WORK / "code_search").is_file()
            else "failed"
        )
    except BaseException as error:
        row["status"] = "interrupted"
        row["reason"] = str(error)
        if p and p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        raise
    finally:
        row["elapsed_seconds"] = time.monotonic() - start
        try:
            observations.append(meta.usage())
        finally:
            meta.close()
        save(RUN / "usage.json", observations)
        events = []
        if (RUN / "events.jsonl").exists():
            for line in (RUN / "events.jsonl").read_text().splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        turns = [x for x in events if x.get("type") == "turn.completed"]
        row["usage"] = turns[-1]["usage"] if turns else None
        save(RUN / "run.json", row)
        print(json.dumps(row, indent=2))


if __name__ == "__main__":
    {"audit": audit, "run": run}[sys.argv[1]]()
