# Round 1 analysis: sonnet55:medium on database_migration, no skill (fresh Fable 5.1)

Evidence: sm0a 95.1% (39/39 60/62 84/87 108/117 123/137), sm0b 92.5% (39/39 56/62 80/87 106/117 123/137). Both strict 1/5.
Every failure is introduced at the checkpoint that adds the feature and persists as a regression (earlier tests are re-graded), so a cp2 bug costs ~4x.

Systematic (both runs): cp2 default_value bound as literal instead of SQL-literal/expression like sibling `value` field (4/run); cp2 transform_data on nonexistent column auto-creates it, tests expect error (4/run); cp4 pre-seeded `_migrations.operations` in unanticipated shapes crash (object wrapper with rollback_operations; constraint original_definition as SQL string not dict) (6/run); cp4 drop_index rollback event lacks `table` (2/run); cp5 `migrate <file> <db> --migrations-dir <dir>` rejected as usage error (3/run).
Noise (one run): UNIQUE not restored on rollback (ALTER fallback dropped it instead of using existing table-rebuild path); dependent-index rollback guard listed under "Constraints" never implemented; validate deduped target file by realpath so a same-version copy outside the dir collided; migrate_column_data event omitted from/to column (16 test-runs!).

Process: sessions 36-122 s, 2-7 tool calls per checkpoint; happy-path-only manual test; answer.txt admits untested error/rollback paths, exactly where failures are; no persistent test script; ambiguities resolved by a documented guess (every guess lost); broad `except ValueError` turned a data bug into a Usage message; tools only round-tripped state they wrote themselves. cp3 (longest sessions, error paths exercised) was clean in both runs.

Levers (ranked):
1. Enumerate-then-execute: checklist of every bullet under Constraints/Error Handling/Requirements and every Example; run a command for each before finishing.
2. Spec silent/ambiguous -> implement the union of readings (expression-then-literal; accept options anywhere; accept list or object wrappers; file inside or outside dir), never pick one.
3. Output events: echo every identifying field the op carries (type, table, name, column, from/to...), at least the example's fields plus identifiers; extra keys are cheaper than missing.
4. Persisted state is an external interface: write exactly the spec'd schema (no extra columns), read liberally, hand-craft a state literally following the spec and read it back; unparseable -> `Error:` + exit 1, no traceback.
5. Never silently degrade a guaranteed property because a shortcut fails; use the heavier existing path (rebuild) or error.
6. Run spec examples verbatim AND one perturbation each (different dir, option order, NULL, quoted vs bare value).
7. Keep a persistent regression script across checkpoints replaying prior examples/error cases; run before submitting.
8. Error discipline: no broad except around CLI; usage errors only from arg parser; all else `Error: msg` stderr exit 1.

Likely to backfire: "be strict / reject unlisted" (breaks accept-both); "add extra metadata columns"; "ask/stop on ambiguity" (non-interactive; say implement both); heavy TDD mandate (sessions 40-120 s; cp3/cp4 currently clean); "follow spec examples exactly" for event shapes (examples are a floor); refactor-for-reuse without regression script; anything naming specific fields/tests/seed shapes (benchmark leakage; must stay generic).
