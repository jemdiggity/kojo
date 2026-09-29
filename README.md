# Kojo

Experiments on changes to a software factory harness: model choice, independent
review, fixer passes, and execution budgets. Persistent skill learning remains a
future experiment; no model training or fine-tuning is involved.

**Latest run: restricted-network diagnostic.** Four fresh `code_search` chains used
the same harness, 10-minute sessions, and one review/fix loop at every checkpoint
in reviewed conditions. Final scores: Luna **64/104**, Luna-reviewed Luna **81/104**,
Astra low **96/104**, Astra-reviewed Luna **94/104**. None fully passed the final suite.

[Checkpoint scores, paired changes, costs, transcripts, and reproduction](results/comparisons/20260928-checkpoint-factory-10m/RESULTS.md).
Network restrictions were our deviation from normal SCB; the user explicitly chose
to finish this batch as a diagnostic. Earlier five-minute/final-only review results
are preserved separately.

- [Run registry and exact prompts](results/runs/README.md)
- [Public code_search specifications](specs/code_search/checkpoint_1.md)
- [Results and accounting](results/runs/20260927-code-search-continuation-01/RESULTS.md)
- [Setup, execution, and reproduction](docs/reproduction.md)
- [Protocol and context isolation](docs/protocol.md)

## Relationship to SCB

Kojo is a separate local execution harness, not a GitHub fork of SCB. It uses
pinned upstream specifications and grading tests, while running agents through
subscription-authenticated Codex CLI and Claude Code in local directories instead
of direct API calls and Docker. Reported dollar amounts are hypothetical
API-equivalent token costs, not subscription charges.

[Current suite results and protocol differences](results/comparisons/20260928-dex-subset/SUITE_ANALYSIS.md).

## Quick start

Python 3.12.8 is pinned. The controller uses only the standard library; Codex CLI,
tmux, and SCB's evaluator are separate tools. From the repository root:

```sh
python3.12 scripts/kojo.py status --once
python3.12 scripts/kojo.py report
python3.12 scripts/kojo.py tmux watch
tmux attach -t scb
```

These commands do not call a model. The monitor displays saved history and follows
new events. Generation requires the explicit `generate` command; see the protocol
and reproduction instructions before spending allowance.

```sh
python3.12 -m unittest discover -s tests -v
```

## Parallel runs

Independent SCB factories can run concurrently while each checkpoint chain stays
sequential. Inspect an example without inference:

```sh
python3.12 scripts/scb_batch.py configs/batches/parallel-example.json
```

Use `--audit` for concurrent no-inference CLI checks, or `--run --jobs 2` to execute
the configured runs. [Configuration, tmux monitoring, and cancellation](docs/parallel-runs.md).

## Repository layout

```text
src/kojo/       CLI execution, quota guard, evaluator, reporting, tmux viewer
scripts/       CLI entry points and explicit experiment launchers
skills/        Initial-skill and revision-writer prompts
configs/       Experiment/split definitions, pinned dependencies, and quota limits
tests/         Offline quota, isolation, and artifact integrity checks
results/       Versioned comparison reports, charts, and compact run registry
docs/          Protocol, reproduction, and upstream investigation
intermediate/  Ignored local traces, scratch data, vendor checkouts, and environments
```

Raw traces, credentials, virtual environments, and vendored repositories are not
committed. Per-run evidence under `results/runs/<run-id>/` also stays local, including
submissions and their installed dependencies. The small registry, comparison reports,
chart data, and reproduction scripts remain versioned. Recomputing reports requires
the local run evidence; a Git clone alone does not include it. Dependency pins are
versioned, and the maintained harness lives under `src/kojo`.

The current factory enables network access and audits external-source evidence
after each session. Role instructions are separate versioned Markdown files.
See [factory protocol](docs/factory.md),
[audit policy](docs/external-access-audit.md), and
[no-inference verification](results/harness/network-enabled-v1/REPORT.md).
Previous benchmark results remain restricted-network diagnostics.
