# Kojo — New Models Meet SCBench

September 28, 2026

We ran seven coding models through three evolving software problems: `circuit_eval`,
`database_migration`, and `dynamic_config_service_api`. Each model worked through
17 checkpoints at medium effort, carrying its code into a fresh conversation each
time. No reviewer, fixer, or learned skills were supplied in this comparison.

**Astra 6 led on correctness and was the only completed model to fully pass a
problem: all eight checkpoints of `circuit_eval`.** Sonnet 5.5 matched Opus 5.5’s
strict score at about one third of its API-equivalent cost. Static code-quality
scores did not track correctness: Opus 5 had the lowest measured erosion despite weak
strict correctness.

**[Read the full results, checkpoint breakdown, quality analysis, and methodology →](results/comparisons/20260928-dex-subset/SUITE_ANALYSIS.md)**

## Results at a glance

Models are listed newest release first. All seven baselines are complete.

| Model | Strict checkpoints passed | Partial pass | API-equivalent cost |
|---|---:|---:|---:|
| Sonnet 5.5 | 7/17 | 90.8% | $6.86 |
| Opus 5.5 | 7/17 | 90.7% | $21.07 |
| Sol 6 | 5/17 | 90.3% | ≥$4.03 |
| Astra 6 | 11/17 | 90.8% | ≥$15.89 |
| Fable 5.1 | 3/17 | 85.1% | $69.84 |
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
Fable’s `dynamic_config_service_api` run encountered two denied package-install
attempts and wrote replacements; network-enabled configuration did not guarantee
unrestricted dependency installation. This is disclosed in the full report.
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
- [Protocol and context isolation](docs/protocol.md)

## Run the experiment

Software dependencies: macOS, Git, uv, Python 3, and Node.js/npm. Setup installs Python 3.12.8, Codex CLI 0.158.0, Claude Code 2.1.283, and the pinned benchmark dependencies. Authenticated provider accounts with access to the selected models are required. No Docker or tmux is needed.

