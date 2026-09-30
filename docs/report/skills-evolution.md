# Skill hill-climbing on SCBench: what the runs actually show

Status: analysis of runs recorded up to 2026-09-30 on branch `task-d2f29b37`. All
scores below were regenerated from `results/runs/*/scores.json` with
`scripts/scb_rank.py` (data root `/Volumes/VHS/kojo-data`), from the official
per-checkpoint `grading/evaluation.json` files under `intermediate/runs/`, and from
the regrade outputs in `.tmp/regrade/*/regrading.json`. The per-round narrative
draws on the fresh-agent analyses checked in under `skills/*/round*/ANALYSIS*.md`;
where this report disagrees with those files or with prior working assumptions it
says so. A machine-readable table of every run cited here is in
[`run-scores.csv`](run-scores.csv).

## 1. Summary

- **dynamic_config_service_api is the one clear win.** Sonnet 5.5 (medium) scores
  68.4–70.5 % with no skill (four runs). One rule found in round 1 (a "current
  value" read of an identity that exists must succeed with a typed sentinel, never
  404) lifts a run to ~92 % because 46 of 76 checkpoint-3 tests and 15 of 81
  checkpoint-4 tests are `pytest.skip`ped when that read fails. Round 3 made the
  rule the first section of the skill and all five variants held it; the best
  single run, `skills/sonnet-dcs/round3/d3b-inherit`, scored **96.0 %** (47/47,
  92/93, 73/76, 72/81). Its residual failures are almost entirely the class the
  analyses call a spec-vs-grader ceiling.
- **database_migration is saturated for this builder.** Five no-skill runs span
  92.5–95.3 % (mean 93.8, sd 1.4). No skill beat the best control; the best skill
  run (`s2c-state-reader`, 95.7 %) is 0.4 points above the control in the same
  batch. Two round-1 skills collapsed the score to 53 % and 70 % through a single
  wrong instruction, and a round-2 wording harmed four of five variants by ~3.5
  points. About half of the residual failures are spec ambiguities the grader
  resolves one way; the analyses put the generic-skill ceiling near 97 %.
- **circuit_eval with Luna (gpt-6-luna, low effort) went from 61–72 % to 99.6 %**
  over two rounds; the single biggest effect was getting the builder to run the
  spec's examples at all. The top four skills are within noise of each other, and
  a replicate of the 99.6 % skill scored 91.5 %. Sonnet 5.5 (medium) scores 99.9 %
  on the same problem with no skill, so it was not used for the Sonnet climb.
- **The Hard-problem baselines were partly a grading artifact, not a model
  failure.** Five of ten problems (metric_transform_lang, meshctl, sheeteval,
  mocked_http, sith) scored 0–2 % officially because their tests launch the
  program from a temporary working directory and the grader passes a relative
  entry file and a relative interpreter path. Regrading with the corrected launcher
  gives 94.5, 92.7, 91.6, 81.0 and (sith, regraded for this report) 94.3 %.
  **sith is not the real failure it was believed to be**; see §3.4.
- Everything is n=1 per condition except where stated. The per-problem noise floor
  (2.8 points on database_migration, ~2 points on dynamic_config, 8–11 points on
  circuit_eval with Luna) is larger than most of the differences between skills.

## 2. Setup, method and validity

### 2.1 Benchmark and scoring

SCBench problems are multi-checkpoint specifications (4–8 checkpoints). Each
checkpoint is a fresh CLI conversation in a persistent workspace that inherits the
run's own code; the builder sees only the current checkpoint's spec. After each
checkpoint the hidden tests for that checkpoint and all earlier checkpoints are run
against the saved submission. The score used throughout is **partial pass**: the
mean over checkpoints of passed/total, with totals including earlier-checkpoint
regression tests and with skipped tests counted as not passed. "Strict" counts
checkpoints with every test passing. A bug introduced at checkpoint k is therefore
paid for at every later checkpoint, which is why a single early decision can move
the score by 20 points.

### 2.2 Builder and skill delivery

- Builder factory `sonnet-medium` (`configs/factories/sonnet-medium.factory`):
  Claude Sonnet 5.5 at medium effort, build stage only, no review or fix stages,
  1800 s per session, network enabled (the manifest of every run records this).
  The Luna climb used `luna-low` (gpt-6-luna, low effort, Codex CLI 0.159.1).
