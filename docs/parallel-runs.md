# Parallel SCB runs

The batch launcher runs independent instances of the SCB
factory. Each instance still completes its checkpoints sequentially, including
build → review → fix when reviews are enabled. Parallelism does not change the
model prompt, checkpoint source flow, grading, or timeout policy.

Claude auto-memory remains disabled in every session. Each run has a separate
workspace, virtual environment, session IDs, logs, receipts, and grading outputs.
Provider login and subscription limits remain shared, as with ordinary parallel
Claude sessions. Concurrent resource use can affect elapsed times; the actual
concurrency is recorded with the batch.

## Configure and inspect

Copy [the example](../configs/batches/parallel-example.json), choose a new
`batch_id` and unique `run_id` values, and supply normal `kojo.factory` arguments
for each run. The example contains two Sonnet 4.6 medium baselines with 128k
response allowances and 30-minute session limits. It is an example, not a request
to launch paid runs. The factory supports `code_search`, `circuit_eval`, `database_migration`, and
`dynamic_config_service_api`, using each problem’s upstream checkpoint count.

```sh
# Print exact commands; no model calls or run directories are created.
python3.12 scripts/scb_batch.py configs/batches/parallel-example.json

# Two concurrent native CLI audits, using local dummy endpoints. No inference.
python3.12 scripts/scb_batch.py configs/batches/parallel-example.json --audit

# Execute the configured runs; consumes provider usage.
python3.12 scripts/scb_batch.py configs/batches/parallel-example.json --run \
  --jobs 2 --tmux-session scb-parallel

tmux attach -t scb-parallel
```

`max_parallel` defaults to two; `--jobs` overrides it. With one job the same batch
runs serially. Every run's arguments are validated before any process starts.
Different builder/reviewer models, efforts, review settings, or repeats can be
listed in the same batch. Codex runs can use `--monitor-only` when usage-floor
stopping has been explicitly waived; Claude uses the existing reporting policy.

Audits use distinct IDs derived from the batch and run IDs, so they do not consume
the IDs intended for inference. A repeated audit needs a new batch ID. No attempt
is silently overwritten or resumed.

## Monitoring and stopping

The launcher stays in the foreground. `--tmux-session` creates one **log viewer**
window per started run; it does not detach the launcher. To keep the launcher
itself alive independently of your terminal, start it in tmux:

```sh
tmux new-session -s scb-controller \
  'python3.12 scripts/scb_batch.py configs/batches/parallel-example.json --run --tmux-session scb-controller'
```

Ctrl-C or SIGTERM on the launcher cancels active controllers and prevents queued
runs from starting. Controllers terminate their model children and retain their
normal interrupted-run receipts. Closing a log viewer only closes the viewer.
A failed/timed-out run does not prevent independent queued runs from executing;
the batch exits nonzero if any run fails. There is no automatic retry or larger
time budget: use the existing explicit checkpoint-resume options in a new run.

Do not edit factory code, shared configuration, or role instructions during a
batch; the protocol hash guard cancels the batch if the harness changes. Per-run
arguments are frozen at launch. Run IDs are reserved across batch and Sonnet
launchers; direct factory invocations also retain their per-run execution lock.

## Artifacts

- `intermediate/batches/<batch-id>/plan.json`: frozen effective batch settings.
- `commands.json` and `status.json` beside it: commands, process IDs, timestamps,
  concurrency, cancellation, and exit status. Audit batches use `<batch-id>-audit`.
- `intermediate/runs/<run-id>/run-config.json`: frozen per-run command and config.
- `controller.log` and `launcher-exit.json` beside it: separate logs and exit status.
- `results/runs/<run-id>/`: normal factory results plus the copied run config.

The shared results index is updated under a process lock with atomic replacement;
concurrent report writers preserve one another's entries. Reports remain separate
postprocessing commands. The older Sonnet launcher also accepts
`--config /path/to/plan.json` and freezes that plan, so it no longer requires
editing a shared config for independent launches.

## Recover an interrupted baseline

Use a new run ID and `--resume-run OLD_ID --no-review`. Omit
`--resume-checkpoint` to detect the contiguous completed prefix automatically.
The controller checks model/effort, transcript verification, and frozen source
hashes before copying completed receipts. It starts the next checkpoint in a
fresh conversation and rebuilds the environment from the completed snapshot’s
requirements; the interrupted workspace is never reused. Keep all failed
attempt receipts for total cost accounting, and count copied sessions only once.

In monitor-only mode, unavailable quota telemetry is recorded in
`quota-errors.json` without terminating inference. Enforced quota mode still
stops when usage cannot be checked. Provider failures still stop the chain;
synthetic CLI error messages are not treated as model identity evidence.

## Dashboard

`python3.12 scripts/scb_dashboard.py [--port 8765]` serves a read-only local web
page (stdlib only, no inference) with auto-refreshing batch/run progress,
per-checkpoint test results and cost, the controller log tail, and the published
comparison tables and figures. It only reads `intermediate/` and `results/`.
