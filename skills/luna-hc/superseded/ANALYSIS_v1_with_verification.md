# What failed for v1-spec-checklist (luna6:low, circuit_eval, 98.9% partial, 555/566 at cp8)

Round-1 partial: v1 98.9 | v4 97.8 | v2 89.3 | v5 76.3 | v3 70.0 | no-skill 61.2.
The skill removed the biggest baseline failure classes (error envelope `command`, runtime value grammar,
crashes on new commands, builtin shadowing). What is left (11 tests at the end):

## A. Carried regressions: 8 of the 11 final failures (never repaired once broken)
| introduced | persisted | what |
|---|---|---|
| cp2 | cp2..cp8 | a `.circ` file containing the forbidden literal `X` now gives exit 3 (undefined name) instead of the parse error (exit 2). Cause: cp2 made runtime `X`/name handling shared with the file parser; `X` became "just an identifier". |
| cp4 | cp4..cp8 | `AND(a, 0)` (scalar literal as a function argument) fails with "Unexpected number". Cause: cp4 rewrote the literal tokenizer/parser for 3-valued/vector literals and dropped the plain `0`/`1` argument case. A cp3 regression test covered it. |
| cp6 | cp6..cp8 | stats on a BENCH file gives the wrong wire count (3 vs 1): spec semantics of "wires" misapplied for that format. New failure (was not a regression). |
| cp7 | cp7..cp8 | exhaustive counterexample prints a scalar input as `0b0` (vector radix formatting) instead of `0`. Cause: the shared formatter treats width-1 scalar as a vector; spec example shows scalar form. |
Why they persisted: Pass 3 of v1 verifies only the *current* part deeply; for earlier parts it asks for "one success and one error command". It also says to DELETE `scratch/` at the end, so every checkpoint starts with no memory of earlier checks. Each broken case was a *different* earlier-part case than the one spot-checked. The builder never sees the hidden earlier tests.

## B. New-part bugs on richer combinations (cp4: 3 tests, cp7: 1, cp6: 1)
- 3-valued eval with nested NOT/AND, multiple outputs, and hex-literal input crashed or returned a parse error: happy-path example passed, richer combos not exercised. A hex runtime value in 3-valued mode raised an uncaught exception printed as a bare `CircError: 3` (exit 4) — the "any uncaught exception is a bug" rule was followed for known cases but no catch-all/fuzz of input forms.
- Same lesson: run each new mode with every value syntax already accepted elsewhere (bin/hex/sized/X), with >1 output, nested expressions.

## C. Algorithmic (3 tests, cp8): absorption laws through nested/wired expressions, constant-op elimination postcondition. Genuinely hard at low effort; postconditions are checkable by re-running the optimizer's own output through a self-check (e.g. re-optimize and expect no change — "idempotence" — and scan output for each forbidden pattern the spec lists).

## Also noted
- The builder wrote "scratch_checklist.tmp" that leaked into submission (harmless).
- Builder finishes fast; spends its effort on the checklist and examples. There is room for more verification.
- Persistent workspace: files it keeps in the workspace survive to the next checkpoint's fresh conversation (the entry file and any extra files do; cp2 built on cp1's code).

## Levers for round 2 (build on v1's three-pass structure)
1. Persistent regression suite: instead of deleting scratch, keep `regress/cases.txt` (command line, fixture, expected stdout/exit) + a tiny runner; append every verified case each checkpoint; run the WHOLE suite after every edit to shared code and before finishing. Every fixed bug becomes a case.
2. Before editing a shared parser/formatter/dispatcher: list what it accepts today (read earlier spec parts, list each syntax/literal form), afterwards re-run each form. Never replace a tokenizer wholesale; extend it.
3. Combinatorial pass: new feature x each existing value syntax x multi-output x nested x scalar/vector/1-bit.
4. Forbidden-input checklist: items the spec says are forbidden/still forbidden must be re-tested after every parser edit (they regress because of generic reuse).
5. Formatting: scalar vs 1-bit vector vs wide; use the spec's example form for each.
6. Postcondition self-check: for spec-listed output postconditions, write a scanner and run it on outputs of several inputs.
7. Read the spec files for ALL earlier checkpoints only via the regression suite, not again in full (low effort budget).

## Verification pass (round 2 prep): corrections and additions

Checked against `scb_scores.py --failures`, `.tmp/analysis/*/checkpoint_N.txt`, the hidden test bodies and the builders' `events.jsonl`.

