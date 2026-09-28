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

## Repository layout

```text
src/kojo/       CLI execution, quota guard, evaluator, reporting, tmux viewer
scripts/       CLI entry points and explicit experiment launchers
skills/        Initial-skill and revision-writer prompts
configs/       Experiment/split definitions, pinned dependencies, and quota limits
tests/         Offline quota, isolation, and artifact integrity checks
results/       Frozen submissions, evaluation reports, and usage accounting
docs/          Protocol, reproduction, and upstream investigation
intermediate/  Ignored local traces, scratch data, vendor checkouts, and environments
```

Raw traces, credentials, virtual environments, and vendored repositories are not
committed. Dependency pins and frozen evidence live under `results`; the maintained
harness lives under `src/kojo`. No new model runs were made during repository cleanup.

The current factory enables network access and audits external-source evidence
after each session. Role instructions are separate versioned Markdown files.
See [factory protocol](docs/factory.md),
[audit policy](docs/external-access-audit.md), and
[no-inference verification](results/harness/network-enabled-v1/REPORT.md).
Previous benchmark results remain restricted-network diagnostics.
