#!/bin/sh
# Set up a fresh macOS checkout without Docker or model inference.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
[ "$(uname -s)" = Darwin ] || { echo 'Kojo currently requires macOS sandboxing.' >&2; exit 1; }
for tool in git uv npm; do
    command -v "$tool" >/dev/null 2>&1 || { echo "Install $tool first, then rerun setup." >&2; exit 1; }
done
# Setup changes shared environments: refuse while a controller holds a run lock.
python3 - <<'PY'
import fcntl
from pathlib import Path
for pattern in ('intermediate/runs/*/launcher.lock', 'intermediate/runs/*/gauntlet/execution.lock'):
    for path in Path('.').glob(pattern):
        with path.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit(f'Active run: {path}. Finish or stop it before setup.')
PY
uv sync --frozen
mkdir -p intermediate/vendor
checkout() {
    path=$1 url=$2 revision=$3
    if [ ! -d "$path" ]; then
        git clone --no-checkout "$url" "$path"
        git -C "$path" checkout --detach "$revision"
    else
        [ "$(git -C "$path" rev-parse HEAD)" = "$revision" ] || { echo "Wrong revision in $path; preserve it and use a fresh checkout." >&2; exit 1; }
        [ -z "$(git -C "$path" status --porcelain)" ] || { echo "Local edits in $path; refusing to overwrite." >&2; exit 1; }
    fi
}
checkout intermediate/vendor/slop-code-bench https://github.com/SprocketLab/slop-code-bench.git 31ceea3add480edb33431e70475c4c70597e6b31
checkout intermediate/vendor/scb-problems https://github.com/gabeorlanski/scb-problems.git 38d627ecf668a88f88f8d260f8df8df6116e9b03
UV_PROJECT_ENVIRONMENT="$PWD/intermediate/scb-runner-venv" uv sync --project intermediate/vendor/slop-code-bench --python 3.12.8 --frozen --no-dev
if [ ! -d intermediate/solver-venv ]; then
    uv venv --python 3.12.8 intermediate/solver-venv
fi
uv pip install --python intermediate/solver-venv/bin/python --require-hashes -r configs/solver.lock
# Local installs avoid changing the user's global CLIs.
npm install --prefix intermediate/provider-cli --no-audit --no-fund @openai/codex@0.158.0 @anthropic-ai/claude-code@2.1.283
intermediate/provider-cli/node_modules/.bin/codex --version
intermediate/provider-cli/node_modules/.bin/claude --version
printf '\nSetup complete. Sign in if needed, then audit/run with scripts/scb_suite.py.\n'