**Account risk:** Anthropic may suspend or terminate accounts for terms violations. Its consumer terms restrict automated access except where explicitly permitted. Kojo invokes the official Claude Code CLI, but that is not a guarantee that this benchmark workload is permitted under your subscription. Review the [Consumer Terms](https://www.anthropic.com/legal/consumer-terms) and [Claude Code usage rules](https://code.claude.com/docs/en/legal-and-compliance) before running it. See Anthropic’s [enforcement policy](https://www.anthropic.com/transparency/system-trust-reporting).

```sh
sh scripts/scb_setup.sh
```

Preview and audit without inference, then run:

```sh
.venv/bin/python scripts/scb_suite.py --id repro-01 --models sonnet55 opus55 sol6 astra6 fable51 opus5 sol56 --problems circuit_eval database_migration dynamic_config_service_api
.venv/bin/python scripts/scb_suite.py --id repro-01 --models sonnet55 opus55 sol6 astra6 fable51 opus5 sol56 --problems circuit_eval database_migration dynamic_config_service_api --audit
.venv/bin/python scripts/scb_suite.py --id repro-01 --models sonnet55 opus55 sol6 astra6 fable51 opus5 sol56 --problems circuit_eval database_migration dynamic_config_service_api --run
```

Select models with a space-separated list:

```sh
.venv/bin/python scripts/scb_suite.py --id repro-02 --models sonnet55 opus55 astra6 --problems circuit_eval database_migration --run
```

Supported suite aliases map to exact provider IDs; they are not moving “latest” aliases:

| CLI alias | Provider model ID |
|---|---|
| `sonnet55` | `claude-sonnet-5-5` |
| `opus55` | `claude-opus-5-5` |
| `sol6` | `gpt-6-sol` |
| `astra6` | `gpt-6-astra` |
| `opus5` | `claude-opus-5` |
| `sol56` | `gpt-5.6-sol` |
| `fable51` | `claude-fable-5-1` |

`--models` and `--problems` are both required; neither has an implicit selection. Supported problems: `code_search` (5 checkpoints), `circuit_eval` (8), `database_migration` (5), and `dynamic_config_service_api` (4). Without `--parallel`, all runs execute in series, in the order supplied. Duplicate or unknown names are rejected. Use the same selections for audit and run.

Use a fresh ID for each experiment. Use `--models sonnet55` for a single model. The example runs seven models through all three problems: 119 sessions
at medium effort, with 30 minutes per session and no review. **`--run` consumes
provider allowance; usage is reported but there is no spending cap.** Your accounts
must have access to the selected models. No Docker or tmux is required.

Progress appears in the terminal. Results are saved under `results/runs/`; raw
transcripts and logs under `intermediate/runs/`. Ctrl-C stops the controller.

### Skill sets and parallel execution

Each directory passed to `--skill-sets` is a separate condition. Kojo runs every
problem × model × skill-set combination. Omit it for the no-skills baseline.
Use a directory containing `SKILL.md`, or a directory of named skill folders
(`testing/SKILL.md`, `review/SKILL.md`, etc.). Supporting scripts and resources
are included. An empty directory adds a no-skills condition to the matrix.

Instead of a path, `--skill-sets` accepts well-known names, each pinned to an
exact upstream commit and cached under `intermediate/vendor/skill-sets/`:

| Name | Source |
|---|---|
| `karpathy` | [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) `skills/` |
| `superpowers` | [obra/superpowers](https://github.com/obra/superpowers) `skills/` |

Names and paths can be mixed (`--skill-sets karpathy superpowers ./mine`). Add
more in `src/kojo/known_skill_sets.py`.

```sh
.venv/bin/python scripts/scb_suite.py --id skills-01 \
  --models sonnet55 opus55 astra6 \
  --problems circuit_eval database_migration dynamic_config_service_api \
  --skill-sets ./skill-sets/baseline ./skill-sets/testing ./skill-sets/review \
  --parallel all
```

This previews 27 independent runs. Use the same command with `--audit` for
no-inference checks, then with `--run` to execute it. Each run still processes
its checkpoints sequentially, with a fresh conversation at each checkpoint.

| Option | Concurrent runs | Sequential barriers |
|---|---|---|
| Omitted | One run | Problems, skill sets, and models |
| `--parallel models` | Models | Problems and skill sets |
| `--parallel models-skills` | Models × skill sets | Problems |
| `--parallel all` | Problems × models × skill sets | Only each run’s checkpoints |

Selections retain the order supplied. Skill sets are copied and hashed when the
plan is saved; use a new experiment ID when changing skills or scheduling.
Each problem × model × skill-set run gets its own physical copy of the selected
skills and resources, even when several runs select the same set. No live skill
directory is shared between runs. Each run has its own workspace and transcripts. Codex discovers the selected
project skills; Claude discovers them through an explicit local skill plugin.
Ambient skills and memory remain disabled, and stock system prompts remain in
use. Skills are available for native invocation, not inserted into every task
prompt; their use is observable in the captured transcripts. These new options
do not change the published baseline results above.

## Advanced batch plans

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
results/       Versioned comparison reports and charts; ignored local runs
docs/          Protocol, reproduction, and upstream investigation
intermediate/  Ignored local traces, scratch data, vendor checkouts, and environments
```

Raw traces, credentials, virtual environments, and vendored repositories are not
committed. Per-run evidence under `results/runs/<run-id>/` also stays local, including
submissions, installed dependencies, the generated registry, and relocation metadata.
Comparison reports, chart data, and reproduction scripts remain versioned. Recomputing reports requires
the local run evidence; a Git clone alone does not include it. Dependency pins are
versioned, and the maintained harness lives under `src/kojo`.

The current factory enables network access and audits external-source evidence
after each session. Role instructions are separate versioned Markdown files.
See [factory protocol](docs/factory.md),
[audit policy](docs/external-access-audit.md).
Earlier restricted-network diagnostics are retained separately from the network-enabled suite.

---

Jeremy Hale · [@jemdiggity](https://github.com/jemdiggity) · [kanna.build](https://kanna.build)