- A skill set is a directory with one `SKILL.md` (frontmatter `name` +
  `description`, body under 6000 bytes, no task names, tests or expected outputs).
  It is delivered natively (Claude Code skill / Codex `.agents/skills`); the model
  decides whether to open it. Skill sizes: 2.1–4.6 KB for the Sonnet families,
  4.3–6.0 KB for Luna.
- Every run records the skill-set SHA in `manifest.json` and `accounting.json`;
  run IDs embed the first ten hex digits.

### 2.3 The hill-climb loop

Per problem and round: a fresh Fable 5.1 agent analysed the previous batch
(transcripts, failure detail from `scripts/scb_failures.sh`, hidden tests) and wrote
an `ANALYSIS*.md`; a second fresh Fable 5.1 agent wrote five candidate skills; all
five plus a no-skill control (and, from round 2, the previous best) were run once
each with `scripts/scb_suite.py`. The next round's inputs were the analysis and the
top three skills. Rounds run: database_migration 2 (batches sm1, sm2, baselines
sm0a/sm0b), dynamic_config_service_api 3 (dc2, dc3, dc4; baselines dc1a/dc1b),
circuit_eval/Luna 3 (hc1, hc2b, hc3; hc4p replicates). No analysis file exists for
the dc4 batch; §3.2 covers it from the run outputs.

### 2.4 Validity caveats

1. **Single runs.** Every skill/problem cell is one run. Measured no-skill spread:
   database_migration 92.5–95.3 (n=5), dynamic_config 68.4–70.5 (n=4), circuit_eval
   Luna 61.2 and 72.2 (n=2). Replicates of the same skill: `d1a-empty-state` 91.8,
   92.8, 69.4; `s1c-state-errors` 95.4, 94.3; Luna `v1-spec-checklist` 98.9, 91.7;
   Luna `r2d-postcondition-fidelity` 99.6, 91.5. Differences under ~3 points on
   the Sonnet problems and under ~10 on Luna are not resolvable with n=1.
2. **Same-task, not held-out.** Every skill was written from failure analyses of the
   problem it was then scored on. The analysts were told not to name fields,
   endpoints or tests, and the harness rejects problem names in skills, but the
   rules are still shaped by the grader of that one problem. Nothing here is
   evidence of transfer (see §6).
3. **Grading launcher artifacts.** Two defects in the grading launcher produced
   zero scores unrelated to the submission: (a) `scripts/scb_entrypoint.py`
   resolved a relative entry file against the current directory, which is wrong
   for tests that `cd` to a temporary directory; (b) grading could write
   `__pycache__` into the submission, which the snapshot check treats as a mutated
   submission. The uncommitted diff to `scripts/scb_entrypoint.py` (resolve the
   entry file against `SCB_SUBMISSION_ROOT`; support directory entrypoints from
   another cwd) and `src/kojo/gauntlet.py` (export `SCB_SUBMISSION_ROOT`, set
   `PYTHONDONTWRITEBYTECODE=1`) addresses both. **Still open:** the official grader
   also passes the interpreter as the relative path `.venv/bin/python`
   (`src/kojo/gauntlet.py` line 207; visible in every official `evaluation.json`,
   e.g. `.venv/bin/python /…/scb_entrypoint.py sith`), so for problems whose tests
   change directory the official path still fails with
   `FileNotFoundError: '.venv/bin/python'` (38 of 39 sith checkpoint-1 tests in
   hd2). `scripts/scb_regrade.py` sidesteps this by substituting an absolute
   interpreter, which is why the regraded numbers in §3.4 are the ones to trust.
   None of this affects circuit_eval, database_migration or
   dynamic_config_service_api, whose tests run from the submission directory.
4. **Interrupted batches.** The hd1 batch was cancelled (`KeyboardInterrupt` in
   `.tmp/hd1.log`) before dynamic_buffer, sith and test_translator finished; hd2
   re-ran those three to completion. hd1 rows for those problems are partial. The
   sheeteval regrade crashed at checkpoint 7 on a stale
   `intermediate/regrading/sheeteval/checkpoint_7` directory (`FileExistsError`),
   so its regraded score covers 6 of 7 checkpoints.
