"""Codex CLI adapter with account-wide weekly quota checks. No API-key billing."""

import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import tomllib


class QuotaStop(RuntimeError):
    pass


def overrides(ignore_user_config=False, native_work=None):
    settings = {
        "model": "gpt-6-luna",
        "model_reasoning_effort": "low",
        "forced_login_method": "chatgpt",
        "web_search": "disabled",
        "project_doc_max_bytes": 0,
        "memories.use_memories": False,
        "memories.generate_memories": False,
        "approval_policy": "never",
        "features.skip_host_skill_discovery": native_work is None,
    }
    for name in [
        "plugins",
        "apps",
        "multi_agent",
        "shell_tool",
        "unified_exec",
        "code_mode_host",
        "browser_use",
        "computer_use",
        "view_image",
        "skill_search",
        "unbounded_connection_retries",
    ]:
        settings["features." + name] = False
    args = []
    for k, v in settings.items():
        args += ["-c", k + "=" + json.dumps(v)]
    bases = [
        Path.home() / ".codex/skills",
        Path.home() / ".agents/skills",
        Path("/etc/codex/skills"),
    ]
    if native_work:
        bases += [ancestor / '.agents/skills' for ancestor in Path(native_work).parents]
        bases += [ancestor / '.codex/skills' for ancestor in Path(native_work).parents]
    # rglob does not descend into symlinked skill directories. Resolve every
    # reachable directory explicitly, with cycle protection, before disabling.
    found = set()
    visited = set()
    for base in bases:
        if not base.exists():
            continue
        for current, dirs, files in os.walk(base, followlinks=True):
            real = Path(current).resolve()
            if real in visited:
                dirs[:] = []
                continue
            visited.add(real)
            if "SKILL.md" in files:
                found.add(str(real / "SKILL.md"))
    skills = sorted(found)
    args += [
        "-c",
        "skills.config=["
        + ",".join("{path=" + json.dumps(p) + ",enabled=false}" for p in skills)
        + "]",
    ]
    cfg = Path.home() / ".codex/config.toml"
    config = tomllib.loads(cfg.read_text()) if cfg.exists() else {}
    for name in [] if ignore_user_config else config.get("mcp_servers", {}):
        if not all(c.isalnum() or c in "_-" for c in name):
            raise RuntimeError("Unsupported MCP identifier; cannot guarantee isolation")
        args += ["-c", "mcp_servers." + name + ".enabled=false"]
    return args


class Metadata:
    """Read-only app-server calls. Never starts a model turn or spends reset credits."""

    def __init__(self, native_work=None):
        self.proc = subprocess.Popen(
            ["codex", *overrides(native_work=native_work), "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.queue = queue.Queue()
        self.serial = 0

        def reader():
            for line in self.proc.stdout:
                try:
                    self.queue.put(json.loads(line))
                except ValueError:
                    pass
            self.queue.put({"eof": True})

        threading.Thread(target=reader, daemon=True).start()
        self.request(
            "initialize",
            {
                "clientInfo": {"name": "skill-pilot", "version": "0.2.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self.proc.stdin.write('{"method":"initialized","params":{}}\n')
        self.proc.stdin.flush()

    def request(self, method, params):
        self.serial += 1
        self.proc.stdin.write(
            json.dumps({"id": self.serial, "method": method, "params": params}) + "\n"
        )
        self.proc.stdin.flush()
        deadline = time.monotonic() + 15
        while True:
            result = self.queue.get(timeout=max(0.1, deadline - time.monotonic()))
            if result.get("eof"):
                raise RuntimeError("Metadata server exited")
            if result.get("id") == self.serial:
                if "error" in result:
                    raise RuntimeError("Metadata request failed")
                return result["result"]
            if time.monotonic() > deadline:
                raise RuntimeError("Metadata request timed out")

    def usage(self):
        data = self.request(
            "account/rateLimits/read",
            {"excludeResetCreditDetails": True, "supportsLunaReserve": False},
        )
        return weekly_snapshot(data)

    def audit_skills(self, cwd, expected=()):
        data = self.request("skills/list", {"cwds": [str(cwd)], "forceReload": True})
        skills = [s for row in data["data"] for s in row["skills"]]
        enabled = {str(Path(s["path"]).resolve()) for s in skills if s["enabled"]}
        if enabled != set(expected):
            raise RuntimeError("Unexpected enabled skill; refusing inference")
        return {"discovered": len(skills), "enabled": len(enabled), "paths": sorted(enabled)}

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


def weekly_snapshot(data):
    rates = data.get("rateLimitsByLimitId")
    if rates is not None:
        if "codex" not in rates:
            raise QuotaStop("No codex weekly bucket")
        bucket = rates["codex"]
    else:
        bucket = data.get("rateLimits")
    if not bucket:
        raise QuotaStop("Usage unavailable")
    windows = [bucket.get(k) for k in ("primary", "secondary")]
    weeks = [w for w in windows if w and w.get("windowDurationMins") == 10080]
    if len(weeks) != 1 or weeks[0].get("usedPercent") is None:
        raise QuotaStop("Weekly usage unavailable or ambiguous")
    w = weeks[0]
    if not 0 <= w["usedPercent"] <= 100:
        raise QuotaStop("Invalid weekly usage")
    return {
        "remaining_percent": 100 - w["usedPercent"],
        "used_percent": w["usedPercent"],
        "resets_at": w["resetsAt"],
        "observed_at": time.time(),
    }


def enforce(snapshot, cfg, observations, before=True):
    if snapshot["resets_at"] != cfg["weekly_resets_at"]:
        raise QuotaStop("Weekly window changed; do not start spending a new window")
    floor = cfg["weekly_remaining_floor"]
    if snapshot["remaining_percent"] <= floor:
        raise QuotaStop("Weekly remaining reached the 78% stop floor")
    if before:
        drops = [
            a["remaining_percent"] - b["remaining_percent"]
            for a, b in zip(observations, observations[1:])
        ]
        buffer = max(
            [1] + drops
        )  # integer reporting and recent account-wide consumption
        if snapshot["remaining_percent"] <= floor + buffer:
            raise QuotaStop(
                "Insufficient headroom for another invocation above the weekly floor"
            )
