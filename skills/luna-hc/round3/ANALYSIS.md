# Round 3 analysis: luna6 (gpt-6-luna, low effort) on circuit_eval, rounds 1 and 2

Evidence base
- Scores: `scripts/scb_rank.py hc2b` / `hc1`, `scripts/scb_scores.py --failures RUN`.
- Assertion detail: `scripts/scb_failures.sh RUN` regenerated for all six hc2b runs into
  `.tmp/analysis/<run>/checkpoint_N.txt`; old-checkpoint tests were re-run against later submissions with
  `.tmp/hc_regress.sh RUN SUB_CP TEST_CP KEXPR` (root cause of carried regressions).
- Transcripts: `intermediate/runs/<run>/gauntlet/training-build/circuit_eval/checkpoint_N/events.jsonl`,
  summarised with `.tmp/hc_dump.py RUN CP` and `.tmp/hc_metrics.py` (duration, tokens, commands, edits, whether
  `SKILL.md` was read, final message). Submissions read from `results/runs/<run>/build/checkpoint_N/submission/`.
- Hidden tests/fixtures: `intermediate/vendor/scb-problems/circuit_eval/tests/`.
- The `hc2-*` run directories (earlier aborted attempt) contain no events and were ignored.

Runs are abbreviated: r2a..r2e = `hc2b-circuit-eval-luna-low-<variant>`, v1a = round-1 v1 (`hc1-...-v1-spec-checklist`),
v1b = round-2 v1 control re-run (`hc2b-...-v1-spec-checklist`).

## 0. Scoreboard and effort

| run | partial | cp1 | cp2 | cp3 | cp4 | cp5 | cp6 | cp7 | cp8 | final fails | total s | cmds | SKILL.md read at cp |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r2d postcondition-fidelity | 99.6 | 36/36 | 99/99 | 204/205 | 428/430 | 455/457 | 506/508 | 527/529 | 560/566 | 6 | 1876 | 176 | 1,3,4,5,6,7,8 |
| r2c combination-grid | 99.3 | 36 | 99 | 205 | 427 | 453 | 503 | 523 | 556 | 10 | 1238 | 85 | all 8 |
| r2e combined-tight | 99.1 | 35 | 98 | 205 | 428 | 455 | 506 | 526 | 557 | 9 | 1084 | 76 | 1,4,7 (suite run at 1,3,4,6,7) |
| v1a (round 1) | 98.9 | 36 | 98 | 204 | 424 | 451 | 501 | 521 | 555 | 11 | 1703 | 137 | all 8 |
| v1b (round 2 control) | 91.7 | 36 | 99 | 170 | 384 | 411 | 461 | 479 | 511 | 55 | 1499 | 104 | 1,2,3,4,6,7,8 |
| r2a persistent-suite | 87.7 | 36 | 99 | 169 | 353 | 379 | 429 | 449 | 479 | 87 | 1110 | 71 | 1,2,3,7,8 (suite run 1,2,3,4,6,7,8) |
| r2b shared-code-guard | 62.9 | 36 | 36 | 37 | 229 | 290 | 393 | 408 | 438 | 128 | 948 | 75 | 1,5,6 |
| none (round 1) | 61.2 | 36 | 36 | 37 | 265 | 284 | 357 | 372 | 401 | 165 | 827 | 50 | - |

Budget is 1800 s per checkpoint; the longest session in any run was 721 s (v4 cp8) and the longest in round 2 was
585 s (r2d cp4). Effort is never exhausted; the model stops early. Every run, whatever the skill said, rewrote the
entry file wholesale (delete + add) at cp3 (vectors) and extended it at every other checkpoint.

## 1. The top three runs: every failing test, root cause, shared vs unique

Legend for "rule?": Y = a transferable rule can prevent it (with a sketch of that rule); Y* = the rule was already in
the skill and was not followed; T = task-specific knowledge only.

### r2d (winner, 6 final failures)

