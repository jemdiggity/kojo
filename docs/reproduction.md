# Docker-free setup and reproduction

The controller requires Python 3.12.8 and uses no third-party Python packages.
`uv sync --frozen` sets up the pinned controller runtime, or use an existing Python
3.12.8 installation. Use `uv run python scripts/kojo.py ...` in place of
`python3.12 scripts/kojo.py ...` if desired.

## External tools

Generation requires macOS native Codex sandbox support, authenticated Codex CLI
0.157.1, and the original approved quota window in `configs/quota.json`. The guard
refuses a different week; do not change it to authorize new spending implicitly.
Viewing needs tmux (verified with 3.6a). Grading needs uv and the pinned SCB runner:

```sh
mkdir -p intermediate/vendor
git clone https://github.com/SprocketLab/slop-code-bench.git intermediate/vendor/slop-code-bench
git -C intermediate/vendor/slop-code-bench checkout 31ceea3add480edb33431e70475c4c70597e6b31
git clone https://github.com/gabeorlanski/scb-problems.git intermediate/vendor/scb-problems
git -C intermediate/vendor/scb-problems checkout 38d627ecf668a88f88f8d260f8df8df6116e9b03
UV_PROJECT_ENVIRONMENT="$PWD/intermediate/scb-runner-venv" uv sync --project intermediate/vendor/slop-code-bench --python 3.12.8 --frozen --no-dev
```

No Docker daemon or images are required. The runner includes a Docker SDK dependency,
but `configs/local.yaml` selects its native local runtime. Adjust its Python executable
path on another machine. Grader dependencies are pinned with hashes in
`configs/grader.lock`; SCB resolves them through uvx constraints.

The evaluator uses `PYTEST_ADDOPTS=.evaluation_tests` so pytest loads SCB's conftest
before parsing custom options. No benchmark tests or upstream runner code were edited.

## Commands

```sh
python3.12 scripts/kojo.py status --once  # Saved state; no live account request
python3.12 scripts/kojo.py report        # Rebuild summary from committed artifacts
python3.12 scripts/kojo.py tmux watch    # No model calls
tmux attach -t scb
```

The two monitor panes show status/quota timestamps and readable agent events.
Detach with Ctrl-b then d; scroll with Ctrl-b then [ (or your configured prefix).
Raw traces remain under `intermediate`, so a fresh clone has summary data but no
historical event replay.

Only after authorization, in a separate reproduction checkout with existing output
folders preserved elsewhere:

```sh
python3.12 scripts/kojo.py tmux run --session scb-next
# Equivalent without tmux:
python3.12 scripts/kojo.py generate
# After generation finishes:
python3.12 scripts/kojo.py grade
python3.12 scripts/kojo.py report
```

Generation continues the seed at
`results/scb-code-search/checkpoints/checkpoint_1/submission`. Preserve checkpoint 1.
For a fresh continuation, move checkpoints 2–5 and their local attempt directories
(`intermediate/scb-sequence/checkpoint_2` through `checkpoint_5`) out of the way in
that separate checkout. Completed attempts are skipped; ambiguous retries fail closed.
Grading refuses existing grading folders; preserve them before regrading. Generation
spends allowance; grading/reporting do not call models. Detaching tmux leaves a run
alive; killing the runner window can interrupt it.

The legacy `generate` command supports the recorded `code_search` continuation.
For fresh problems and the three-condition learning experiment, use the separate
[gauntlet commands](gauntlet.md).

## Recorded provenance

`results/scb-code-search/pins.json` records dependency revisions and retained input
hashes. Every frozen submission has its own hash manifest, checked by
`tests/test_artifacts.py`. Original paths in recorded logs remain unchanged. The old
harnesses were deleted at user request; Git tracks the maintained implementation.