5. **Skill adoption is not guaranteed.** Codex opened the Luna skill in 3–8 of 8
   sessions depending on variant; Sonnet loaded it in every checkpoint of every
   run except one (`d2b-accept`, checkpoint 3), which behaved as a no-skill run.
   Several Luna-low sessions bailed out in 10–16 s having read the code and
   written nothing, with or without a skill (about 3 in 12 at checkpoint 2).
6. **Local re-runs of the dynamic_config tests disagree with official grading.**
   `scripts/scb_failures.sh` on the best dc4 submission reports 54 failures at
   checkpoint 3 where the official grader reports 3. The cause was not
   investigated; §3.2 uses only the official `evaluation.json` files.

## 3. Results

### 3.1 database_migration (Sonnet 5.5 medium; 5 checkpoints, 39/62/87/117/137 tests)

No-skill runs, all batches:

| run | partial | per checkpoint |
|---|---|---|
| sm0a | 95.1 | 39/39 60/62 84/87 108/117 123/137 |
| sm0b | 92.5 | 39/39 56/62 80/87 106/117 123/137 |
| sm1 none | 93.5 | 39/39 58/62 82/87 107/117 121/137 |
| sm2 none | 95.3 | 39/39 60/62 84/87 109/117 123/137 |
| 20260928-…-sonnet55-medium-01 (older launcher, same build model/effort) | 92.5 | 39/39 58/62 82/87 103/117 119/137 |

Mean 93.8, sd 1.4, range 2.8. Builder time 340–500 s per run (all five
checkpoints), API-equivalent cost $2.0–3.0.

Round 1 (batch sm1):

| skill | partial | per checkpoint | note |
|---|---|---|---|
| s1c-state-errors | 95.4 | 39/39 60/62 84/87 110/117 123/137 | best; edge is one line, "emit the spec's exact shape on output" |
| none | 93.5 | 39/39 58/62 82/87 107/117 121/137 | control |
| s1d-regression-script | 93.4 | 39/39 58/62 82/87 107/117 120/137 | 300-line check.sh built; +30–70 % time, no gain |
| s1a-enumerate-examples | 92.2 | 39/39 57/62 81/87 105/117 118/137 | NOTES.md checklist never created |
| s1e-one-page-card | 70.2 | 30/39 41/62 58/87 84/117 95/137 | collapse: "extra keys are free" |
| s1b-union-echo | 53.3 | 20/39 31/62 46/87 65/117 78/137 | collapse: same rule plus "record it in NOTES.md" |

Round 2 (batch sm2):

| skill | partial | per checkpoint | note |
|---|---|---|---|
| s2c-state-reader | 95.7 | 39/39 60/62 84/87 111/117 124/137 | cheapest run (304 s, $2.03); fixed object-wrapped stored state |
| none | 95.3 | 39/39 60/62 84/87 109/117 123/137 | control |
| s1c-state-errors (rerun) | 94.3 | 39/39 58/62 82/87 109/117 124/137 | |
| s2e-base-control | 92.3 | 39/39 56/62 80/87 107/117 120/137 | shared "no fields beyond the spec" harm |
| s2d-replay-audit | 92.2 | 39/39 56/62 80/87 106/117 121/137 | same |
| s2b-parity-identity | 92.1 | 39/39 56/62 80/87 105/117 121/137 | same; its own levers were worth +0.45 |
| s2a-exact-shape | 91.9 | 39/39 56/62 80/87 106/117 119/137 | same; key-set diff never run |

Residual failures at checkpoint 5 are the same list in the control and the best
skill run (13 vs 12 tests: `default_value` bound as a literal, transform on a
missing column, three `rollback_drop_*` tests, five dependency tests,
`validate_without_migrations_dir`). The round-2 analysis attributes 51 % of the
223 failed test-runs in sm2 to spec ambiguity or grader disagreement and estimates
a realistic generic-skill ceiling of 96.8–97.2 %.

### 3.2 dynamic_config_service_api (Sonnet 5.5 medium; 4 checkpoints, 47/93/76/81 tests)

No-skill runs: dc1a 68.8, dc1b 69.7, dc2 none 68.4, 20260929-…-sonnet55-medium-02
70.5 (mean 69.4, sd 0.9). Per checkpoint the shape is always 45/47, 87–91/93,
24–26/76, 38–47/81. Builder time 950–1450 s per run, cost $4.3–6.2.

