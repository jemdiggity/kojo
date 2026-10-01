# Factory language

A factory says which model does each stage of a checkpoint and how the stages
flow, including loops with a limit. It lives in `configs/factories/NAME.factory`
and is run per checkpoint, after which the resulting code carries into the next
checkpoint as usual.

```
# luna builds -> opus refactors -> review loop (max 5) -> qa; failed qa goes back to build (max 2)
build    = luna6
refactor = opus55:high
review   = opus55:high
fix      = luna6
qa       = sonnet55

build -> refactor -> review
review -[fail, max 5]-> fix -> review
review -> qa
qa -[fail, max 2]-> build
qa -[pass]-> done
```

## Stages

`NAME = [KIND] MODEL[:EFFORT] [xN] [by CHECKER] [guard CHECKER] [prompt NAME]`, or
`NAME = check CHECKER [ARG]` for a deterministic stage that runs no model. `MODEL` is a
suite alias (`luna6`, `astra6`, `sol61`, `sonnet55`, `opus55`, ...; run
`scripts/scb_suite.sh -h` for the list) or an exact provider ID. `EFFORT` defaults to
`medium` and must suit the model's provider. `KIND` defaults to the stage name, so a stage
called `review` is a review.

| Kind | Does | Prompt |
|---|---|---|
| `build` | Stock SCB prompt for the checkpoint, in the shared builder workspace. | upstream |
| `revise` | Reviews its own inherited code against the specs and fixes it. | `configs/factory-prompts/revise.md` |
| `refactor` | Restructures without changing behavior. | `refactor.md` |
| `fix` | Follows up on the review, qa or check report that precedes it. | `fix.md` |
| `review` | Reads a disposable copy and reports; ends with a verdict. | `review.md` |
| `qa` | Runs the program against the specs in a disposable copy; ends with a verdict. | `qa.md` |
| `plan` | Reads specs 1..N and a copy of the code and writes a plan; no verdict. | `plan.md` |
| `tester` | Writes or extends the run-level test suite from specs 1..N; never sees code. | `tester.md` |
| `branch` | Builds the checkpoint from its start code in its own workspace, with any model; kept aside. | upstream |
| `check CHECKER` | Deterministic, no model, no session; verdict from the checker. | none |