| cp introduced | test | persisted | root cause (verified) | rule? |
|---|---|---|---|---|
| cp3 (new) | cp3 `test_eval_reduction_operators[REDUCE_AND-0b1111-1]` | cp3-cp8 | `REDUCE_AND` implemented as `int(args[0]==mask)` where `mask` is the 1-bit result mask, so it returns 1 only when the operand equals 1. The session ran no `REDUCE_AND`/`REDUCE_OR` fixture at all (only `REDUCE_XOR({a[1:0],b[1:0]})`), despite a 503 s / 34-command session. | Y*: "tick an item only after its run" was not applied per operator. Sharper rule: one run per operator/branch with an input whose expected output is not the default (r2c's "asymmetric value" cell). |
| cp4 (regression of cp1) | cp1 `test_check_parse_errors_have_location[literal_x]` | cp4-cp8 | Re-run of cp1 tests against the cp8 submission: `y = X` in a `.circ` file gives exit 3 (`UndefinedNameError`) instead of `CircParseError` exit 2. The cp4 session (585 s, 93 commands, 26 edits) spent ~80 commands looping on exactly this file-vs-runtime `X` boundary, finally "removed the overbroad early guard and kept X prohibition enforced by literal parsing", which classifies a bare `X` as an identifier. Same class as v1a's cp2 regression. | Y: r2a/r2e wording "a token an earlier part forbids in files stays a parse error there after this part allows it elsewhere" plus a concrete check (feed the forbidden token through the file reader, expect the old type). r2e, which had that sentence, kept this test green. |
| cp8 (new) | `test_opt_postcondition_absorption`, `_absorption_and` | - | Absorption is only applied when both operands are inline; `t = AND(a,b); y = OR(a,t)` (through a wire) is left. Fails in all 6 runs. | T-ish. r2d's own rule ("three inputs built to violate the rule, at least one through an intermediate named signal") is exactly the check needed and was not executed (cp8: 10 commands). |
| cp8 (new) | `test_opt_fanin_limit_enforced`, `_for_nested_inputs` | - | `--fanin-limit 2` with the default pipeline leaves `AND(a,b,c,d,e)`; the fanin pass only runs when selected via `--passes`/`--pipeline area`. Spec postcondition 8 says the limit holds whenever the flag is given. Fails in r2d, r2e, v1b, r2a, r2b; r2c passes. | Y: "a flag's guarantee holds whenever the flag is given, with default settings; run the spec's example for the flag and inspect the written file for the guarantee (the example's `# exit 0` is not the check)". |

### r2c (99.3, 10 final failures)

| cp | test | persisted | root cause | rule? |
|---|---|---|---|---|
| cp4 (new) | `test_eval_3val_mux_vector_per_bit`, `test_eval_3val_mux_vector_cases` x2 | cp4-cp8 | `MUX(X, a, b)` returns all-X bits instead of per-bit (`a_i` where `a_i == b_i`). The builder ran the spec's own example (`sel=X a=0b0101 b=0b0111`), saw `y=0bXXX1` and finished with "Verification exposed a bug ... I'm stopping here with that issue unresolved." | Y*: byte-compare rule existed; the Finish section only forbids finishing while an example *crashes*. Needs "an example whose output differs from the spec is never a finished state". |
| cp5 (new) | `test_json_vector_eval_3val_cases[0b0101-0b0101-X-...]` | cp5-cp8 | Same MUX-X bug through the JSON pipeline (`eq` of equal MUX alternatives returns X). Consequence of the cp4 bug, not a new one. | same |
| cp6 (new) | `test_stats_cross_format[bench]` | cp6-cp8 | BENCH loader marks every assigned name as a wire (`decls[lhs]='wire'`), so `OUTPUT(y0)` names count as wires: `wires_count` 3 instead of 1. Fails in r2c, r2a, r2b, v1a, v1b; passes in r2d and r2e. | Y: r2d's "feed the same design in two formats and compare each named count" (r2d passed; its cp6 transcript does not show the comparison, so this may be luck). |
| cp7 (new) | `test_truth_table_json_hex_vector_columns` | cp7-cp8 | truth-table JSON prints `'f'`/`'0'` without the `0x` prefix that `eval` prints; the builder wrote a second formatter and "adjusted vector binary values to carry the 0b prefix" but not hex. Round-1 class E. | Y*: one-formatter rule and the agreement oracle ("same value through two commands must be identical") both existed in r2c. |
| cp8 (new) | `test_opt_bench_export_vectors_error` | - | `opt vector.circ -o vector.bench` exits 3 (validation error at `y = REDUCE_XOR(v)`) before the BENCH check: the serializer drops the vector declaration and the builder's own "validate the serialized result through the existing loader" turned that bug into a user-facing error. Never ran `opt` on a vector fixture. | Y*: "richest existing features (wide values)" cell of its own grid was skipped at cp8 (7 commands). |
| cp8 (new) | `test_opt_cse_and_dce_cleanup` | - | DCE removes the dead assignment but leaves `unused` in the `wire` declaration line. | Y: round trip through the reader with a strict check that every declared wire is assigned; or "the writer emits declarations from the surviving assignments, never from the input". |
| cp8 (new) | absorption x2 | - | as r2d | T-ish |

### r2e (99.1, 9 final failures)

| cp | test | persisted | root cause | rule? |
|---|---|---|---|---|
| cp1 (new) | `test_check_file_not_found` | cp1-cp2 (fixed by the cp3 rewrite) | Submission defines `class FileNotFoundError(CircError)` and then `except OSError as e: if isinstance(e, FileNotFoundError)` -> never true -> catch-all -> exit 4. The exact builtin-shadow the skill forbids. The cp1 final message also admits "the regression suite still has a known failure ... I did not rerun the final diff". | Y*: rule existed; also violates "never finish broken". The missing-file row was on its checklist (item 6) and was never run. |
| cp4 (new) | `test_eval_3val_hex_input_no_x_ok`, `_decimal_input_no_x_ok` | cp4-cp8 | In 3val mode `--set a=0xff` gives `0b00001111` (new runtime parser mishandles non-binary radix). New mode x old value syntax; same class as v1a's cp4 hex crash. r2c's grid ("x every value syntax the program already accepts") covers it and r2c passed. | Y: grid cell "new mode x each existing value syntax". |
| cp7 (new) | `test_cone_outputs_sorted_and_inputs_pruned` | cp7-cp8 | Assignments emitted `t, z, y` (level order) instead of "dependency order, ties by LHS name" (`t, y, z`). Same in r2a. Round-1 skills v2-v5 carried the explicit rule "emit the smallest-named ready item each step"; v1 and all round-2 variants dropped it. r2d/r2c/v1b happened to implement it right. | Y: restore the explicit rule. |
| cp8 (new) | `test_opt_output_equivalent_to_input`, `test_opt_absorption_after_flattening` | - | `opt` on the comparator fixture (`OR(gt1, AND(eq1, AND(a0, NOT(b0))))`) dies with `InternalError: unhashable type: 'list'` (exit 4). Never ran the new command on a nested fixture; 8-command session. | Y*: "richest existing features, nested expressions" and "internal-error exit is always a bug" both in r2e. |
| cp8 (new) | fanin x2, absorption x2 | - | as r2d | see r2d |

### Shared vs unique

- Systematic (all three, and every run): cp8 absorption through a wire (2 tests). Nobody applies rewrites through
  wire definitions; a rule can make the builder *test* it, but implementing it is task knowledge.
- Systematic in 5 of 6 round-2 runs: fanin-limit with default pipeline (2 tests, r2c excepted); BENCH wire count
  (r2d, r2e excepted); cone assignment order (r2a, r2e).
- Unique (noise-like, but each with a known transferable cause): r2d REDUCE_AND (untested operator), r2d X-in-file
  (boundary rewrite), r2c MUX-X (abandoned known failure), r2c hex prefix (second formatter), r2c bench-export and
  DCE declaration (new command never run on vector / dead-wire fixtures), r2e file-not-found (builtin shadow),
  r2e hex-in-3val (mode x syntax), r2e cp8 crash (nested fixture).
- Only task-specific: absorption laws through intermediate wires. Everything else has a general rule; the problem is
  that most of those rules were already in the skill and were not executed (marked Y*).

## 2. The bad runs and v1's dip

### r2b (62.9): two bail-out sessions, not the skill text

- cp2: 10 s, 2 commands, no edits, skill not read. Final message: "I can't make the requested changes: the workspace
  is in a no-write state, and file-editing tools are unavailable." Sandbox mode was `workspace-write` (transcript
  developer message); the claim is false. 63 tests lost.
