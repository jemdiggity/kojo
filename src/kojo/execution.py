"""Fresh Codex CLI sessions with explicit instructions and native filesystem isolation."""

import hashlib
import http.server
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import tempfile
import time

from kojo.catalog import BASE
from kojo.codex import Metadata, enforce, overrides


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def session_paths(root):
    """Only controller-owned receipts; never count agent-authored files in work/submission."""
    for path in sorted(root.rglob("run.json")):
        parts = path.relative_to(root).parts
        if len(parts) == 3 and parts[0] == "writers":
            yield path
        elif (
            len(parts) == 4
            and parts[0].startswith(("training-", "validation-"))
            and parts[2].startswith("checkpoint_")
        ):
            yield path
        elif (
            len(parts) == 6
            and parts[0] == "test"
            and parts[1].startswith("repeat-")
            and parts[2] in ("baseline", "initial", "learned")
            and parts[4].startswith("checkpoint_")
        ):
            yield path


def permission_args(work, runtime=None, readonly_skill=False, isolated_src=False):
    paths = {str(BASE): "deny", str(work): "write"}
    if isolated_src:
        paths.update({":root": "deny", ":minimal": "read", ":tmpdir": "deny", ":slash_tmp": "deny"})
        paths[str(Path(sys._base_executable).resolve().parents[1])] = "read"
    if runtime:
        paths[str(runtime)] = "read"
    if readonly_skill:
        paths[str(work / "SKILL.md")] = "read"
    value = (
        "{"
        + ",".join(json.dumps(k) + "=" + json.dumps(v) for k, v in paths.items())
        + "}"
    )
    return [
        "-c",
        'default_permissions="scb"',
        "-c",
        'permissions.scb.extends=":workspace"',
        "-c",
        "permissions.scb.filesystem=" + value,
    ]


def command(run, instructions, runtime=None, skill=None, isolated_src=False, persist=False):
    work = run / ("src" if isolated_src else "work")
    work.mkdir(parents=True, exist_ok=True)
    if skill is not None:
        if not isolated_src:
            (work / "SKILL.md").write_text(skill)
        instructions += "\n\n# Designated reusable instructions\n" + skill
    instruction_path = (run if isolated_src else work) / "instructions.md"
    instruction_path.write_text(instructions)
    args = overrides(ignore_user_config=True)
    args += [
        "-c",
        "features.shell_tool=true",
        "-c",
        "features.unified_exec=true",
        "-c",
        "features.code_mode_host=true",
        "-c",
        "model_instructions_file=" + json.dumps(str(instruction_path)),
    ]
    args += permission_args(work, runtime, skill is not None and not isolated_src, isolated_src)
    if isolated_src:
        args += ["-c", "permissions.scb.network.enabled=false", "-c",
                 "shell_environment_policy.set=" + "{" + ",".join(json.dumps(k)+"="+json.dumps(v) for k,v in {"TMPDIR":str(work), "TMP":str(work), "TEMP":str(work), "PYTHONDONTWRITEBYTECODE":"1"}.items()) + "}"]
    return [
        "codex",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        *([] if persist else ["--ephemeral"]),
        "--skip-git-repo-check",
        "--json",
        *args,
        "-C",
        str(work),
        "-o",
        str(run / "answer.txt"),
        "-",
    ]