**The gate.** Official `evaluation.json` for dc1a: checkpoint 3 = 25 passed,
5 failed, **46 skipped**; checkpoint 4 = 43 passed, 23 failed, **15 skipped**. The
test helper reads "current active version" for a name whose versions exist but
none is active; unless that returns HTTP 200 with an integer version it skips, and
dependent tests skip in turn. Both baselines returned 404 there and used `null` as
the sentinel, and both documented that choice in their answer. The round-1 analysis
patched the two baselines (~330 bytes) and re-graded: 68.8→~90.7 and 69.7→~91.6,
i.e. the gate alone is worth ~21–22 points. The realised effect in round 1 was
+23.4 (d1a 91.8 vs none 68.4 in the same batch).

Round 1 (batch dc2):

| skill | partial | per checkpoint | gate held |
|---|---|---|---|
| d1a-empty-state | 91.8 | 45/47 90/93 70/76 67/81 | yes (0 skipped) |
| d1d-combined-card | 71.4 | 45/47 91/93 24/76 49/81 | no (had 0 in store, then added a 404 branch) |
| d1e-replay | 70.5 | 45/47 91/93 25/76 45/81 | no (never curled the read; replay step never run) |
| d1b-error-set | 70.2 | 45/47 91/93 26/76 43/81 | no |
| d1c-exact-words | 70.0 | 47/47 93/93 25/76 38/81 | no; but fixed cp1/cp2 (nested deep-merge inheritance) |
| none | 68.4 | 45/47 91/93 25/76 38/81 | no |

Round 2 (batch dc3; each variant = d1a core + one lever):

| skill | partial | per checkpoint | note |
|---|---|---|---|
| d1a-empty-state (replicate) | 92.8 | 45/47 90/93 73/76 67/81 | gate held |
| d2a-inherit | 92.1 | 47/47 93/93 68/76 64/81 | gate held; deep-merge fixed cp1/cp2 |
| d2e-lean | 90.8 | 45/47 86/93 72/76 65/81 | gate held; cp2 loss = conditional field emitted as null |
| d2d-errorset | 85.5 | 45/47 91/93 47/76 70/81 | gate held, then its ordering rule cost ~25 tests |
| d2c-alias | 70.2 | 45/47 90/93 25/76 45/81 | gate failed (skill loaded, verify curl never run) |
| d2b-accept | 70.2 | 45/47 91/93 24/76 45/81 | gate failed (skill not invoked at cp3) |

Round 3 (batch dc4; gate rewritten as a two-line "Invariant" first section,
imperative description, verify tied to the final summary):

| skill | partial | strict | per checkpoint | added lever |
|---|---|---|---|---|
| **d3b-inherit** | **96.0** | 1/4 | 47/47 92/93 73/76 72/81 | deep-merge inheritance |
| d3e-accept | 94.6 | 2/4 | 47/47 93/93 70/76 70/81 | liberal acceptance + "literal for errors, liberal for inputs" bridge |
| d3c-omit | 94.3 | 2/4 | 47/47 93/93 70/76 69/81 | conditional fields omitted, never null |
| d3d-exact-words | 93.4 | 2/4 | 47/47 93/93 71/76 65/81 | do not widen state sets |
| d3a-gate-lean | 91.9 | 0/4 | 45/47 90/93 72/76 65/81 | none (core only) |
| d1a-empty-state (2nd replicate) | 69.4 | 0/4 | 44/47 90/93 26/76 43/81 | gate failed (46 skipped) |

All five round-3 variants held the gate (n=5, zero skipped tests). The round-1
wording (`d1a`) held it in 2 of 3 runs; the round-2 analysis counted 5 of 7 for
the d1a-derived core across dc2+dc3. Round-3 mean 94.0 vs round-2 mean of the
gate-holding runs 90.3.

