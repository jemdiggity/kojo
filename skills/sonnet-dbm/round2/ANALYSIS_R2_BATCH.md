# Round 2 batch analysis (fresh Fable 5.1): sm2, sonnet55:medium, database_migration
Scores: s2c 95.7, none 95.3, s1c(rerun) 94.3, s2e 92.3, s2d 92.2, s2b 92.1, s2a 91.9. No-skill spans 92.5-95.3 over 5 runs; s1c 95.4 then 94.3.

## Failure buckets (223 failed test-runs in the 7 sm2 runs)
- Spec ambiguity / grader disagreement, persistent in every run (51%): default_value bound as literal (spec only shows null; sibling field uses SQL-literal quoting); transform on missing column (spec says "must exist or will be created", test expects error); stored constraint definition as a SQL string (spec example only shows a dict); `migrate --migrations-dir` applying deps (spec documents option only for validate/migrate-all). Realistic generic-skill ceiling ~96.8-97.2 (about 2.8 pts are unfixable without leakage).
- Skill-induced harm (29%): the round-2 base sentence "Do not add fields to emitted records beyond what the spec shows" plus "emit the spec's exact shape" made the model, for op types with no example, drop the operation's own identifier keys (from/to columns) -> 16 test-runs (3.5 pts) in s2a/s2b/s2d/s2e. s1c's wording ("do not add extra metadata to persisted records") scoped the rule to stored state and did not trigger it. Same lesson as round 1: shape rule written without checking what the grader wants.
- Artifact/skill gap (16%, fixed in some runs): object-wrapped stored ops (fixed 7/7 by "tolerate wrapper/list, string/structure" reader line, worth 0.32), UNIQUE restore, dependent-index guard, identity by content (s2b fixed), validate without dir.
- Variance (4%), infra 0, structural 0.

## Lever engagement
s2a: key-set diff never run; reasoning applied "nothing else" and hurt. s2b: parity + identity engaged, +0.45 pts, wiped out by the shape harm. s2c: load_record existed; "hand-write a record first" never ran; its win is the shape wording (no C3) plus variance, and it was cheapest (304 s, $2.03 vs 366 s, $2.36). s2d: replay never done, grep audit once. Process mandates (notes, scripts, replay, audits) are ignored or costly; one-line code-shaping rules transfer.

## Round 3 recommendation
1. Shape rule: for a record type without an example emit the keys every sibling example shares plus each identifier the operation names as a top-level scalar input field (same key name); never add list/computed/descriptive fields; never drop an identifier the input names. (Grader-informed: validate on a held-out problem.)
2. Keep one-line liberal reader rule; drop hand-craft-record verification.
3. Constraints bullets -> one violating command each, listed in the final summary.
4. Identity by content; 5. option parity (one sentence each); 6. short "guaranteed properties survive re-creation".
Keep headline "accept every plausible reading on input, emit the spec's example shape on output" and error discipline. Drop: "do not add fields beyond spec", one serializer per type, key-set diff, replay-first, grep audit, lenient checker, "never stop to ask". Target <=1.5 KB.
Honest expectation: consolidated skill ~96 vs control mean 94.1; single-run comparisons cannot resolve it. Run 3 seeds control vs 3 seeds skill; judge mean, spread (the skill's value is removing the 3.5-pt tail), cost/time, and one held-out problem.