- **One bug = 5 of v1's 11 final failures, not 1.** The cp4 tokenizer rewrite dropped plain `0`/`1` as a call operand (`AND(a, 1)`). That is the cp3 regression `test_eval_scalar_literal` (2 parametrised tests), both cp4 "new" failures `test_eval_3val_nested_not_and` / `test_eval_3val_json_multiple_outputs` (their fixtures use `AND(a, 1)` / `AND(a, 0)`; section B above wrongly attributed them to nesting/multi-output), and the cp8 `no_trivial_constants` failure (the optimizer's own output file contains a constant operand and cannot be re-parsed: exit 2 "Unexpected number"). Round trip of written files through the program's own reader would have caught the last one; a persistent case from cp3 would have caught all five.
- Remaining v1 failures confirmed as stated: cp1 `X`-literal-in-file gives exit 3 not 2 (1), BENCH `wires_count` 3 vs 1 (1), hex value in the new mode crashes with a bare `CircError: 3` exit 4 (1), scalar printed as `0b0` in the counterexample (1), absorption postconditions (2).
- **Skill adoption differs per variant and per checkpoint** (Codex lists name+description; the model chooses to open it). SKILL.md was opened in v1 8/8 checkpoints, v3 8/8, v4 8/8, v5 6/8, v2 4/8 (not at cp2, cp3, cp6, cp7). v2's description reads as "verification/testing rules" while the stock prompt says "do not add or run tests unless asked"; v1's reads as "working rules for implementing". Keep v1's description verbatim in round 2 (control variable).
- **v2 cp3 collapse (66/205) cause.** Session without the skill opened; 208 s of 1800 s, 7 commands, 4 edits. The builder rewrote the entry file (delete+add), ran 4 spec examples, all died with `internal error: int() ... NoneType`, made one tokenizer fix, reran, same failure, then submitted with the final message "The example runs are still failing with an internal error, so the implementation is incomplete." v1's cp3 hit the same first lexer bug and iterated 6 edits until the examples passed. Lessons for what NOT to put in a skill: (1) do not tell the builder to delete its verification artifacts at the end while relying on them as regression guards (v2's `smoke.sh` never survived a checkpoint; v1 deletes `scratch/` too); (2) do not offer an "honest failure" exit in the Finish section ("name the exact item left unverified") - a low-effort model takes it after one attempt; say instead that a failing spec example is never a finished state, restore the last working copy and take a smaller step; (3) the catch-all error handler hid the traceback and the builder never tried to get one - give it a debug switch; (4) descriptions framed as testing lower adoption.
- **v4 cp8 (524/566, opt 27 tests lost)** is the same failure mode with the skill open: 721 s, 84 commands, 41 edits looping on one undefined temporary name in the compact-rename path; the loop also broke the basic `opt` path (every test exits 3), final message "should not be treated as a working solution". A last-good copy of the entry after the first example passed would have kept ~20 tests.
- Workspace persistence confirmed: `builder-workspace/src` is the same directory for all 8 checkpoints; v1's cp8 builder ran `cat scratch_checklist.tmp` left over from cp6, so a clearly named file will be found and read by later sessions. Only `SPEC.md`, `SKILL.md`, `instructions.md`, `.venv`, `__pycache__`, `.pytest_cache` are excluded from submissions; anything else ships, harmlessly, as long as nothing importable lands at the root.
- Sandbox notes from transcripts: `rm -rf scratch` was rejected (python `unlink` works), `git` fails (xcrun cache error), `/tmp` is blocked, `python3` on PATH prints xcrun noise while the interpreter path from the spec's examples is clean.

## Round-2 variants (all derived from v1, same description, < 6000 bytes)

| variant | hypothesis |
|---|---|
| r2a-persistent-suite | Carried regressions dominate; a `regress/` suite (fixtures + `cases.sh` + `expected.txt`) that is never deleted, run at session start, after every shared-code edit and before finishing, gives the fresh conversation memory of every verified case. |
| r2b-shared-code-guard | Regressions come from edits to shared tokenizer/parser/formatter/dispatcher; inventory ACCEPTS/REJECTS before the edit, extend never replace, re-test each line after, forbidden inputs and literal operands explicitly. |
| r2c-combination-grid | New-part failures come from testing only the happy path; a grid of new feature x each value syntax x scalar/width-1/wide x nested-with-literal x multi-output x each format x each error path, plus agreement oracles (two formats, two commands, text vs JSON). |
| r2d-postcondition-fidelity | Output-producing commands need self-checks (round trip through own reader, idempotence, preservation, per-postcondition scanner to a fixed point) and formatting chosen by declared kind (scalar vs vector) with the spec's example as reference; counts compared across formats. |
| r2e-combined-tight | v1 core compressed + light persistent suite + extend-not-replace/forbidden-input rule + agreement and round-trip oracles + debug traceback switch + "never finish broken" (last-good copy, three attempts then smaller step). |