Residual failures of d3b from the official evaluation: checkpoint 2, one test
(`yaml_non_string_key`); checkpoint 3, three (`diff_ordering_and_includes_sorted`,
`stale_base_proposal`, `merge_stale_base`); checkpoint 4, nine (eight
`evaluate_*` policy tests plus `evaluation_timeout`). The round-1 and round-2
analyses classify the checkpoint-4 evaluate cluster as the partial-scope lookup
ceiling (reference does subset matching; the checkpoint-1 spec says exact match)
and the stale-base test as a grader quirk. If those are indeed unfixable without
leakage, d3b is within ~2 points of the ceiling; the 1.4-point spread between
d3b, d3e and d3c is not resolvable at n=1.

### 3.3 circuit_eval with Luna (gpt-6-luna low; 8 checkpoints, 36…566 tests)

| batch | skill | partial | note |
|---|---|---|---|
| hc1 | none | 61.2 | zero executions of the program in any build session |
| hc1 | v1-spec-checklist | 98.9 | three-pass checklist; opened 8/8 sessions |
| hc1 | v4-regression-guard | 97.8 | |
| hc1 | v2-run-examples | 89.3 | testing-framed description, opened 4/8 |
| hc1 | v5-terse | 76.3 | |
| hc1 | v3-error-contract | 70.0 | |
| hc2b | r2d-postcondition-fidelity | 99.6 | 6 final failures |
| hc2b | r2c-combination-grid | 99.3 | |
| hc2b | r2e-combined-tight | 99.1 | read the skill 3/8 times; workspace artifacts carried the habit |
| hc2b | v1-spec-checklist (replicate) | 91.7 | one parser choice at cp3 cost 45 tests |
| hc2b | r2a-persistent-suite | 87.7 | suite of 8 trivial cases caught nothing |
| hc2b | r2b-shared-code-guard | 62.9 | two 10-s bail-out sessions, skill unread |
| hc3 | r3b-discriminating-grid | 99.4 | |
| hc3 | r3e-light-suite | 99.4 | |
| hc3 | r3d-guarantee-fixtures | 91.7 | |
| hc3 | r3a-no-known-failure | 84.8 | |
| hc3 | none (replicate) | 72.2 | |
| hc3 | r3c-rewrite-safe-tokenizer | 70.2 | cp4 collapse (203/430) |
| hc3q/hc3r | external Pocock skills (`skills/external/pocock*`) | 79.0 (5 cps, interrupted), 75.4 (7 cps) | off-the-shelf control |
| hc4p | r2d-postcondition-fidelity (replicate) | 91.5 | cp4 loss of 60 tests carried to cp8 |
| hc4p | pocock (replicate) | 62.0 | |

The round-4 analysis (`skills/luna-hc/round4/ANALYSIS_99.md`) inventories the 45
failing test instances across the five ~99 % runs: 18 root causes, of which 18 of
26 run/failure pairs were rules already in the skill and not followed, 6 not
covered, 1 induced by the skill itself. Cross-checks on other builders: Sonnet 5.5
medium with no skill scores 99.9 % (20260928-circuit-eval-sonnet55-medium-01); Sol
6.1 medium scores 100 % with and without `r2d` (20260929-sol61-medium-skills-01).
Cost per Luna run: $0.03–0.16 API-equivalent (subscription), 830–1880 s.

### 3.4 Hard-problem no-skill baselines (Sonnet 5.5 medium)

| problem | cps | official (scb_rank) | regraded (fixed launcher) | reading |
|---|---|---|---|---|
| rejector | 5 | 94.3 (hd1) | – | real; 6 failures at cp5 |
| metric_transform_lang | 5 | 0.0 (hd1) | **94.5** (46/46 98/98 162/164 176/226 71/74) | launcher artifact |
| meshctl | 8 | 0.0 (hd1) | **92.7** (77/83 … 74/78) | launcher artifact |
| sheeteval | 7 | 1.6 (hd1) | **91.6** over 6 of 7 cps (23/24 … 131/144); cp7 regrade crashed | launcher artifact |
| dynamic_buffer | 4 | 90.0 (hd2: 30/30 44/50 92/104 144/172); hd1 interrupted after 28/30 | – | real |
| dag_execution | 3 | 89.3 (hd1: 31/33 36/41 44/51) | – | real |
| mocked_http | 8 | 0.0 (hd1) | **81.0** (24/29 … 163/200) | launcher artifact; residuals real (startup-failure expectations, 500s) |
| recli | 8 | 79.8 (hd1: 34/34 … 153/255) | – | real; most late failures are "Container runtime is not installed" (the submission calls a real runtime) |
| test_translator | 8 | 36.3 (hd2: 90/102 217/609 311/703 602/1021 286/1582 287/1790 292/1960 295/2069); hd1 interrupted at 48.6 over 5 cps | – | real; cp5 regressed 511 tests on one decision ("discovery failed: disallowed statement") |
| sith | 6 | 1.6 (hd1, 3 cps) / 1.1 (hd2) | **94.3** (38/39 73/75 105/108 134/146 172/186 204/228) | launcher artifact; see below |

