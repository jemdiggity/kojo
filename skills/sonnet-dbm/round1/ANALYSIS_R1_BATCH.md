# Round 1 batch analysis (fresh Fable 5.1): sm1, sonnet55:medium, database_migration
Scores: s1c 95.4, none 93.5, s1d 93.4, s1a 92.2, s1e 70.2, s1b 53.3. (baselines earlier: 95.1, 92.5; noise several points.)

## Collapses (s1b, s1e): one instruction, fully attributable
Tests compare event streams with EXACT list equality (about half of tests per checkpoint). s1b/s1e said the spec example is a "floor, extra keys are free, missing keys fail"; the agent added extra keys to events (columns, description, column_type) -> every exact-equality test containing that event failed (19/39 cp1 for s1b, 9/39 for s1e), persisting to cp5. s1b's "record decisions in NOTES.md so later checkpoints preserve it" locked the mistake in for all 5 checkpoints. Root error: the round-1 lever "extra keys are cheaper than missing" was inferred from one failing test without checking grader comparison semantics. The no-skill model already leans to adding helpful extra keys (control lost 8 test-runs on one extra key on an event type with no spec example); the skill turned a tendency into policy. s1c's line "emit the spec's exact shape on output" is the only positive signal: its whole edge over control (60 vs 58 at cp2, carried x4) came from that.

## Clusters (both/most runs, incl. none): not fixed by any skill
- cp2 default_value stored as quoted literal instead of SQL-literal; cp2 transform on missing column auto-creates while tests expect error (spec text ambiguous); cp4 dependent-object rollback guard (spec Constraints bullet) missed in 8/8; cp5 single-file migrate with --migrations-dir rejected as usage error (option parity across subcommands); cp5 same-version copy of the target file outside the dir counted as duplicate (identity by content, not path).
- s1c fixed: extra-key (via exact-shape line), object-wrapper stored state (code branch), UNIQUE restore (weak). s1c did not fix: string-encoded stored definitions; added new failure: required its own stored rollback_operations for drop_index instead of reading the spec'd original_definition; still added a schema column despite "no extra columns".
- s1d = control (check.sh genuinely built, 300 lines, +30-70% time, 0 gain, false confidence: replays the agent's own reading). s1a = control minus noise; its NOTES.md checklist was never created.

## Compliance
Skill loaded once per checkpoint in every run, but content compliance was thin: NOTES.md checklists never created (s1a,s1c,s1e); "run spec examples verbatim" skipped in every run; "hand-craft a stored record" never done (yet the "read liberally" text still changed the code). Zero Write/Edit calls; code via heredoc and python str.replace. Text instructions that change code transfer; process mandates (notes, scripts) are ignored or costly.

## Round 2 levers (one change each)
1. Exact output shape: emit exactly the spec example's key set per record type; when a type has no example copy the nearest sibling's identifier keys, add nothing; diff emitted keys against spec examples before finishing.
2. Option parity: any documented option accepted by every subcommand where meaningful (shared parent parser); verify by running each documented option against each subcommand.
3. Stored-state reader covers every documented encoding (structured and serialized; bare and wrapped); writer never widens schema (no added columns/keys); verify by writing such a record by hand first.
4. Constraint-to-code audit: for every bullet under Constraints/Error Handling/Rules name the line that enforces it; make it a required final grep step, not a notes exercise.
5. Identity by content, not path: same content reached by two paths is one item; conflict only when contents differ.
6. Mechanical example replay: first verification command materializes the spec's example files and runs the spec's command lines unchanged.
7. A lenient checker (validate/dry-run) never rejects what the applier accepts.
8. Keep budget flat: no mandated persistent artifacts.

## AVOID
"Extra keys are free / example is a floor / echo every identifying field / add fields until reconstructable"; "record decisions in NOTES.md so later checkpoints preserve it"; levers inferred from a single failing test without checking grader semantics; never paste failure content or its inferred fix into skill text; "add stored fields to be safe"; strict "validate syntax" wording; long union-heuristic checklists.

## Keep from s1c
Headline "accept every plausible reading on input, emit the spec's exact shape on output"; write exactly the spec schema, no extra columns; read liberally (wrapper vs list, string vs structure); no silent degradation (prefer heavier existing path); error discipline (usage errors from parser only; `Error:` + exit 1, no traceback). Drop/mechanize "prove once per checkpoint" and NOTES.md.
