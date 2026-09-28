# Luna skill-learning gauntlet

Prepared, offline-verified, **not approved or run yet**. This extends the previous
Docker-free baseline with fresh problem starts, bounded skill learning, and paired
held-out evaluation. The prior `code_search` result is development evidence only;
no previous solution is used to seed this experiment.

## Proposed experiment

All model work uses **GPT-6 Luna, low reasoning, Codex CLI 0.157.1** under the existing
ChatGPT subscription. The same model writes the skills. Stronger-assistant harness
preparation is not separately metered and is not evidence of Luna teaching itself.

| Split | Problems | Checkpoints |
|---|---|---:|
| Training | code_search, l2m | 10 |
| Validation | etl_pipeline | 5 |
| Held-out | xjq, file_backup, env_manager, migrate_configs | 19 |

This is a coherent CLI software family with structured/text inputs and deterministic
outputs. Each problem starts empty; later checkpoints start from that condition's
previous code. Problem chains stay entirely within one split. These are **seven
problems with dependent checkpoints**, not 34 independent tasks. Results will be
preliminary. Configuration planning and migration problems stay together in the test
split. Task-specific languages/operations distinguish ETL, querying, and migration;
shared CLI conventions are the intended transfer opportunity.

`configs/splits.json` records catalog metadata, every public spec hash, and the
cross-split duplicate check. Lowercased word 5-shingle Jaccard rejects overlaps at
0.75. This lexical screen complements the semantic grouping review; it cannot prove
absence of all conceptual similarity. No held-out grading tests or solutions were
inspected to choose these splits.

## Fixed learning loop

1. A fresh, isolated Luna session writes initial `SKILL.md` from **public training
   specs and repository metadata only**, before it receives any task outcomes.
   This avoids using our already-observed `code_search` failures in the initial skill.
2. Run all five validation checkpoints with that initial skill.
3. For each of two rounds: run the ten training checkpoints with the incumbent
   skill; collect traces, official outcomes, and failures; let a fresh Luna writer
   propose a revision; evaluate it on all validation checkpoints.
4. Retain the candidate with more strict checkpoint passes, then higher mean test
   pass fraction. Exact ties retain the incumbent. Invalid revisions are rejected
   without extra inference; initial-writer failure stops the experiment.
5. Freeze both initial and selected learned skill hashes. Evaluate baseline (empty
   skill), initial, and learned on the same 19 held-out checkpoints. Deterministically
   shuffle condition order within each problem. One repeat initially.

The baseline and both skill conditions receive the same prompt, tools, libraries,
and per-checkpoint time budget. Only the designated skill text differs. It is
injected directly into model instructions and mirrored in a read-only `SKILL.md`;
this does not depend on automatic skill discovery. Skills have a 6000-byte limit.
All other installed skills and memories stay disabled. Each checkpoint uses a new
conversation; code, self-authored checks, and prior public specs carry within a
problem, but no conversation history or grader feedback does.

The writer sees training feedback only, in its isolated working directory. It cannot
read the dataset checkout, sibling runs, validation reports, held-out results, or
solutions. Validation selects candidates without exposing validation failures to the
writer. All three conditions' test submissions freeze before any held-out grading;
learning cannot resume once held-out generation has begun.

## Budget for approval

- At most **95 model sessions**: 38 learning/selection sessions (including 3 writers)
  and 57 final-evaluation sessions. Rejected candidates may use fewer.
- Solver limit: 300 seconds/checkpoint. Writer limit: 180 seconds. Maximum model
  execution time is 7h49m, plus audits and local grading; typical runs may be much shorter.
- Rough estimate: **$0.30–$3.00 at API-equivalent token prices**. The lower end scales
  the prior pilot's observed average; the upper end allows substantially harder tasks
  and longer contexts. This is a planning range, not a guaranteed dollar ceiling.