**sith correction.** The working assumption was that sith's ~1 % was a real
failure (32 of 39 checkpoint-1 tests failing). Both numbers are launcher
artifacts. The official hd2 grade fails 38/39 with
`FileNotFoundError: '.venv/bin/python'` because 33 of the 52 `cwd=` uses in sith's
tests run the program from `tmp_path`. The "32 of 39" figure came from
`scripts/scb_failures.sh`, which uses an absolute interpreter but does not export
`SCB_SUBMISSION_ROOT`, so it reproduces the relative-entry-file defect instead
(`No such file or directory: '<tmp>/sith'`; the 7 passing tests are the ones that
run with `cwd=root`). Re-running the same checkpoint-1 tests against the hd2
submission with `SCB_SUBMISSION_ROOT` set gives **38 passed, 1 failed**
(`test_complete_names_are_visible_on_their_definition_line`). A full regrade of
hd2 with `scripts/scb_regrade.py hd2-sith-sonnet-medium-none --output
.tmp/regrade/sith` (source hashes verified before and after, as for the other
four) gives **94.3 %** over all six checkpoints, strict 0/6, with failures growing
from 1 at checkpoint 1 to 24 at checkpoint 6. Those residuals are ordinary
completion-engine disagreements and have not been analysed. The user's intent for
sith should be re-read against these numbers rather than the 1 % ones.

Two of the twelve Hard problems (`eve_*`) were excluded because they need an SDE
asset adapter the harness lacks (`scripts/scb_suite.py` comment).

## 4. What helped and what hurt

Evidence is the transcripts and failure inventories in the ANALYSIS files plus the
score deltas above; each item names the run(s) that support it.

**Helped**

- *Gate-first invariants.* Putting the one load-bearing rule at the top, as a
  two-line invariant ("for an identity that exists every current-value read
  succeeds; nothing-yet is the integer 0"), and tying its verification to the final
  summary took the gate hold rate from 2/3 (d1a) and 5/7 (d1a core in dc2+dc3) to
  5/5 (dc4). Wording mattered more than length: the d1d/d1e variants contained the
  same facts and still added a 404 branch; d1a's "This is a normal state, not an
  error. Do not reuse the not-found path for it" is what the round-1 batch analysis
  identifies as load-bearing.
- *One-line code-shaping rules.* `s1c`'s "accept every plausible reading on input,
  emit the spec's exact shape on output" accounts for its entire edge (60 vs 58 at
  cp2, carried four times). `d2a`/`d3b`'s deep-merge section fixed the cp1/cp2
  inheritance tests in every run that carried it (47/47, 93/93). `d1d`'s liberal
  "must expose A and B = A and/or B" wording fixed six tests; `d2b`'s paraphrase of
  the same idea with a "no rejection example" escape hatch did not.
- *Running the spec's examples (Luna).* The single largest effect in the whole
  study (61 → 98 on circuit_eval) came from a skill that reframed running examples
  as part of implementing, overriding Codex's stock "do not run tests" instruction.
  Every Luna session that opened the skill ran the examples; the no-skill run never
  executed the program.
- *Copying spec sentences verbatim into a checklist* (v1b passed the hex-padding
  tests, r2a's paraphrase failed them), and *output-contract self-checks* (round
  trip, idempotence, kind-based printing) in `r2d`, the only run passing all five
  optimizer postcondition tests together.
- *Workspace artifacts as the durable channel.* `r2e` read its skill in 3 of 8
  sessions and still scored 99.1 because the `regress/` files it left behind carried
  the habit into sessions that never opened the skill.

**Hurt**