def audit(run, instructions, runtime=None, skill=None, isolated_src=False, prompt=None, persist=False):
    cmd = command(run, instructions, runtime, skill, isolated_src, persist)
    received = queue.Queue()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.put(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                b'{"error":{"message":"Offline audit, no inference","type":"invalid_request_error"}}'
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
    process = None
    try:
        with (run / "audit-stderr.log").open("w") as err, (run / "audit-events.jsonl").open("w") as audit_out:
            process = subprocess.Popen(
                cmd[:-1] + extra + ["-"],
                stdin=subprocess.PIPE,
                stdout=audit_out,
                stderr=err,
                text=True,
            )
            process.stdin.write(prompt or "Inspect the supplied working files.")
            process.stdin.close()
            payload = received.get(timeout=30)
            save(run / "audit-request.json", payload)
            serialized = json.dumps(payload)
            if any(
                x in serialized
                for x in ["Available skills", "/.agents/skills/", "/.codex/skills/"]
            ):
                raise RuntimeError("Ambient skill catalog present")
            if skill and json.dumps(skill.strip())[1:-1] not in serialized:
                raise RuntimeError("Designated skill missing from exact model request")
            catalog = payload.get("tools", []) + [
                t
                for item in payload.get("input", [])
                if item.get("type") == "additional_tools"
                for t in item.get("tools", [])
            ]
            if "exec_command" not in json.dumps(catalog):
                raise RuntimeError("Shell tool absent")
            work = run / ("src" if isolated_src else "work")
            sandbox = [
                "codex",
                "sandbox",
                *permission_args(work, runtime, skill is not None and not isolated_src, isolated_src),
                "-P",
                "scb",
                "-C",
                str(work),
            ]
            probe = work / ".audit-public"
            probe.write_text("public probe")
            public = subprocess.run(
                sandbox + ["/bin/cat", str(probe)], capture_output=True
            )
            probe.unlink()
            if public.returncode or not public.stdout:
                raise RuntimeError("Working-directory read failed")
            write = subprocess.run(
                sandbox + ["/bin/sh", "-c", "echo ok > .probe"], capture_output=True
            )
            if write.returncode:
                raise RuntimeError("Working-directory write failed")
            (work / ".probe").unlink()
            canary = subprocess.run(
                sandbox + ["/bin/cat", str(BASE / "configs/gauntlet.json")],
                capture_output=True,
            )
            if canary.returncode == 0 or canary.stdout:
                raise RuntimeError("Private experiment files readable")
            if runtime:
                check = subprocess.run(
                    sandbox
                    + [
                        str(Path(sys._base_executable).resolve()),
                        "-c",
                        "import yaml,lxml,cssselect,tomli_w",
                    ],
                    capture_output=True,
                    env={
                        **os.environ,
                        "PYTHONPATH": str(runtime / "lib/python3.12/site-packages"),
                    },
                )
                if check.returncode:
                    raise RuntimeError(
                        "Pinned runtime not accessible inside sandbox: "
                        + check.stderr.decode()[-1000:]
                    )
            if skill is not None and not isolated_src:
                changed = subprocess.run(
                    sandbox + ["/bin/sh", "-c", "echo changed >> SKILL.md"],
                    capture_output=True,
                )
                if changed.returncode == 0:
                    raise RuntimeError("Solver can modify designated skill artifact")
            if isolated_src:
                # Check representative private paths without returning file contents.
                blocked = [BASE / "README.md", BASE / "results/runs/20260927-code-search-baseline-01/checkpoints/checkpoint_5/submission/code_search", Path.home() / ".codex/config.toml", run / "instructions.md"]
                for path in blocked:
                    check = subprocess.run(sandbox + [str(Path(sys._base_executable).resolve()), "-c", "from pathlib import Path; Path(" + repr(str(path)) + ").open().read(1)"], capture_output=True)
                    if check.returncode == 0:
                        raise RuntimeError("Private read allowed: " + str(path))
                with tempfile.NamedTemporaryFile(prefix="kojo-private-canary-", dir="/private/tmp") as private:
                    private.write(b"private canary"); private.flush()
                    check = subprocess.run(sandbox + ["/bin/cat", private.name], capture_output=True)
                    if check.returncode == 0:
                        raise RuntimeError("Global temporary files readable")
                network = subprocess.run(sandbox + [str(Path(sys._base_executable).resolve()), "-c", "import socket; socket.create_connection(('127.0.0.1', " + str(server.server_port) + "), timeout=1)"], capture_output=True)
                if network.returncode == 0:
                    raise RuntimeError("Tool network access allowed")
                link = work / ".audit-link"
                link.symlink_to(BASE / "README.md")
                try:
                    check = subprocess.run(sandbox + ["/bin/cat", str(link)], capture_output=True)
                    if check.returncode == 0:
                        raise RuntimeError("Symlink escaped src")
                finally:
                    link.unlink()
                if prompt and prompt not in json.dumps(payload, ensure_ascii=False) and not any(prompt == item.get("text") for msg in payload.get("input", []) for item in msg.get("content", []) if isinstance(item, dict)):
                    raise RuntimeError("Exact task prompt missing from audited request")
            save(run / "audit-request.json", payload)
            save(
                run / "verification.json",
                {
                    "inference_calls": 0,
                    "ambient_skills": False,
                    "private_files_blocked": True,
                    "isolated_src": isolated_src,
                    "designated_skill_sha256": hashlib.sha256(
                        (skill or "").encode()
                    ).hexdigest(),
                },
            )
    finally:
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        server.shutdown()
        server.server_close()
    if persist:
        from kojo.transcripts import capture
        instruction_path = (run if isolated_src else run / 'work') / 'instructions.md'
        capture(run, instruction_path.read_text(), prompt or 'Inspect the supplied working files.', skill or '', audit=True)


def usage_from_events(path):
    events = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    turns = [e for e in events if e.get("type") == "turn.completed"]
    return turns[-1]["usage"] if turns else None


def cost(usage):
    if usage is None:
        return None
    return (
        (usage["input_tokens"] - usage.get("cached_input_tokens", 0)) * 0.10
        + usage.get("cached_input_tokens", 0) * 0.01
        + usage["output_tokens"] * 0.50
    ) / 1e6


def run_session(
    run, instructions, prompt, seconds, runtime=None, skill=None, prior_observations=(), isolated_src=False, capture_transcript=True
):
    if (run / "run.json").exists():
        raise RuntimeError("Attempt already exists; refusing automatic retry")
    audit(run, instructions, runtime, skill, isolated_src, prompt)
    cmd = command(run, instructions, runtime, skill, isolated_src, persist=capture_transcript)
    cfg = json.loads((BASE / "configs/quota.json").read_text())
    observations = []
    process = None
    meta = None
    started = time.monotonic()
    row = {
        "status": "started",
        "model": "gpt-6-luna",
        "reasoning": "low",
        "max_seconds": seconds,
        "fresh_conversation": True,
        "skill_sha256": hashlib.sha256((skill or "").encode()).hexdigest(),
    }
    save(run / "run.json", row)
    try:
        meta = Metadata()
        observations.append(meta.usage())
        enforce(observations[-1], cfg, [*prior_observations, *observations], True)
        row["skills_audit"] = meta.audit_skills(run / ("src" if isolated_src else "work"))
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
        if runtime:
            env["PYTHONPATH"] = str(runtime / "lib/python3.12/site-packages")
        with (
            (run / "events.jsonl").open("w") as out,
            (run / "stderr.log").open("w") as err,
        ):
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=out,
                stderr=err,
                text=True,
                env=env,
                start_new_session=True,
            )
            process.stdin.write(prompt)
            process.stdin.close()
            deadline = time.monotonic() + seconds
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    row["status"] = "budget_exhausted"
                    break
                try:
                    process.wait(timeout=min(15, remaining))
                except subprocess.TimeoutExpired:
                    observations.append(meta.usage())
                    save(run / "quota.json", observations)
                    enforce(
                        observations[-1],
                        cfg,
                        [*prior_observations, *observations],
                        True,
                    )
            if row["status"] == "started":
                row["status"] = "complete" if process.returncode == 0 else "cli_failure"
            row["returncode"] = process.returncode
    except BaseException as error:
        row["status"] = "interrupted"
        row["reason"] = str(error)
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise
    finally:
        row["elapsed_seconds"] = time.monotonic() - started
        row["usage"] = usage_from_events(run / "events.jsonl")
        row["api_price_equivalent_usd"] = cost(row["usage"])
        save(run / "run.json", row)
        if meta:
            try:
                observations.append(meta.usage())
            finally:
                meta.close()
                save(run / "quota.json", observations)
        else:
            save(run / "quota.json", observations)
        if capture_transcript and process is not None:
            from kojo.transcripts import capture
            instruction_path = (run if isolated_src else run / 'work') / 'instructions.md'
            try:
                row['transcript'] = capture(run, instruction_path.read_text(), prompt, skill or '')
            except Exception as error:
                row['transcript_error'] = str(error)
            save(run / 'run.json', row)
    if row.get('transcript_error'):
        raise RuntimeError('Transcript capture failed; stop before another model call: ' + row['transcript_error'])
    if row["status"] == "cli_failure":
        raise RuntimeError("CLI infrastructure failure; inspect before resuming")
    return row
