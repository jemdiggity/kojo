# Round 1 analysis: luna (gpt-6-luna) on circuit_eval

Evidence: `results/runs/luna-ab-01-circuit-eval-luna` (build only) and
`luna-ab-01-circuit-eval-luna-review-fix` (build/review/fix), both medium effort, no skill.
Failure detail regenerated with `scripts/scb_failures.sh` into `.tmp/analysis/<run>/checkpoint_N.txt`;
transcripts read from `intermediate/runs/<run>/gauntlet/training-*/circuit_eval/checkpoint_N/events.jsonl`.

## Scores

| run | cp1 | cp2 | cp3 | cp4 | cp5 | cp6 | cp7 | cp8 | partial pass |
|---|---|---|---|---|---|---|---|---|---|
| build only | 36/36 | 95/99 | 200/205 | 372/430 | 392/457 | 443/508 | 458/529 | 463/566 | 0.902 |
| review-fix (after fix) | 35/36 | 98/99 | 204/205 | 429/430 | 76/457 | 507/508 | 525/529 | 558/566 | 0.816 |

371 test-failures in the build run, 398 in the review-fix run. Every failure is accounted for below.

## What the builder actually did (transcripts)

* Build sessions ran `rg --files`, `sed -n` over the entry file, `git diff`, at most `py_compile`. **Zero
  executions of the program** in any build session of either run. Answers say "I did not run tests".
* Sessions lasted 53-194 s of an 1800 s budget; output 1.5k-7.6k tokens. Effort was not the limit.
* The Codex stock prompt contains "Do not add or run tests unless the user asks you to test or verify
  implementation", and the task prompt does not ask. A skill must explicitly reclassify running the
  spec's examples as part of implementing.
* Fix sessions did run the CLI: `./entry` was "permission denied" (sandbox), `python3 entry ...` worked;
  fixtures written in the workspace worked; `/usr/bin/python3` prints xcrun cache warnings on stderr
  (harmless). One build answer claimed temp-file writes were denied (system temp dir). Skills should tell
  the model: run via the interpreter, keep fixtures inside the workspace, ignore cache warnings.
* Skill delivery: `.agents/skills/cli-software/SKILL.md`; Codex lists name + description and the model
  decides whether to open it. The description must clearly claim "any CLI-from-spec task".

## Failure classes

### Build-only run (371 failures)

| # | class | tests | root cause (from code + spec) | general? |
|---|---|---|---|---|
| A | Error envelope `command` is the CLI placeholder instead of the subcommand | 49 (cp2: 4, cp3: 5, cp4-8: 8 each) | cp1 error handler computes `cmd = args[0] if args[0]=='check' else '__cli__'`; never updated when `eval` was added; bad `--radix`/`--mode` combos and value errors all mislabeled. Hard-coded command list in the error path. | yes: single emitter, command field = typed subcommand, update every enumeration when adding a command |
| B | Runtime `--set` vector values with unknown digits rejected as a file parse error (`CircParseError: invalid literal`) | 250 (50 at cp4, persisting cp5-8) | Runtime value parser delegates to the file literal parser, which (correctly) forbids the new digit in files; spec section "Runtime literals" explicitly allows it on the command line. The spec's own example (`--set v=0b11X1`) would have failed on first run. | yes: separate command-line value grammar from file grammar; run the spec examples |
| C | Crash (exit 4, internal error) on a new command's main path | 38 (cp7 cone: 3, +3 at cp8; cp8 opt: 32, `TypeError: 'int' object is not subscriptable`) | Never executed once; the spec's first example crashes. All opt tests lost. | yes: run every example before finishing; internal-error exit is always a bug |
| D | Exit code taken from category prose instead of the explicit row | 4 (cp5-8) | Spec: "format-specific errors follow conventions: parse 2, validation 3" then "Unknown extension -> exit 1". Implementation used 2. | yes: exit code comes from the row naming the type |
| E | Second, divergent value formatter | 6 (cp7: 3, cp8: 3) | truth-table JSON dropped the radix prefixes that `eval` (shared formatter from cp3) prints. New command copied formatting instead of reusing it. | yes: one formatter/parser shared by all commands |
| F | New input format does not carry existing features | 24 (6 at cp5, persisting) | JSON-format circuits with vector ports crash (`IndexOutOfBoundsError: invalid slice`): the new parser did not feed msb/lsb ranges into the shared model. Tested (if at all) only with the scalar example. | yes: new format must produce the same model; exercise it with the richest earlier features |