- *"Extra keys are free" (s1b, s1e; −40 and −23 points).* About half the
  database_migration tests compare event streams by exact list equality. The
  round-1 lever "the example is a floor, echo every identifying field" was inferred
  from one failing test without checking the grader's comparison semantics; the
  skill turned a mild model tendency into policy, and `s1b`'s "record decisions in
  NOTES.md so later checkpoints preserve it" locked the mistake in for all five
  checkpoints.
- *The over-correction (s2a, s2b, s2d, s2e; −3.5 points each).* "Do not add fields
  to emitted records beyond what the spec shows" made the model drop an
  operation's own identifier keys for record types that have no example (16
  test-runs). `s1c`'s narrower "no extra metadata on persisted records" did not
  trigger it. Same lesson twice: shape rules written without reading the grader.
- *Ordering rules (d2d; −7 points, cp3 47/76).* "Order of checks: identity
  existence → always-preconditions → body validation → business rules" made a
  policy-set call require an existing identity; tests that set policy first got
  404 and everything downstream cascaded (~25 tests).
- *Process mandates are ignored or cost time without return.* NOTES.md checklists
  were never created (s1a, s1c, s1e); "run spec examples verbatim" was skipped in
  every Sonnet run; "hand-craft a stored record first" never happened (s1c, s2c);
  the key-set diff never ran (s2a); replay steps never ran (d1e, s2d). `s1d`
  genuinely built a 300-line check script, spent 30–70 % more time and gained
  nothing because it replayed the agent's own reading of the spec. On Luna,
  "extend, never rewrite" was ignored by every run at cp3; "copy to last_good" and
  "three attempts then a smaller step" were never exercised.
- *Escape hatches.* Finish sections that let the builder "name the item left
  unverified" were taken after one attempt (v2 cp3, r2c cp4 "stopping here with
  that issue unresolved", r2e cp1). Descriptions framed as testing lowered Codex
  adoption (v2 opened 4/8).
- *Lever-specific verify clauses* crowded out the gate check (d2c, n=1), and one
  Luna rule ("fix the reader when the spec allows the construct") induced a new
  failure (F9 in the round-4 analysis).

## 5. Saturation and headroom

Sonnet 5.5 medium, no skill, per problem (best available grade):

| problem | no-skill | best skill | noise floor | headroom for a generic skill |
|---|---|---|---|---|
| circuit_eval | 99.9 | – | – | none |
| database_migration | 93.8 ± 1.4 (n=5) | 95.7 (n=1) | 2.8 | ≤ 3 points, ~half of residual failures are spec/grader disagreements; not measurable at n=1 |
| dynamic_config_service_api | 69.4 ± 0.9 (n=4) | 96.0 (n=1) | ~2 | closed by the gate rule; ≤ 2 points left if the evaluate cluster is a ceiling |
| rejector | 94.3 | – | ? | small (6 tests) |
| metric_transform_lang | 94.5 (regrade) | – | ? | cp4 176/226 is the only soft checkpoint |
| meshctl | 92.7 (regrade) | – | ? | 5–10 %, spread evenly across checkpoints |
| sheeteval | 91.6 (regrade, 6/7 cps) | – | ? | ~8 %, spread evenly |
| dynamic_buffer | 90.0 | – | ? (hd1 partial 28/30 agrees) | ~10 % |
| dag_execution | 89.3 | – | ? | ~10 % over 3 checkpoints |
| mocked_http | 81.0 (regrade) | – | ? | ~19 %; failures are real server-behaviour disagreements |
| recli | 79.8 | – | ? | ~20 %; one systematic decision (real container runtime) dominates late checkpoints |
| test_translator | 36.3 (hd2, 8 cps) / 48.6 (hd1, 5 cps) | – | ~12 on the shared first 5 cps | large; one cp5 decision cost 511 tests, so this is the dynamic_config pattern (one gate) rather than diffuse quality |
| sith | 94.3 (regrade) | – | ? | ~6 %, growing with checkpoint (1 → 24 failures) |

Reading: after the launcher fix the Hard set is not hard for this builder in the
way the official numbers suggested. Seven of ten problems are at 89–95 % with no
skill, which is inside or near the band where database_migration proved
unclimbable at n=1. The three with real headroom (test_translator, recli,
mocked_http) each show a single systematic decision carried across checkpoints,
which is the shape of failure a skill fixed on dynamic_config, but each is one
run and none has a failure analysis yet.