`build`, `revise`, `refactor` and `fix` change code; their result carries forward
in the persistent builder workspace. `review` and `qa` never change it. Their
answer goes to the next code-changing stage as feedback, and their final
`VERDICT: PASS` or `VERDICT: FAIL` line (appended to the request by the harness;
a missing line counts as a fail) selects the next arrow. A `check` gives the same
verdict from its checker, and its log is the feedback text (headed
`# Deterministic check results` in the next stage's prompt instead of the reviewer heading).

A `build` stage re-entered through a loop receives the stock prompt plus the
preceding report as appended feedback; a first build never does. Every stage runs
in a fresh CLI conversation.

* `plan`: its answer becomes `# Planning notes for this checkpoint`, appended to every
  later `build` of the same checkpoint (until another plan replaces it). A build with no
  plan is byte-identical to the stock prompt.
* `tester`: runs in a fresh workspace holding only `suite/` (the accumulated suite so far).
  Afterwards the suite is copied back to the run-level suite directory and archived under
  `STAGE/checkpoint_N/suite`. Its answer is not forwarded to any stage.
* `branch`: gets the stock build prompt and the code the checkpoint started with, in its own
  non-shared workspace. Its result is frozen and graded like other code-changing sessions but
  never becomes the main code; checks such as `diff NAME` reference it by stage name.

### Attributes

Any order after `MODEL[:EFFORT]`; they apply to code-changing stages (not `branch`), except `prompt`.

* `xN` (2 to 10) with `by CHECKER`: N independent attempts from the same starting code, each in its
  own non-shared workspace. `by` scores each attempt with a scoring checker; the highest score wins
  (ties go to the earliest attempt) and becomes the main code. Every attempt is frozen and graded
  (`STAGE/checkpoint_N-attemptK`); the winner is recorded in the trace.
* `guard CHECKER`: score the code before and after the stage; if the after-score is lower, the stage's
  result is discarded and the earlier code carries on. Recorded in the trace.
* `prompt NAME`: use `configs/factory-prompts/NAME.md` instead of `KIND.md` as this stage's request
  (review, qa, fix, revise, refactor, plan and tester stages; not `build`/`branch`).

Scoring checkers (`by`, `guard`) are `smoke`, `examples`, `suite` and `safe`: score is the fraction of checks
passed, 1.0 when nothing was checked (0.0 for `safe` when the program does not start). `guard safe` is
stricter than a score comparison: the stage is also rolled back if the program no longer compiles or starts,
or if any suite case that passed before it now fails, even when other cases were repaired and the
aggregate score rose.

## Flow

`a -> b -> c` chains stages. An arrow may carry options: `-[fail]->`, `-[pass]->`,
`-[max N]->`, `-[reset]->`, `-[progress]->`, or a mix such as `-[fail, max 5, reset]->`. `done` ends the checkpoint.

* From a stage, the **first** arrow (in file order) whose condition holds and whose
  `max` is not spent is taken. `pass`/`fail` conditions need a `review`, `qa` or `check` source.
* `max N` counts uses per checkpoint. If nothing is eligible, the checkpoint's
  factory ends with the current code.
* `progress` (only on an arrow out of a `check` stage) is taken only while the check's failures differ from
  the same check's previous visit in this checkpoint (the first visit always qualifies). When a fix changed
  nothing, or was rolled back by `guard`, the same cases fail again and the loop ends with the current code
  instead of spending the rest of its `max`. The trace marks such a visit `stalled`. For `suite` and `safe`
  what is compared is the set of failing cases; for the other checks, the passed and total counts.
  Worst-case session counts ignore `progress`.
* `reset` restarts the destination stage (a code-changing stage that carries code) from the code the
  checkpoint started with, not the latest attempt, and without feedback text (a reroll). The shared
  builder workspace is made exactly equal to that code first (extra files removed, environment and
  cache files such as `venv/` kept).
* The flow may start at a `tester` or `plan` stage, but the first code-changing stage reached must be a
  `build`; nothing that needs code (`check`, `review`, `qa`) may run before it. Every stage must be
  reachable, a `fix` must follow a `review`, `qa` or `check`, every loop needs a `max`, so a factory
  always terminates. `suite` and `diff` need a `tester` somewhere, and `check diff NAME` needs `NAME`
  to be a `branch`. Errors name the file and line.

In the first example, `review -[fail, max 5]-> fix` allows at most five fix passes;
a review that still fails afterwards falls through to `review -> qa`.

Session counting: `Factory.max_sessions()` is the worst-case number of MODEL sessions per checkpoint
(checks cost none, `xN` costs N); `max_checks()` counts deterministic runs, scoring runs included.
The manifest records both, times the number of checkpoints.

## Checks

Deterministic checks live in `src/kojo/checks.py` (`run_check(name, ctx)`). A check returns a verdict,
`passed/total`, a `score` in [0, 1], a `log` (feedback text for a fixer: failures first, capped near
6000 characters, stating that it comes from deterministic checks) and JSON `details` saved as a receipt:
`STAGE/checkpoint_N[-k]/result.json` and `log.txt`. Everything a check executes (the candidate, and
suite scripts) runs like builder code under the official grader: a subprocess in a fresh temp directory,
a scrubbed environment (no secrets), per-case timeouts and truncated output; checks never write into the
code they test. The candidate runs under the harness's base Python without the run's own virtualenv, so
third-party dependencies are not available to checks.

| Checker | Does |
|---|---|
| `smoke` | Byte-compiles every `.py` and the entry file; runs `--help` (and `--version` if a spec mentions it). Fails on SyntaxError, IndentationError, Traceback, timeout or a non-zero exit. |
| `examples` | Extracts runnable examples from public specs 1..N and compares stdout (trailing whitespace normalized; equal JSON in another layout counts as equal) and the stated exit code. Reports `spec example mismatch` with a diff. Finding nothing passes with total 0. |
| `safe` | `smoke`; if the program starts, then `suite`. One gate for "runs at all, and passes the suite". Its details list the failing case names, and `guard safe` uses them (see Attributes). A program that does not start scores 0.0 and only the smoke log reaches the fixer. |
| `suite` | Runs the accumulated suite; if the previous checkpoint's code exists, also runs it there and lists REGRESSIONS (passed before, fail now) first. Invalid cases are listed but never blamed on the code. |
| `repro` | Parses repro cases (suite case schema, one fenced `json` block) from the previous stage's answer, runs them, and reports only CONFIRMED failures (the actual result does not meet the stated expectation). No parseable repros passes with total 0. |
| `diff NAME` | Runs each `suite/fuzz/*.py` with `ENTRY_A` (this code) and `ENTRY_B` (branch `NAME`); exit 0 means agreement, and disagreements are logged. |

Example extraction is careful and never guesses. It keeps a `$ <entry command> ...` example from a
fenced block only if every input file it names was defined earlier in specs 1..N as a fenced block
under a `` `name.ext` `` line, and its expected output has no `...` or `<placeholder>`. Later specs win:
an identical command line in a later spec replaces the earlier example, and an example whose fixture
was redefined later is dropped. Skipped examples are recorded with a reason in the receipt.

### Suite format

`suite/cases.json` is a JSON array (or `{"cases": [...]}`):

```json
{"name": "unique", "source": "example|postcondition|property|regression",
 "argv": ["eval", "adder.circ", "--set", "a=1"],
 "files": {"adder.circ": "file text"},
 "stdin": null,
 "expect": {"exit": 0, "stdout": "exact", "stdout_regex": "re", "stdout_contains": ["x"],
            "stdout_json": {"ok": true},
            "files": {"out.txt": {"regex": "re", "not_regex": "re", "equals": "text"}}}}
```

`argv` excludes the program; the harness prepends it. All `expect` keys are optional (at least one is
needed). Script cases `{"name": "...", "script": "checks/absorb.py", "args": []}` run the script with
Python and the env vars `ENTRY` (shell-quotable command) and `ENTRY_ARGV_JSON`; exit 0 passes.
`fuzz/*.py` scripts get `ENTRY_A`/`ENTRY_B` (plus `*_ARGV_JSON`) for `check diff`. Malformed cases,
missing or non-compiling scripts count as `invalid` (listed in the log for the tester, never a code failure).
A script that fails at run time counts as a failure, including one that dies parsing the program's output, with
one exception: a script that dies with `NameError`, `UnboundLocalError`, `SyntaxError`, `IndentationError`,
`TabError`, `ImportError` or `ModuleNotFoundError` has a bug of its own, so it is listed as invalid and left out
of the pass count. Other exceptions may be a tester's intended way of failing, or the program's fault, and still
count against the program.

### Information rules

Stages may use only public information: the public checkpoint specs 1..N (never a later spec), the
code, and what earlier stages wrote. Never hidden grader tests, official scores or grading output.
A `tester` sees specs 1..N and the suite, never any builder code, and a `branch` builds from the spec
alone, so both stay independent of the main builder. Checks read code and suite only.

## Bundled factories (the ten `luna-*` experiments of `fx-02`, and three variants)

| Factory | Idea |
|---|---|
| `luna-smoke-reroll` | build; smoke check; on failure reroll from the start code (max 3). |
| `luna-examples-fix` | build; run the spec examples; mismatches go to a fix (max 3). |
| `luna-tester-suite` | sol writes a growing spec-only suite; build; suite check with regressions first; fix (max 3). |
| `luna-best-of-3` | suite from sol; three luna builds, the best suite score wins. |
| `luna-guarded-fix` | suite; build; sol QA; luna's fix is rolled back if it lowers the suite score. |
| `luna-postcond` | like tester-suite but the tester writes only guarantee cases plus fuzz scripts. |
| `luna-vs-sol-diff` | luna and sol (branch) build independently; fuzz diff; luna adjudicates disagreements (max 2). |
| `luna-verified-review` | astra reviews with repro cases; only program-confirmed failures reach the fix (max 2). |
| `luna-planned` | sol plans; luna builds from the plan; spec examples gate a fix (max 2). |
| `luna-regress-net` | regression-focused tester; two-stage gate (smoke, then suite) with fixes. Differs from `luna-tester-suite` by its tester prompt and the smoke stage ahead of the suite. |

Variants built from the `fx-02` results (report `2026-09-30-fx-02-factory-sweep.md`, kept in the private kojo-results repo under `reports/`):

| Factory | Change from its parent |
|---|---|
| `luna-postcond-safe` | `luna-postcond` with one `check safe` gate, `guard safe` on the fix (a fix that breaks the program or any passing case is discarded), and a `progress` arrow (stop when a fix changes nothing). |
| `luna-tail-safe` | `luna-postcond-safe` with the `tester-tail` prompt: a systematic pass over every guarantee (routes to it, boundaries, output order, error classes, feature interactions) and scripts that report problems with an explicit exit 1. The prompt names no problem-specific behavior. |
| `luna-verified-review-sol` | `luna-verified-review` with sol 6.1 as the reviewer instead of astra (the same `repro` check). |

`configs/batches/fx-02-factory-grid.json` runs all ten on `circuit_eval`, three seeds each.

## Running

```sh
scripts/scb_suite.sh --id try-01 --problems circuit_eval \
  --factory luna-review-astra luna-opus-review-loop luna-opus-qa --parallel all --audit
```

`--factory` replaces `--models` and `--efforts`; each factory is one run per
problem (and per skill set), and `--parallel` treats factories as it treats
models. Or run one directly: `python -m kojo.factory run --run-id ID --factory NAME
--problem circuit_eval`.

Each run records `factory.txt`, the parsed factory (with attributes) and its hash in `manifest.json`,
the worst-case `max_sessions` and `max_checks`, and `flow-trace.json` (stage, verdict and next stage
per session, plus check scores, xN attempts and winner, guard before/after/rollback and `reset`).
A stage's first visit in a checkpoint writes to `STAGE/checkpoint_N`; later visits to
`STAGE/checkpoint_N-2`, `-3`, and so on; xN attempts to `STAGE/checkpoint_N-attemptK` (`-2-attemptK` on a later
visit). Check stages write receipts to `STAGE/checkpoint_N[-k]/{result.json,log.txt}`, and scoring runs
for `by` and `guard` to `score/`, `guard-before/` and `guard-after/` inside the stage's directory.
Every code-changing session (attempts, branches and rolled-back fixes included) is graded after all
model calls finish; sessions that did not become the main code carry `aside: true` in `scores.json`
and do not move the baseline the next `-N / +M` is measured against.

## Reading scores

Each `Graded ...` line ends with the same compact diff (`-N / +M`, against the previous graded session of the run). Each `scores.json` entry records it as `broken` and `gained`, and splits the score into `new` (this
checkpoint's own core, functionality and error tests) and `regression` (tests from
earlier checkpoints). `scripts/scb_scores.py RUN_ID ...` prints that table for finished
runs as one compact diff per session, `-N / +M`: N tests passed after the previous session
and now fail, M tests pass now that did not before (new tests plus repairs). Add `--failures`
to name the failing tests.

## Measuring every stage

Every code-changing stage (build, revise, refactor, fix, branch), on every visit and attempt, has its output
tested and analyzed once all model calls have finished: the official grade is in
`STAGE/checkpoint_N/evaluation.json` and the static quality analysis (erosion and verbosity,
scb-check) in `STAGE/checkpoint_N/quality.json`. The `Graded` line and `scores.json` carry
the headline numbers, and `scb_scores.py` shows them per session. Review, qa, plan, tester and check stages
change no code, so they have no output to measure. A quality analysis that fails is recorded
in `scores.json` and never costs the run its grades; `--no-quality` skips it (it needs `uvx`
and network access). Runs made before this can be analyzed afterwards with
`scripts/scb_quality.py`.

Stage outputs are independent snapshots, so several are graded and analyzed at the same
time once every model call has finished: `--grading-jobs N` (default 4; `1` grades one at a
time). The `Graded` lines, `scores.json` and the `-N / +M` diffs still follow session order,
and the manifest records `grading_jobs`. Each snapshot gets its own fresh grading
environment, built once and shared by the evaluator's collection passes and test run;
the install and freeze receipts come from that one build.
