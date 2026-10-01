"""Fresh Codex CLI sessions with explicit instructions and native filesystem isolation."""

import hashlib
import http.server
import json
import os
from pathlib import Path
import queue
import re
import shlex
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


def permission_args(work, runtime=None, readonly_skill=False, isolated_src=False, network_enabled=False):
    paths = {str(BASE): "deny", str(work): "write"}
    if isolated_src:
        paths.update({":root": "deny", ":minimal": "read", ":tmpdir": "deny", ":slash_tmp": "deny"})
        paths[str(Path(sys._base_executable).resolve().parents[1])] = "read"
    for directory in [work / ".agents", work / ".claude"]:
        if directory.exists(): paths[str(directory)] = "read"
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
        '-c',
        'permissions.scb.network.enabled=' + str(network_enabled).lower(),
        "-c",
        "permissions.scb.filesystem=" + value,
    ]


def node_compile_cache():
    """One warm compile cache for every Node process the harness starts, outside any workspace.
    Node would otherwise put it under TMPDIR, which sessions point at their workspace, and a fresh
    workspace never has a warm cache anyway. Node writes entries atomically, so sessions can share it."""
    # Node creates the directory itself and treats an unusable one as "no cache", never as an error.
    return str(Path(os.environ.get("KOJO_NODE_COMPILE_CACHE", str(Path.home() / "Library/Caches/kojo/node-compile-cache"))).expanduser())


