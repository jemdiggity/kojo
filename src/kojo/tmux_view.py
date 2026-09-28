"""Read-only live view of SCB status and Codex JSONL traces. No model calls."""

import argparse
import json
from pathlib import Path
import time

from kojo.execution import session_paths

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / "intermediate/runs/20260927-code-search-continuation-01"


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def runs(data):
    if data.name == "gauntlet":
        return [
            (str(p.parent.relative_to(data)), p.parent) for p in session_paths(data)
        ]
    first = data / "checkpoint_1"
    candidates = [(1, first)] + [(n, data / f"checkpoint_{n}") for n in range(2, 6)]
    return [
        (
            n,
            path
            if (path / "run.json").exists()
            else BASE / f"results/runs/20260927-code-search-continuation-01/checkpoints/checkpoint_{n}",
        )
        for n, path in candidates
    ]


def dashboard(data):
    rows = [
        f"SCB {data.name} | read-only monitor | no model calls",
        "Saved state, refreshed every second. Completed runs are recorded history.",
        "",
        "Attempt / checkpoint                                             Status          Seconds    Last quota",
    ]
    for n, path in runs(data):
        run = read(path / "run.json", {})
        samples = read(path / "usage.json", read(path / "quota.json", []))
        seconds = run.get("elapsed_seconds")
        elapsed = f"{seconds:.1f}" if seconds is not None else "—"
        quota = "—"
        if samples:
            last = samples[-1]
            stamp = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(last["observed_at"])
            )
            quota = f"{last['remaining_percent']}% at {stamp}"
        rows.append(
            f"{str(n):<64} {run.get('status', 'not started'):<15} {elapsed:<10} {quota}"
        )
    rows += [
        "",
        "Quota floor: 78%. Detach: Ctrl-b then d. Scroll: Ctrl-b then [.",
        "This viewer does not start, stop, or send input to the agent.",
        "Grading remains separate; its feedback is never sent to the agent.",
    ]
    return "\n".join(rows)


def event_text(event):
    item = event.get("item", {})
    kind = item.get("type", event.get("type", "?"))
    state = event.get("type", "?")
    if kind == "command_execution":
        body = item.get("command", "")
        if state == "item.completed":
            body += (
                f"\nexit={item.get('exit_code')}\n"
                + item.get("aggregated_output", "")[-4000:]
            )
    elif kind == "agent_message":
        body = item.get("text", "")
    elif kind == "file_change":
        body = json.dumps(item.get("changes", []), ensure_ascii=False)
    elif kind == "error":
        body = item.get("message", "")
    elif state == "turn.completed":
        body = json.dumps(event.get("usage", {}))
    else:
        body = ""
    # Do not allow logged terminal control characters to control this terminal.
    body = "".join(c for c in body if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127))
    return f"[{state} / {kind}] {body}"


def follow_events(data, once=False):
    print(
        "RECORDED HISTORY, followed by new events as they arrive. No agent input.",
        flush=True,
    )
    offsets = {}
    while True:
        for n, path in runs(data):
            source = path / "events.jsonl"
            if not source.exists():
                continue
            offset = offsets.get(source, 0)
            if source.stat().st_size < offset:
                offset = 0
            with source.open("rb") as stream:
                stream.seek(offset)
                while True:
                    start = stream.tell()
                    line = stream.readline()
                    if not line.endswith(b"\n"):
                        offsets[source] = start
                        break
                    offsets[source] = stream.tell()
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    print(f"\nCheckpoint {n} {event_text(event)}", flush=True)
        if once:
            return
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["status", "events"])
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.mode == "events":
        follow_events(args.data, args.once)
    else:
        while True:
            print(
                ("" if args.once else "\033[2J\033[H") + dashboard(args.data),
                flush=True,
            )
            if args.once:
                break
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
