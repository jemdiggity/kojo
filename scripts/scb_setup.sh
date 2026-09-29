#!/bin/sh
# Prepare a worktree from the shared, versioned benchmark setup cache.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
exec python3 scripts/scb_setup.py
