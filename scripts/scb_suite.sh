#!/bin/sh
# Run scb_suite.py under the project's pinned Python, from any directory.
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
[ -x "$root/.venv/bin/python" ] || { echo 'Missing .venv; run scripts/scb_setup.sh first.' >&2; exit 1; }
exec "$root/.venv/bin/python" "$root/scripts/scb_suite.py" "$@"