def shell_environment(work, runtime=None):
    """Tool-only overrides; do not change the controller's :tmpdir resolution."""
    env = {
        "TMPDIR": str(work), "TMP": str(work), "TEMP": str(work),
        # zsh uses TMPPREFIX for heredocs independently of TMPDIR.
        "TMPPREFIX": str(work / ".kojo-zsh"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "NODE_COMPILE_CACHE": node_compile_cache(),
    }
    if runtime:
        # Bare `python`/`python3` must be the pinned 3.12 runtime, not the machine's (on macOS,
        # the Xcode 3.9 stub). Tool shells run non-login (allow_login_shell=false in command())
        # because /etc/zprofile's path_helper would move this entry behind /usr/bin.
        env["PATH"] = f"{Path(runtime) / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(runtime)
    return env


def audit_shell_writes(sandbox, work, runtime=None):
    """Exercise actual zsh writes under the native sandbox, without inference."""
    with tempfile.TemporaryDirectory(prefix=".audit-shell-", dir=work) as directory:
        probe = Path(directory)
        program = (
            "import os, pathlib, tempfile\n"
            "root = pathlib.Path(os.environ['TMPDIR']).resolve()\n"
            "with tempfile.TemporaryFile() as f:\n"
            "    f.write(b'hello'); f.seek(0); assert f.read() == b'hello'\n"
            "with tempfile.NamedTemporaryFile() as f:\n"
            "    assert pathlib.Path(f.name).resolve().is_relative_to(root)\n"
            "assert pathlib.Path('fixtures/nested/value.txt').read_text() == 'fixture\\n'\n"
            "print('shell-write-smoke-ok')\n"
        )
        script = (
            "set -eu\ncd " + shlex.quote(str(probe)) + "\n"
            "mkdir -p fixtures/nested\ncat > fixtures/nested/value.txt <<'KOJO_FIXTURE'\n"
            "fixture\nKOJO_FIXTURE\ncat > probe.py <<'KOJO_PROGRAM'\n"
            + program + "KOJO_PROGRAM\n"
            + shlex.quote(str(Path(sys._base_executable).resolve())) + " -m py_compile probe.py\n"
            + shlex.quote(str(Path(sys._base_executable).resolve())) + " probe.py\n"
        )
        # Apply overrides after Codex resolves :tmpdir from its parent environment,
        # exactly as shell_environment_policy.set applies to a tool subprocess.
        result = subprocess.run(
            sandbox + ["/usr/bin/env", *[f"{k}={v}" for k, v in shell_environment(work, runtime).items()],
                       "/bin/zsh", "-c", script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode or result.stdout.strip() != "shell-write-smoke-ok" or result.stderr:
            raise RuntimeError("Native shell write smoke failed: " + result.stderr[-2000:])
        if (probe / "probe.py").read_text() != program:
            raise RuntimeError("Heredoc content was corrupted")


def command(run, instructions, runtime=None, skill=None, isolated_src=False, persist=False, model="gpt-6-luna", work_path=None, network_enabled=False, effort="low", native_skill_set=None):
    from kojo.skill_sets import active_source
    native_skill_set = active_source(native_skill_set)
    run.mkdir(parents=True, exist_ok=True)
    if model not in ("gpt-6-luna", "gpt-6-astra", "gpt-5.6-sol", "gpt-6-sol", "gpt-6.1-sol"):
        raise ValueError("Unsupported experiment model")
    work = Path(work_path) if work_path is not None else run / ("src" if isolated_src else "work")
    work.mkdir(parents=True, exist_ok=True)
    if instructions is None and skill is not None:
        raise ValueError("Stock mode accepts guidance in task messages, not a base-prompt override")
    if skill is not None:
        if not isolated_src:
            (work / "SKILL.md").write_text(skill)
        instructions += "\n\n# Designated reusable instructions\n" + skill
    instruction_path = (run if isolated_src else work) / "instructions.md"
    if instructions is not None:
        instruction_path.write_text(instructions)
    from kojo.skill_sets import install
    native = install(work, native_skill_set, 'codex')
    args = overrides(ignore_user_config=True, native_work=work if native else None)
    if effort not in ("low", "medium", "high", "xhigh", "max"):
        raise ValueError("Unsupported Codex effort")
    args += ["-c", "model=" + json.dumps(model), "-c", "model_reasoning_effort=" + json.dumps(effort)]
    catalog = run / 'model-catalog.json'
    if catalog.exists():
        args += ['-c', 'model_catalog_json=' + json.dumps(str(catalog.resolve()))]
    args += [
        "-c",
        "features.shell_tool=true",
        "-c",
        "features.unified_exec=true",
        "-c",
        "features.code_mode_host=true",
        # Non-login tool shells keep the PATH set by shell_environment().
        "-c",
        "allow_login_shell=false",
    ]
    if instructions is not None:
        args += ["-c", "model_instructions_file=" + json.dumps(str(instruction_path))]
    args += permission_args(work, runtime, skill is not None and not isolated_src, isolated_src, network_enabled)
    if isolated_src:
        args += ["-c",
                 "shell_environment_policy.set=" + "{" + ",".join(json.dumps(k)+"="+json.dumps(v) for k,v in shell_environment(work, runtime).items()) + "}"]
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


def freeze_model_catalog(run, model):
    """Bind audit and inference to one current catalog, not a shared CLI cache."""
    path = run / 'model-catalog.json'
    if path.exists():
        catalog = json.loads(path.read_text())
    else:
        result = subprocess.run(
            ['codex', *overrides(ignore_user_config=True), '-c', 'model_provider="openai"',
             'debug', 'models'], check=True, capture_output=True, text=True, timeout=30)
        catalog = json.loads(result.stdout)
    entries = [entry for entry in catalog.get('models', []) if entry.get('slug') == model]
    if len(entries) != 1 or not entries[0].get('base_instructions', '').strip():
        raise RuntimeError(f'Model catalog lacks stock instructions for {model}; refusing fallback metadata')
    if not path.exists():
        save(path, catalog)
    return path


def audit(run, instructions, runtime=None, skill=None, isolated_src=False, prompt=None, persist=False, model="gpt-6-luna", work_path=None, network_enabled=False, effort="low", native_skill_set=None):
    from kojo.skill_sets import active_source
    native_skill_set = active_source(native_skill_set)
    run.mkdir(parents=True, exist_ok=True)
    freeze_model_catalog(run, model)
    cmd = command(run, instructions, runtime, skill, isolated_src, persist, model, work_path, network_enabled, effort, native_skill_set)
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
            if payload.get("model") != model:
                raise RuntimeError("Requested model missing from audited request")
            if payload.get("reasoning", {}).get("effort") != effort:
                raise RuntimeError("Requested effort missing from audited request")
            serialized = json.dumps(payload)
            # Stock instructions explain skills generically; that is not a catalog.
            texts = [c.get("text", "") for m in payload.get("input", [])
                     for c in m.get("content", []) if isinstance(c, dict)]
            if native_skill_set is None and (any(x in serialized for x in ["/.agents/skills/", "/.codex/skills/"]) or any(
                re.search(r"(?m)^### Available skills\s*$", t) for t in texts
            )):
                raise RuntimeError("Ambient skill catalog present")
            if native_skill_set:
                from kojo.skill_sets import install
                native = install(Path(work_path) if work_path else run/'src', native_skill_set, 'codex')
                for entry in native['skills']:
                    expected_path = str(Path(native['installed_root'])/entry['name']/'SKILL.md')
                    alias = re.search(r"- `(r\d+)` = `" + re.escape(native['installed_root']) + r"`", '\n'.join(texts))
                    if expected_path not in serialized and not (alias and f"(file: {alias[1]}/{entry['name']}/SKILL.md)" in serialized):
                        raise RuntimeError('Designated native skill missing from request')
                meta = Metadata(native_work=Path(work_path) if work_path else run/'src')
                try:
                    meta.audit_skills(Path(work_path) if work_path else run/'src',
                        [str(Path(native['installed_root'])/e['name']/'SKILL.md') for e in native['skills']])
                finally: meta.close()
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
            work = Path(work_path) if work_path is not None else run / ("src" if isolated_src else "work")
            sandbox = [
                "codex",
                "sandbox",
                *permission_args(work, runtime, skill is not None and not isolated_src, isolated_src, network_enabled),
                "-P",
                "scb",
                "-C",
                str(work),
            ]
            if native_skill_set is not None:
                for entry in native['skills']:
                    path=Path(native['installed_root'])/entry['name']/'SKILL.md'
                    result=subprocess.run(sandbox+["/bin/cat",str(path)],capture_output=True)
                    if result.returncode or result.stdout != path.read_bytes():
                        raise RuntimeError("Native skill is not readable in sandbox")
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
                audit_shell_writes(sandbox, work, runtime)
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
                if network_enabled:
                    bind = subprocess.run(sandbox + [str(Path(sys._base_executable).resolve()), "-c", "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); s.close()"], capture_output=True)
                    if bind.returncode:
                        raise RuntimeError("Local server binding failed: " + bind.stderr.decode()[-1000:])
                if (network.returncode == 0) != network_enabled:
                    raise RuntimeError("Native network policy does not match the requested setting")
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
                    "shell_write_smoke": isolated_src,
                    "network_enabled": network_enabled,
                    "network_probe": "loopback reachable" if network_enabled else "loopback blocked",
                    "designated_skill_sha256": native["sha256"] if native_skill_set is not None else hashlib.sha256((skill or "").encode()).hexdigest(),
                    "native_skill_set": native if native_skill_set is not None else None,
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
        capture(run, instruction_path.read_text() if instructions is not None else None, prompt or 'Inspect the supplied working files.', skill or '', audit=True)


def usage_from_events(path):
    events = []
    if path.exists():
        for line in path.read_text().split("\n"):
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    turns = [e for e in events if e.get("type") == "turn.completed"]
    return turns[-1]["usage"] if turns else None


def pricing(model):
    """Per-million-token rates for a model from configs/pricing.json."""
    table = json.loads((BASE / "configs/pricing.json").read_text())["models"]
    if model not in table:
        raise ValueError(f"No pricing for {model}; add it to configs/pricing.json")
    return table[model]


def cost(usage, model="gpt-6-luna"):
    rates = pricing(model)
    if usage is None:
        return None
    cached = usage.get("cached_input_tokens", 0)
    return ((usage["input_tokens"] - cached) * rates["input"]
            + cached * rates["cached_input"]
            + usage["output_tokens"] * rates["output"]) / 1e6


def observe_usage(meta, observations, run, *, required=False):
    """Telemetry must not abort monitor-only execution or final cleanup."""
    try:
        sample = meta.usage()
    except Exception as error:
        path = run / "quota-errors.json"
        errors = json.loads(path.read_text()) if path.exists() else []
        errors.append({"time": time.time(), "error_type": type(error).__name__, "message": str(error)})
        save(path, errors)
        if required:
            raise
        return None
    observations.append(sample)
    save(run / "quota.json", observations)
    return sample


def run_session(
    run, instructions, prompt, seconds, runtime=None, skill=None, prior_observations=(), isolated_src=False, capture_transcript=True, model="gpt-6-luna", monitor_only=False, work_path=None, network_enabled=False, effort="low", native_skill_set=None
):
    if (run / "run.json").exists():
        raise RuntimeError("Attempt already exists; refusing automatic retry")
    audit(run, instructions, runtime, skill, isolated_src, prompt, persist=instructions is None, model=model, work_path=work_path, network_enabled=network_enabled, effort=effort, native_skill_set=native_skill_set)
    cmd = command(run, instructions, runtime, skill, isolated_src, persist=capture_transcript, model=model, work_path=work_path, network_enabled=network_enabled, effort=effort, native_skill_set=native_skill_set)
    cfg = json.loads((BASE / "configs/quota.json").read_text())
    observations = []
    process = None
    meta = None
    started = time.monotonic()
    row = {
        "status": "started",
        "model": model,
        "quota_monitor_only": monitor_only,
        "reasoning": effort,
        "max_seconds": seconds,
        "fresh_conversation": True,
        "network_enabled": network_enabled,
        "skill_sha256": hashlib.sha256((skill or "").encode()).hexdigest(),
    }
    save(run / "run.json", row)
    try:
        work = Path(work_path) if work_path is not None else run / ('src' if isolated_src else 'work')
        from kojo.skill_sets import active_source
        native_skill_set_has_skills = active_source(native_skill_set) is not None
        meta = Metadata(native_work=work if native_skill_set is not None and native_skill_set_has_skills else None)
        observe_usage(meta, observations, run, required=not monitor_only)
        if not monitor_only:
            enforce(observations[-1], cfg, [*prior_observations, *observations], True)
        work = Path(work_path) if work_path is not None else run / ("src" if isolated_src else "work")
        from kojo.skill_sets import install
        native = install(work, native_skill_set, 'codex')
        expected = [str(Path(native['installed_root'])/s['name']/'SKILL.md') for s in native['skills']] if native else []
        row['native_skill_set'] = native
        if native: row['skill_sha256'] = native['sha256']
        row["skills_audit"] = meta.audit_skills(work, expected)
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
        if network_enabled:
            env.pop("PYTHONPATH",None)
        elif runtime:
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
                    observe_usage(meta, observations, run, required=not monitor_only)
                    if not monitor_only:
                        enforce(
                            observations[-1], cfg, [*prior_observations, *observations], True,
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
        row["api_price_equivalent_usd"] = cost(row["usage"], model)
        save(run / "run.json", row)
        if meta:
            try:
                observe_usage(meta, observations, run)
            finally:
                try:
                    meta.close()
                except Exception:
                    pass
                save(run / "quota.json", observations)
        else:
            save(run / "quota.json", observations)
        if capture_transcript and process is not None:
            from kojo.transcripts import capture
            instruction_path = (run if isolated_src else run / 'work') / 'instructions.md'
            try:
                row['transcript'] = capture(run, instruction_path.read_text() if instructions is not None else None, prompt, skill or '')
            except Exception as error:
                row['transcript_error'] = str(error)
            save(run / 'run.json', row)
    if row.get('transcript_error'):
        raise RuntimeError('Transcript capture failed; stop before another model call: ' + row['transcript_error'])
    if row["status"] == "cli_failure":
        raise RuntimeError("CLI infrastructure failure; inspect before resuming")
    return row
