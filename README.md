# Kojo

A small experiment in whether persistent, reusable instructions help a cheap coding
model solve unseen software tasks. Learning here means revising skill documents;
there is no model training or fine-tuning.

**Latest run:** Luna with explicit verification guidance finished `code_search` at
76/104 tests, still fully passing 2/5 checkpoints. [Comparison with baseline](results/runs/20260927-code-search-guided-01/RESULTS.md).

**Previous status:** the Docker-free SCB baseline is complete. GPT-6 Luna passed
2 of 5 `code_search` checkpoints completely, ending with 83/104 tests passing.
The baseline / initial-skills / learned-skills gauntlet is now prepared and awaits
paid-run approval. [Protocol, budget, and commands](docs/gauntlet.md).

- [Run registry and exact prompts](results/runs/README.md)
- [Public code_search specifications](specs/code_search/checkpoint_1.md)
- [Results and accounting](results/scb-code-search/RESULTS.md)
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
scripts/       One command-line entry point
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
