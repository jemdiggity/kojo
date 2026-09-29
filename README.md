# Kojo — New Models Meet SCBench

September 28, 2026

We ran six coding models through three evolving software problems: `circuit_eval`,
`database_migration`, and `dynamic_config_service_api`. Each model worked through
17 checkpoints at medium effort, carrying its code into a fresh conversation each
time. No reviewer, fixer, or learned skills were supplied in this comparison.

**Astra 6 led on correctness and was the only completed model to fully pass a
problem: all eight checkpoints of `circuit_eval`.** Sonnet 5.5 matched Opus 5.5’s
strict score at about one third of its API-equivalent cost. Static code-quality
scores did not track correctness: Opus 5 had the lowest measured erosion but the
fewest fully passing checkpoints.

**[Read the full results, checkpoint breakdown, quality analysis, and methodology →](results/comparisons/20260928-dex-subset/SUITE_ANALYSIS.md)**

## Results at a glance

Models are listed newest release first. These are the six completed baselines;
Fable 5.1 is being evaluated separately and is not included below.

| Model | Strict checkpoints passed | Partial pass | API-equivalent cost |
|---|---:|---:|---:|
| Sonnet 5.5 | 7/17 | 90.8% | $6.86 |
| Opus 5.5 | 7/17 | 90.7% | $21.07 |
| Sol 6 | 5/17 | 90.3% | ≥$4.03 |
| Astra 6 | 11/17 | 90.8% | ≥$15.89 |
| Opus 5 | 4/17 | 85.8% | $72.85 |
| Sol 5.6 | 8/17 | 90.6% | ≥$13.29 |

Strict means every collected test passes, including required regressions, with no
failures or skips. Partial pass averages each checkpoint’s passed/collected
percentage; skipped tests stay in the denominator.

![Figure 1. Strict checkpoint pass rates](results/comparisons/20260928-dex-subset/charts/figure-01-strict-pass-bars.png)

## What did the performance cost?

![Figure 8. Partial-pass value versus model release date](results/comparisons/20260928-dex-subset/charts/figure-08-value-release-date.png)

Higher means more partial-pass percentage points per API-equivalent dollar.
Missing usage for one interrupted attempt per Codex model makes its cost a lower
bound (≥) and its value an upper bound (≤). Dates are public API release dates;
this chart does not establish that newer models cause better value.

## What happened to code quality?

![Figure 14. Quality across normalized problem progress](results/comparisons/20260928-dex-subset/charts/figure-14-quality-progress.png)

Lower erosion and verbosity are better under the static analyzer’s definitions.
Erosion measures complexity concentrated in complex functions; verbosity measures
the share of source lines flagged by structural rules. These are proxies, not
proof of maintainability. Generated tests affect the scores. Each curve averages
three problem trajectories interpolated to five progress positions.

Figure numbers match the full report; this README includes only three highlights.

## How to interpret this experiment

One trajectory per model on three problems is preliminary evidence. Checkpoints
share regression tests and are not independent tasks. Provider interruptions and
harness recovery affected some runs; the full report preserves those limitations.
Astra submitted a shell wrapper around Python for `dynamic_config_service_api`;
we corrected our launcher and regraded unchanged source against unchanged tests.

Kojo is a separate local harness, not a GitHub fork of SCB. It reuses pinned
upstream specifications and tests, but runs subscription-authenticated Codex CLI
and Claude Code in local directories instead of direct API calls and Docker.
Dollar amounts are hypothetical API-equivalent token costs, not subscription
charges. This suite tests model baselines; persistent skill learning remains a
future experiment, with no weight training or fine-tuning involved.

- [Full suite analysis and reproduction](results/comparisons/20260928-dex-subset/SUITE_ANALYSIS.md)
- [Detailed code-quality measurements](results/comparisons/20260928-dex-subset/quality-suite/QUALITY.md)
- [Earlier build/review/fix experiment](results/comparisons/20260928-checkpoint-factory-10m/RESULTS.md)
- [Setup and reproduction](docs/reproduction.md)
- [Protocol and context isolation](docs/protocol.md)
- [Local run registry](results/runs/README.md)

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
Earlier restricted-network diagnostics are retained separately from the network-enabled suite.

---

Jeremy Hale · [@jemdiggity](https://github.com/jemdiggity) · [kanna.build](https://kanna.build)
