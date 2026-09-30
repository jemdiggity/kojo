# Getting Luna to pass `circuit_eval`: effort, prompts, skills and factories

September 29–30, 2026. Model `gpt-6-luna` on SCB `circuit_eval` (8 cumulative checkpoints, 566 tests at
checkpoint 8) in the Kojo factory harness. Goal: pass every checkpoint (8/8 strict). Nothing has yet.

## Summary

- Luna's failures are a **stable tail** of spec-guarantee misses plus **rare collapses** (a broken or unfinished
  program). About 7.6% of build sessions collapse (11 of 144 in the prompt × skill sweep), and one collapse in the
  wrong place (for example the final checkpoint) ends the run.
- **Effort, prompt and skill changes** moved the ceiling to about 545–560/566 but never removed the tail, and each
  has large seed-to-seed variance (tens of tests).
- **Pipeline (factory) changes** looked stronger in a pilot: a sol 6.1 "tester" that writes a spec-only suite plus a
  deterministic check-and-fix loop reached 561/566 with 5 strict checkpoints (previous best: 3). One seed each, so
  this is a lead, not a result.
- We built the machinery to test pipeline ideas cheaply: deterministic `check` stages, `tester`/`plan`/`branch`
  stages, best-of-N, guards and reset arrows, plus ten Luna factories (`docs/factory-language.md`).

## What we tried and what happened

All numbers are checkpoint-8 tests passed out of 566. "Partial" is the mean of each checkpoint's pass fraction.
Runs are in `results/runs/` (on the external drive, see Infrastructure).

### 1. Effort (`luna-eff-01`, no skill, stock prompt, build only)

| Run | Effort | Checkpoint 8 |
|---|---|---|
| `luna-ab-01-circuit-eval-luna` (earlier baseline) | medium | 463 |
| `luna-eff-01-circuit-eval-luna6-medium` | medium | 504 |
| `luna-eff-01-circuit-eval-luna6-high` | high | 549 |

Higher effort helped, but a single seed each. (An earlier version of this analysis labeled the `luna-ab-01`
baseline "low"; its manifest shows it ran at the factory default, medium.)

### 2. Skills (another task's evolution runs, `hc1`–`hc3`, Luna at low effort)

Best single runs of five skills scored 556–560 (`r2d` 560, `r2e` 557, `r2c`/`r3b`/`r3e` 556) against no-skill
baselines of 371–463. The same skill (`v1-spec-checklist`) scored 555 and 511 on two runs, and 99.6% partial
pass was the ceiling. Their analysis found the tail is mostly "a numbered guarantee never run on an input that could
violate it" (absorption through a named wire, `--fanin-limit`, cone ordering, invalid-seed labeling), skills often
not followed (18 of 26 failure pairs), and regressions never repaired.

### 3. Prompt × skill sweep (`pf-06`, Luna low effort, 3 seeds per arm)

Question: is Luna's stock prompt line "Do not add or run tests unless the user asks" (sol 6.1's prompt says the
opposite) the cause? Six arms crossed three base prompts with two skill conditions.

| Base prompt | Skill | Checkpoint 8 by seed | Partial mean ± sd | Collapsed sessions |
|---|---|---|---|---|
| Sol 6.1 full prompt | none | 521, 504, 500 | 91.4 ± 3.3 | 0 |
| Stock + sol's two testing lines | none | 488, 541, 535 | 89.7 ± 7.7 | 2 |
| Stock | none | 412, 529, 533 | 81.0 ± 13.7 | 4 |
| Sol 6.1 full prompt | `r3e` | 542, 545, 182 | 81.1 ± 27.9 | 2 |
| Stock + sol's testing lines | `r3e` | 558, 1, 550 | 90.5 ± 7.8 | 1 |
| Stock | `r3e` | 547, 534, 178 | 81.9 ± 18.6 | 2 |

Findings, with 3 seeds per arm so mostly directional:

- Nothing reached 566; the best run was 558. Strict checkpoints per run never exceeded 3.
- The sol full prompt gave the best and most stable no-skill result. The stock prompt with no skill **gave up at
  checkpoint 2 in all three seeds** (`eval` not implemented); the sol prompt did not.
- The prompt changed behavior modestly: program runs per session rose from 2.2 (stock) to 2.9 (test lines) to 4.6
  (sol full). Without a skill Luna almost never wrote tests.
- The `r3e` skill (permanent regression suite) raised the ceiling (534–558 in clean runs) but four of its nine
  runs collapsed. Two collapses were plain `IndentationError` syntax errors (1/430 at checkpoint 4; 1/566 at
  checkpoint 8, from a run that had been at 512/529). A compile or a single spec-example run would have caught both.
- The skill choice was not well justified: `r3e` was picked for its regression suite, not because it scored best
  (`r2d` scored higher). Conclusions about "skills" from this sweep rest on one skill.

