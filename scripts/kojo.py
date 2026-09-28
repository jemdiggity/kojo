#!/usr/bin/env python3
"""Repository entry point. Status/report/view commands make no model calls."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["status", "events", "tmux", "generate", "grade", "report", "_agent"],
    )
    args, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0], *remaining]
    if args.command in ["status", "events"]:
        from kojo import tmux_view

        sys.argv.insert(1, args.command)
        tmux_view.main()
    elif args.command == "tmux":
        from kojo import tmux_session

        tmux_session.main()
    elif args.command == "report":
        from kojo import report

        report.main()
    elif args.command == "_agent":
        from kojo import cli_adapter

        if remaining not in [["audit"], ["run"]]:
            parser.error("_agent requires audit or run")
        {"audit": cli_adapter.audit, "run": cli_adapter.run}[remaining[0]]()
    else:
        from kojo import sequence

        if remaining:
            parser.error("unexpected arguments")
        {"generate": sequence.generate, "grade": sequence.grade}[args.command]()


if __name__ == "__main__":
    main()