- cp3: 12 s, 2 commands, skill not read: "I can't implement this part reliably without the earlier CLI
  specification ... Please provide the earlier parts." 168/205 lost.
- cp4 (skill not read) then built `eval` + vectors + 3val from scratch in 131 s: 229/430; cp5-cp8 kept inheriting
  a program with wrong 3val semantics, crashes on JSON inputs, and format bugs (cp5 `InternalError: sequence item 0
  ... NoneType`, cp7 `test_equiv_invalid_seed` returns no JSON at all).
- The same "read the code, then stop" behaviour appears in round 1 without any skill (none cp2, 10 s; none cp3,
  9 s) and with v5 (cp2, 16 s, skill read, "I haven't implemented eval yet") and v3 (cp2 wrote code, 42 s, "I haven't
  run the CLI"). It is a luna-low failure mode with roughly 3-in-12 incidence at cp2, independent of skill wording
  (r2b's cp2 never read the skill). r2b's `ACCEPTS/REJECTS`, `last_good`, `CLI_DEBUG` rules were therefore never
  exercised; the run says nothing about them. Treat as a wasted sample; compare skills only on runs whose cp2/cp3
  sessions actually edited the file, or run two replicates.

### r2a (87.7): cp3 rewrite broke identifiers, suite too shallow, cp4 without the skill

- cp3 (214 s, 15 commands): rewrote the file, then ran the inherited suite (`diff` clean) and its own Part-3
  fixtures. Three failure classes: (a) tokenizer classifies any identifier whose uppercase is an operator name as an
  operator and raises an invented `CircParseError: Operator call requires parentheses`; the cp1/cp2 comparator
  fixture has a signal named `eq`, so 1 + 16 + 16 tests fail (cp1 check, cp2 eval, cp3 eval) and 11 more at cp4
  (`test_comparator_2bit_3val`) and 1 at cp8 (`test_opt_output_equivalent_to_input`, which optimises the
  comparator). (b) `y = X` in a file -> exit 3 (`literal_x`). (c) The builder "fixed hexadecimal formatting to avoid
  padding beyond the required minimal digits" (`0xf` instead of `0x0f`, `0x1` instead of `0x001`): the checklist
  paraphrased the radix rule ("scalar invariant and vector output formatting") instead of copying "hex padded to
  ceil(width/4)"; v1b copied that sentence verbatim and passed both radix tests.
- Why the suite did not help: at cp3 it held 8 cases from cp1/cp2 (adder, one bad file, usage/version), none with a
  lowercase operator-named identifier, none with `X` in a file, none with hex output. Diff was green while 18 tests
  broke. A suite only remembers what was proven; cheap wins come only if the cases are diverse (every error row,
  every syntax, one fixture per operator).
- cp4 (88 s, 6 commands, skill NOT read): `NAND/NOR/XNOR` return the non-inverted value, `EQ` inverted, `REDUCE_*`
  inverted in 3val (`'y=0' == 'y=1'` on every truth-table row); 41 tests lost and carried to cp8. The session ran
  `bash regress/cases.sh` without diffing, tried two 3val cases (MUX, one reduction), and finished. The suite habit
  persisted without the skill; the "tick after run" habit did not.
- cp7/cp8: cone order (level order), `--passes` ignored in the report (all passes listed), no convergence stop.
- Net: r2a's suite mechanism is not refuted (it caught nothing because it held nothing), but its cost is real: the
  cp1-cp3 sessions spent commands regenerating `expected.txt`; the cp3 session deleted and regenerated it after the
  rewrite, which is the exact moment a stale expected file would have been valuable.

### v1 dip (98.9 -> 91.7): one tokenizer decision at cp3, otherwise noise

- Both v1 sessions at cp3 rewrote the file wholesale, wrote a 20+ item checklist, ran the same spec examples, and
  spent similar effort (v1a 276 s/16 cmds/7 edits; v1b 309 s/13 cmds/5 edits). Neither ran any cp1/cp2 fixture other
  than the adder-style examples they wrote themselves.
- v1a's parser (`if self.peek("("): op=v.upper(); if op not in OPS: error`) only treats a name as an operator when a
  `(` follows. v1b's (`upper=tok.value.upper(); if upper in OPS: take("(")`) reserves every operator name in any case,
  so `eq` fails: 1 + 16 + 16 + 11 + 1 = 45 of v1b's 55 final failures come from this single choice. The other 10:
  `EQ` width check missing at cp3 (1), BENCH wires (1), cp7 cone `.bench` `UnsupportedFeatureError` type and
  truth-table vector formatting (3), cp8 absorption/fanin/equivalence (5; the equivalence one is the comparator again).
- So the 7-point gap is one coin flip in parser design, amplified by regression tests that reuse one fixture across
  five checkpoints. It is noise with respect to the skill text, but the class is preventable: "match keywords only in
  the position where the grammar expects one (name followed by `(`); case-insensitivity never reserves identifiers"
  or, more generally, "any identifier an earlier part accepted must still be accepted after a tokenizer change; run an
  earlier fixture whose names collide with new keywords". v1's wording has nothing about identifiers, keywords or
  tokenizer rewrites; r2b/r2e's "extend, never rewrite" was ignored by every run at cp3 anyway.
- Consequence for evaluation: the three round-2 leaders (99.6/99.3/99.1) and v1a (98.9) are within run-to-run noise
  of each other; the differences between them are 1-4 tests, each traceable to a session-specific choice.

## 3. Which instructions were followed, which caught bugs, which were dead weight

Followed and visibly useful (transcript evidence):
- Checklist extraction (all v1-derived variants, every session that read the skill). Copying sentences verbatim
  matters: v1b's verbatim "hex padded to ceil(width/4)" passed; r2a's paraphrase failed two radix tests.
- Running spec examples through the interpreter: every session that read the skill did it; the no-skill run never
  did. This is the single largest effect (61 -> 98).
- r2d's inside-out/round-trip/idempotence rules at cp8: "The optimized .circ round-trips and the full adder passes
  verification ... compact naming is stable across a second run ... vector BENCH export returns the required error".
  r2d is the only run that passes `test_opt_bench_export_vectors_error`, `test_opt_cse_and_dce_cleanup`,
  `test_opt_postcondition_no_trivial_constants`, `test_opt_absorption_after_flattening` and
  `test_opt_output_equivalent_to_input` together (r2c fails two of these, r2e three, v1b one, r2a one).
- r2d's "printed form follows the declared kind (scalar vs vector)": r2d and r2c passed the cp7 scalar/vector row
  tests that v1a (`0b0` for a scalar) and v1b (`'0000' == '0b0000'`) failed.
- r2c's combination grid at cp3/cp4: r2c is the only run with cp3 fully green (all others lost REDUCE_AND, hex, or
  identifiers) and the only one of the three leaders that passed hex/decimal inputs in 3val mode. r2c cp4's
  transcript shows the grid: MUX/EQ/reduce with X, radix rejection, 2val unchanged, mixed `0xfX` error.
- r2e's persistent suite: run at cp3, cp4, cp6, cp7 even when the skill itself was not opened (cp3, cp6). It produced
  no catch (all diffs clean) but it also cost little (one command per session). It did not prevent r2e's cp4 or cp7
  regressions because it had no hex-in-3val or multi-output cone case.
- "Double-quote values containing shell-special characters" (round 2 addition): still violated once per cp3 session
  (`zsh: unmatched '` in v1b, r2d), costing a command each; harmless.

Present but ignored, or followed without benefit:
- "Extend, never rewrite wholesale" (r2b, r2e): every run rewrote at cp3.
- "Copy to scratch/last_good; three attempts then a smaller step" (r2b, r2e): no session ever copied or restored;
  no session hit three attempts on one failure (the long r2d cp4 loop was a chain of different symptoms).
- "Never name a class like a builtin exception": r2e cp1 did exactly that.
- "Every earlier part: one success and one error command": done with the builder's own trivial fixtures; never caught
  anything in round 2 because the breakages were in identifier handling, hex formatting and 3val semantics that the
  spot checks did not touch.
- "Tick an item only after its run passed": checklists were written (Pass 1) but never ticked; nothing in the
  transcripts shows a second look at the checklist before finishing. r2d cp3 listed the reductions and never ran
  `REDUCE_AND`; r2e cp1 listed the missing-file row and never ran it.
- r2d's absorption checker ("three inputs built to violate the rule, at least one through an intermediate named
  signal"): not executed; cp8 sessions of all leaders were 7-10 commands.
- "Delete scratch/ at the end": r2d cp3 left it; the cp4 session spent 3 messages deciding not to delete inherited
  fixtures. Neutral, but it shows the finish rules get attention that verification rules do not.
- The Finish escape hatch: r2c cp4 finished with a known wrong example ("I'm stopping here with that issue
  unresolved"); r2e cp1 finished with a known suite failure. The round-2 wording only forbids finishing while an
  example *crashes*.

Effort: the leaders' totals (r2d 1876 s / 176 commands, r2c 1238 / 85, r2e 1084 / 76) do not order the scores;
r2d's extra time is one 585 s loop at cp4 that ended with the X-in-file regression anyway. What correlates with
losses is session length at the checkpoint that introduces the bug: r2a cp4 88 s / 6 commands (41 tests), r2b
cp2/cp3 10-12 s (168 tests), r2c cp8 162 s / 7 commands and r2e cp8 155 s / 8 commands (4-6 tests each), all far
below the 1800 s budget. Skill reading is not uniform: r2e read it 3/8 times and still scored 99.1 because the
workspace artifacts (suite, fixtures) carried the habit; r2a's unread cp4 was its worst new-part session.

## 4. Recommendations for round 3

Priorities, grounded in the failure inventory (each item names the tests it targets):

1. Make "known failure" a non-finished state, in the Finish section and in Pass 3: "If any spec example prints
   something other than the spec's text, or any checklist item is unticked, you are not done; fix it before anything
   else." (r2c cp4 MUX: 4 tests; r2e cp1: 1; r2a cp4 would have been forced to run its truth tables.) Remove every
   sentence that lets the builder "name anything unverified".
2. Per-operator/per-branch proof with a discriminating input: "For every operator, mode and error row on the
   checklist, one run whose expected result differs from the trivial one (an all-ones and a mixed value; both a 0 and
   a 1 outcome); an operator you did not run is unimplemented." (r2d REDUCE_AND; r2a cp4 41 tests; r2e hex-in-3val.)
   This is r2c's grid reduced to its most productive cells: value syntax x mode, asymmetric values, nested with a
   literal, several outputs.
3. Tokenizer/keyword rule for the inevitable rewrite: "Keywords are recognised only where the grammar expects them
   (a name directly followed by `(`); case-insensitive matching never reserves identifiers. After any change to the
   tokenizer or grammar, re-run an earlier fixture whose signal names look like keywords, whose literals use every
   radix, and which contains the token the earlier part forbids in files (expect the old error type)." (v1b 45 tests,
   r2a 45, r2d/r2a/v1a X-in-file 1 each.) Drop "extend, never rewrite"; it is not obeyed.
4. Keep r2d's output-contract block (round trip, idempotence, preservation via own `equiv`, counts compared across
   formats, kind-based printing) but turn the postcondition item into a procedure with a fixture recipe: "one fixture
   per numbered guarantee, built to violate it, once through an intermediate named signal; grep the output". Add the
   flag rule: "a flag's guarantee holds with default settings; the example's exit code is not the check, the written
   file is." (fanin 2 tests in 5 runs; absorption 2 in 6 runs; DCE declaration; bench export.)