The two prompts differ by about 50 lines: a rewritten personality/writing-style block, PR-description guidance,
persistence lines ("continue work without ending the turn"), tool and skill handling, and the two testing lines.
The exact texts are in `configs/base-instructions/`.

### 4. An independent second opinion

A fresh Fable subagent reviewed the data and argued the limiting factors are (a) wipeout sessions with no retry and
(b) Luna never writing tests, recommending a deterministic gate with retry, a persistent-suite revise stage, and a
mixed QA stage. Two of its claims did not hold up when checked: it said only Astra had passed the problem (sol 6.1
also passed 8/8 at low, medium and high effort in `20260929-sol61-circuit-effort-04-*`), and it said Luna ran the
program in the baseline (the transcripts show only reads and `py_compile` there). Its variance advice (report
catastrophe rate, strict checkpoints, conditional failure counts and failing-test IDs, with 5+ seeds) is what we used.

### 5. Factory (pipeline) machinery and a pilot

Failure classes from the sweep were: giving up, shipping a broken program, unrepaired regressions, and the
guarantee tail. We added (all in `factory_spec.py`, `factory.py`, new `checks.py`, `docs/factory-language.md`):

- Deterministic `check` stages: `smoke` (compile, `--help`), `examples` (runs the examples extracted from the public
  specs), `suite` (a model-written suite, with regressions against the previous accepted code reported first),
  `repro` (runs a reviewer's claimed failures, keeps only confirmed ones), `diff` (differential test against a
  second implementation).
- New stage kinds `tester` (writes a growing suite from specs only, never sees code), `plan`, `branch`; attributes
  `xN`/`by` (best of N), `guard` (roll back if the score drops), `prompt`; and the `reset` arrow (reroll from the
  checkpoint's starting code).
- Ten Luna factories (`configs/factories/luna-*.factory`) and a 30-run batch (`fx-02-factory-grid`).

Validation without inference: run against real saved submissions, `smoke` fails both shipped-`IndentationError`
runs (0/3) and passes good runs; `examples` fails those two (1/23, 1/13) and both runs that gave up at
checkpoint 2 (1/2), and passes the good runs (one 545 run misses 1 of 23). Extraction coverage on `circuit_eval` is
23 usable examples by checkpoint 8 (12 skipped because fixtures are not defined in the specs), and almost none for
the optimizer's numbered guarantees, which is what the tester-written suite is for.

Pilot (`fx-02` seed 1, sol 6.1 base prompt; the controls are the `pf-06` sol-full build-only runs at 500–521):

| Factory | Checkpoint 8 | Partial | Strict | Model sessions | Cost |
|---|---|---|---|---|---|
| `luna-tester-suite` | 561 | 99.5% | 5/8 | 35 | $1.46 |
| `luna-best-of-3` | 560 | 99.6% | 2/8 | 32 | $1.25 |
| `luna-vs-sol-diff` | 544 | 97.8% | 0/8 | 34 | $2.39 |
| `luna-verified-review` | 486 | 95.5% | 3/8 | 48 | $13.90 |

Astra review sessions made `luna-verified-review` the most expensive arm and one of the weakest (checkpoint 7
collapsed to 452). The other 26 runs of the grid (`configs/batches/fx-02-rest.json`) have not been run.

## Infrastructure changes made along the way

- `--base-instructions FILE` for Codex runs (recorded in the manifest as a custom override); `configs/base-instructions/`.
- Cached worktree setup no longer refuses to run because another worktree has an active run.
- Dashboard: partial pass and leaderboard metrics now divide by the problem's checkpoint count, so an unfinished
  run is not shown as 100%; batch and run filter lists are twice as wide and aligned with the columns below.
- Run data moved to the external drive `/Volumes/VHS/kojo-data`; the main checkout's `intermediate/`,
  `results/runs` and untracked comparison folders are symlinks into it. A gitignored `.env` sets `KOJO_DATA_DIR`.
  The drive must be attached for runs to write.
- Codex was rewriting `~/.codex/skills/.system` under our audits (different Codex builds fighting over the shared
  folder), which killed several runs before upstream pinned 0.159.1 and disabled bundled skills.

## Caveats

- Most comparisons are single seeds or three seeds; the prompt × skill sweep's per-arm standard deviations run from 3
  to 28 points. Differences smaller than that are noise.
- The pilot was one seed per factory. The example extractor and the tester's cases can be wrong; a failing suite case
  may be a tester mistake, and the check log says so to the fixer.
- Tester and branch stages had only been exercised with fake inference before the pilot.

## Next steps

1. Launch the rest of `fx-02` (26 runs) and add seeds for `luna-tester-suite` and `luna-best-of-3` to get standard
   deviations and a strict-checkpoint distribution.
2. Sharper tester prompts for the optimizer guarantees, and a two-stage gate (`smoke` then `suite`) to remove
   syntax-error collapses.
3. Re-run the skill dimension properly (`r2d`, `r2e`, `r2c`, `r3b` against `r3e` and a no-skill control), ideally
   on top of the best factory.