- Actual marginal subscription cash cost is unavailable. No API-key billing is used.
- Account-wide weekly stop floor remains **78% remaining**, with a conservative
  headroom check (normally refusing another session at 79%). Current preparation-time
  reading was 82%. The counter is rounded and may lag; this cannot enforce an exact
  percentage boundary to fractional precision. No reset credits are consumed.
- Hard local session/time ceilings apply even if quota remains. There are no automatic
  retries or extra proposals. Interrupted/infrastructure-failed attempts require review.

Every real session must match an explicitly approved protocol hash and reserves one
session from a persistent ledger before inference. A changed protocol, stale approval,
missing quota information, or a different weekly window stops execution. A process
lock prevents duplicate orchestrators. Partial accounting is saved on failure.

## Why this is not GEPA gskill

We inspected the [official guide](https://gepa-ai.github.io/gepa/guides/gskill/) and
implementation pinned at `d771eb21b5dd3228bc3f567293d2ccfc423fc900`:
[training loop](https://github.com/gepa-ai/gepa/blob/d771eb21b5dd3228bc3f567293d2ccfc423fc900/src/gepa/gskill/gskill/train_optimize_anything.py),
[fitness function](https://github.com/gepa-ai/gepa/blob/d771eb21b5dd3228bc3f567293d2ccfc423fc900/src/gepa/gskill/gskill/swe_fitness_fn.py).
That workflow couples SWE-smith Docker evaluation with API-backed reflection. Replacing
both for SCB plus subscription Codex CLI would add integration work for a two-proposal
pilot. This is a small **custom fixed-budget skill-learning loop**, not a GEPA run.
SCB's official local evaluator remains the grading implementation; no new benchmark
or custom correctness tests were invented.

## Setup and commands

From the repository root, first follow [SCB setup](reproduction.md). Then:

```sh
uv venv intermediate/solver-venv --python 3.12.8
uv pip sync --python intermediate/solver-venv/bin/python configs/solver.lock
python3.12 scripts/kojo.py gauntlet prepare
python3.12 scripts/kojo.py gauntlet plan
python3.12 scripts/kojo.py gauntlet smoke
python3.12 scripts/kojo.py gauntlet audit
```

These commands make **zero model inference calls**. Smoke runs use fabricated scores
in a temporary directory and delete them afterward; they are never benchmark evidence.
Audit directs requests to a local dummy HTTP endpoint and checks native sandbox access.

All conditions use the same pinned PyYAML, lxml, cssselect, and tomli-w libraries,
exposed through read-only runtime files and `PYTHONPATH`. This relaxes the original
smoke pilot's standard-library-only restriction for tasks requiring YAML/XPath.
It is fixed across all new conditions. `configs/gauntlet-grader.lock` pins the official
grader dependencies together with these packages. The base Python executable avoids
a macOS sandbox/venv launcher path-resolution issue. There are no Docker images.

After explicit approval, save `configs/gauntlet-approval.json` using the example file,
with `approved: true` and the exact hash printed by `gauntlet plan`. Then:

```sh
python3.12 scripts/kojo.py tmux run --experiment gauntlet --phase learn --session luna-learning
tmux attach -t luna-learning
# After learning finishes and skills are frozen:
python3.12 scripts/kojo.py tmux run --experiment gauntlet --phase evaluate --session luna-test
tmux attach -t luna-test
```

Direct equivalents are `gauntlet learn` and `gauntlet evaluate`. For a read-only view:

```sh
python3.12 scripts/kojo.py tmux watch --experiment gauntlet --session luna-monitor
```

CLI/grader logs and raw traces live in ignored `intermediate/gauntlet`. Skill revisions,
validation selection, freeze metadata, paired results, published test submissions, and
accounting live in `results/gauntlet`. Results include tokens/time/cost per condition,
learning cost, and paired improvements/regressions. Unknown usage is reported as
unknown, not zero. Cost per successful checkpoint and complete problem chain are
reported separately. Break-even is left unestimated unless a subsequent, larger
experiment establishes a credible future-task success/cost rate.