5. Restore round-1 rules that round 2 dropped and that failed again: "dependency order, ties by name = emit the
   smallest-named ready item each step" (r2a, r2e cone); "one formatter: a new command prints a value by calling the
   function the old command calls, then compare the same value through both commands and both radixes" (r2c hex).
6. Persistent suite: keep it only in the light r2e form (one file, one diff command, never regenerated inside a
   session that changed behaviour), and require one case per checklist row rather than "successes you ran"; r2a's
   suite of 8 trivial cases caught nothing while 18 tests broke under a green diff. Whether the suite is worth its
   ~10 commands per session is still untested (r2e's diffs were all clean).
7. Copy verbatim: "each checklist line is the spec's sentence, not a paraphrase" (r2a hex padding vs v1b).
8. Evaluation hygiene: the leaders are within noise (1-4 tests apart; v1 moved 7 points on one parser choice; a
   3-in-12 cp2 bail-out costs 25-35 points regardless of skill). Run at least two replicates per finalist, drop or
   re-run checkpoints where the session made no edit, and rank by the failure-class inventory rather than by score.

Five hypotheses worth testing as separate variants (all on r2d's skeleton, same description):

- H1 "no-known-failure finish": r2d + item 1 only. Prediction: removes the abandoned-example class (r2c cp4 type)
  and forces truth-table runs at cp4; measurable as zero sessions whose final message admits a mismatch.
- H2 "discriminating-input grid": r2d + item 2 (r2c's grid pruned to value-syntax x mode, asymmetric values,
  nested-with-literal, several outputs, per-operator 0/1 outcomes). Prediction: cp3/cp4 new-part losses go to zero
  (r2d REDUCE_AND, r2e hex-in-3val, r2a 3val semantics).
- H3 "rewrite-safe tokenizer": r2d + item 3. Prediction: eliminates the identifier/keyword and forbidden-token
  regressions at cp3/cp4 (v1b, r2a, r2d), the class with the largest single-run variance.
- H4 "postconditions as fixtures + flag guarantees": r2d with its postcondition block rewritten as the fixture
  recipe plus the flag rule and the two restored round-1 rules (items 4 and 5). Prediction: fanin 2 tests, DCE, cone
  order and second-formatter failures disappear; absorption-through-wire is the residual.
- H5 "r2e-light suite on r2d": r2d + the one-diff persistent suite with one case per checklist row. Prediction:
  no gain on unique bugs, but it converts each caught bug into a permanent case; test whether cost (commands per
  session) stays under ~10 and whether unread-skill sessions still run it (as r2e's did).

Not worth another variant: r2b's ACCEPTS/REJECTS inventory and `last_good` (never exercised, and the only run that
carried them was destroyed by unrelated bail-outs); "extend, never rewrite" (universally ignored); any rule addressed
at the description or at making the model read the skill (r2e scored 99.1 reading it 3/8 times because its workspace
artifacts carried the behaviour, while r2a's one unread session cost 41 tests: the workspace, not the prose, is what a
fresh conversation reliably sees, so instructions that leave files behind (`regress/`, fixtures with descriptive names)
are the robust channel).
