"""Create an attachable SCB tmux monitor; generation requires explicit `run`."""

import argparse
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parents[1]


def tmux(*args, check=True):
    return subprocess.run(["tmux", *args], check=check, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", default="watch", choices=["watch", "run"])
    parser.add_argument("--session", default="scb")
    args = parser.parse_args()
    if not args.session or not all(c.isalnum() or c in "_-" for c in args.session):
        parser.error(
            "session must contain only letters, numbers, underscores, and hyphens"
        )
    existing = tmux("list-sessions", "-F", "#{session_name}", check=False)
    if args.session in existing.stdout.splitlines():
        if args.mode == "run":
            parser.error(
                "session already exists; refusing to launch a duplicate runner"
            )
        print(f"tmux attach -t {shlex.quote(args.session)}")
        return
    python = sys.executable
    view = str(BASE / "scripts/kojo.py")
    command = lambda mode: shlex.join([python, "-u", view, mode])
    created = tmux(
        "new-session",
        "-d",
        "-s",
        args.session,
        "-n",
        "monitor",
        "-x",
        "160",
        "-y",
        "45",
        "-c",
        str(BASE),
        "-P",
        "-F",
        "#{session_id} #{pane_id}",
        command("status"),
    )
    target, pane = created.stdout.strip().split()
    tmux("set-option", "-t", target, "history-limit", "20000")
    tmux("split-window", "-v", "-t", pane, "-c", str(BASE), command("events"))
    tmux("select-layout", "-t", target + ":monitor", "even-vertical")
    if args.mode == "run":
        runner = shlex.join([python, "-u", str(BASE / "scripts/kojo.py"), "generate"])
        # A separate shell keeps the window visible after the guarded runner exits.
        shell = (
            runner
            + '; code=$?; printf "\\nRunner exit status: %s\\n" "$code"; exec /bin/zsh -f'
        )
        tmux("new-window", "-t", target, "-n", "runner", "-c", str(BASE), shell)
    tmux("select-window", "-t", target + ":monitor")
    print(f"tmux attach -t {shlex.quote(args.session)}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.stderr.strip() or str(error))
