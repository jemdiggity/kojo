#!/bin/sh
# Prepare a worktree from the shared, versioned benchmark setup cache.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
# A gitignored .env (copied from the main checkout) may set KOJO_DATA_DIR for setup.
if [ -f .env ]; then set -a; . ./.env; set +a; fi
exec python3 scripts/scb_setup.py