## 6. Generalization status and recommended next experiments

**What is known about transfer.** Nothing positive yet.

- The Luna skill `r2d` on other builders and problems: Sol 6.1 medium 100 %/100 %
  on circuit_eval (saturated); database_migration 95.7 with `r2d` vs 94.8 without
  (inside noise); dynamic_config 66.6 vs 64.7 (the gate failed in both, 26/76).
  Luna-low with the Luna skills on database_migration: r3e 93.8, r3b 93.7, r2d 91.6
  (4 of 5 checkpoints), with no Luna baseline because the `dbm1` no-skill run was
  aborted by the harness audit ("Ambient skill catalog present").
- The Sonnet skills (`cli-software` for database_migration, `service-spec` for
  dynamic_config) have not been run on any other problem.
- External off-the-shelf skills (Pocock) scored below the no-skill baseline on
  circuit_eval with Luna (62–79 vs 61–72), which says only that generic engineering
  skills do not substitute for problem-shaped rules at low effort.

**Recommended next experiments, in order.**

1. *Repair grading before anything else.* Make the interpreter path absolute in
   `src/kojo/gauntlet.py` (or resolve `.venv/bin/python` against
   `SCB_SUBMISSION_ROOT` inside `scripts/scb_entrypoint.py`), commit the launcher
   fixes so `harness_sha256` in new manifests reflects them, re-run the sheeteval
   checkpoint-7 regrade into a fresh directory, and adopt the regraded numbers as
   the Hard baselines. Until then every new Hard-problem run whose tests change
   directory will grade at 0.
2. *Replicate before believing.* The two claims worth money are "d3b ≈ 96 on
   dynamic_config" and "no skill beats control on database_migration". Run 3 seeds
   of control vs 3 seeds of `d3b-inherit` (and `d3e`, `d3c`) on dynamic_config, and
   3 vs 3 of control vs `s2c-state-reader` on database_migration. Judge mean,
   spread and gate hold rate, not the single best run. Cost: ~$5.5 and ~20 min per
   dynamic_config run, ~$2.5 and ~6 min per database_migration run.
3. *Held-out test of the two skills.* `service-spec` (d3b) on mocked_http (an HTTP
   service with startup and error-behaviour tests) and, as a negative control, on
   recli; `cli-software` (s2c or s1c) on meshctl and recli. Score against the
   regraded baselines. This is the first experiment that can say whether "gate
   invariant + type-stable sentinels + deep merge" is a dynamic_config fact or a
   service-spec fact. Keep the rule from the protocol pins in the manifests
   (`training` / `validation` / `test` problem lists): write from the training
   problem, pick on validation, report on test.
4. *Where to climb next.* test_translator first (one cp5 decision, 511 tests; a
   round-1 analysis of hd2's transcript is cheap), then recli (container-runtime
   assumption) and mocked_http. Skip the 89–95 % problems until replication shows
   the noise floor is below 2 points there; database_migration says it is not.
5. *Make compliance measurable.* Record per session whether the skill was opened
   and whether the skill's verify step appears in the transcript; report scores
   with and without the non-compliant sessions. The Luna round-3 analysis shows a
   3-in-12 bail-out rate at cp2 that moves scores by 25–35 points independent of
   the skill text.
6. *Skill-writing rules to carry forward* (all supported by a collapse or a win
   above): read the grader's comparison semantics before writing any output-shape
   rule; one invariant first, verification tied to the summary; one-line rules
   that shape code, no notes files, no scripts, no ordering rules across handler
   stages; no escape hatch in the Finish section; description phrased as
   implementing, not testing.

## 7. Files written by this report

- `docs/report/skills-evolution.md` (this file)
- `docs/report/run-scores.csv`: every run cited above (89 rows: run id, problem,
  factory, phase, skill, partial %, strict checkpoints, per-checkpoint passed/total,
  builder seconds, API-equivalent cost, source = official or regrade)

Analysis-time artifacts produced while checking the numbers, outside the report
directory and git-ignored: `.tmp/regrade/sith/` and `intermediate/regrading/sith/`
(sith regrade), `.tmp/analysis/dc4-…-d3b-inherit-…/` (local test re-run; see
caveat 6 in §2.4).