### Review-fix run (398 failures after fix)

| # | class | tests | root cause | general? |
|---|---|---|---|---|
| G | Catastrophic regression: every `eval` crashes (`'str' object is not callable`) | 380 at cp5 (also broke cp6 build: 381; repaired by fix stage at cp6) | cp5 build introduced a variable named `format` in the eval path, shadowing the builtin used by the shared formatter. No smoke run after the edit; the reviewer only exercised `check`, so the fix stage at cp5 did not touch it. | yes: rerun earlier-part commands after touching shared code; never shadow builtins |
| A' | `--seed` validation error labeled with the CLI placeholder | 4 (cp7-8) | Global flag parsed before dispatch; error emitted before the command token was consulted. | yes: same as A |
| B' | `--set a=X` in 2-valued mode reports the file parse error type instead of the input value type | 6 (cp3-8) | Runtime value parser reuses the file parser; its exception escapes untranslated. Reviewer never flagged it. | yes: translate errors at the input-origin boundary |
| D' | Missing file exits 4 instead of 1 | 2 (cp1-2, fixed at cp3) | A custom exception class named `FileNotFoundError` shadowed the builtin; `except FileNotFoundError` caught only the custom one, the builtin fell to the catch-all. | yes: never name a class like a builtin exception; test the trivial error cases |
| H | Deterministic ordering "dependency order, ties by name" implemented as level order | 2 (cp7-8) | Emitted by depth level instead of "smallest-named ready item first". | partly: deterministic-order rule is transferable |
| I | Optimizer postconditions incomplete (absorption through wires, fanin on nested inputs) | 4 (cp8) | Algorithmic depth; each spec postcondition is a test, none were checked on the output. | partly: "write a checker per stated postcondition and run it on your own output" |
| J | cp3 build broke two cp1/cp2 behaviours (error location, value error type); fix restored one | (counted in B'/D') | Shared parser rewrite without rerunning earlier examples. | yes: regression smoke |

## What a skill can and cannot buy

Transferable behaviours (cover ~95% of lost tests): run the program on every spec example and error
row before finishing; keep old-part commands as a regression smoke; one error emitter with the command
field rule and a literal exit-code table; separate command-line value grammar/error types from file
grammar; one shared parser/formatter/model; update every enumeration when adding commands; no builtin
shadowing; treat internal-error exits as bugs; exercise new formats with rich existing features.

Task-specific (a skill cannot legitimately fix): the 3-valued literal grammar itself, absorption through
intermediate wires, fanin decomposition of nested inputs, exact tie-breaking of topological order. These
are ~10 tests per run.

Constraints for skills: name `cli-software`, one-line description, < 6000 bytes, no task identifiers
(gauntlet `skill_valid` rejects problem names; the variants also avoid the word "circuit"), no test
names or expected payloads, no extra tools or dependencies. Builder runs at low effort: rules must be
imperative, concrete, and short, and must override the stock "do not run tests" instruction by framing
example runs as part of implementation.

## Variants in this round

| variant | strategy |
|---|---|
| v1-spec-checklist | Three passes: extract a numbered requirement checklist from the spec, implement against it, tick each item only after a run. |
| v2-run-examples | Verification first: a growing `scratch/smoke.sh` of spec examples, error rows, and earlier-part commands, run after every edit and before finishing. |
| v3-error-contract | Error machinery first: one emitter, one exit table, command-field rule, error-type-by-input-origin, foreign-exception translation; then run every error row. |
| v4-regression-guard | Change discipline for an evolving codebase: read and inventory shared code, record before-outputs, extend instead of copy, diff before/after, mixed old/new cases. |
| v5-terse | Thirteen one-line rules covering the same ground, for a low-effort reader that may skim. |
