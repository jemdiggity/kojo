# database_migration: six medium-effort baselines

All six models strictly passed CP1 only (1/5). Sol 5.6 had the best final raw result, 124/137, one test ahead of Astra and Opus 5.5. Every model passed all 25 new CP3 tests: its strict failure there reflects inherited CP2 failures rather than failure to implement CP3. Existing failed tests persisted across later checkpoints; the growing failure totals largely combine unresolved old contracts with new rollback/dependency failures.

| Model | CP1 | CP2 | CP3 | CP4 | CP5 | Model minutes incl. failed attempts | Known API-equivalent USD |
|---|---:|---:|---:|---:|---:|---:|---:|
| Opus 5 | 39/39 | 50/62 | 74/87 | 102/117 | 115/137 | 57.09 | 20.11 |
| Opus 5.5 | 39/39 | 56/62 | 80/87 | 107/117 | 123/137 | 18.89 | 4.96 |
| Astra 6 | 39/39 | 60/62 | 84/87 | 110/117 | 123/137 | 24.21 | ≥4.70 |
| Sol 5.6 | 39/39 | 60/62 | 84/87 | 110/117 | 124/137 | 25.11 | ≥3.16 |
| Sol 6 | 39/39 | 59/62 | 83/87 | 109/117 | 120/137 | 17.75 | ≥1.03 |
| Sonnet 5.5 | 39/39 | 58/62 | 82/87 | 103/117 | 119/137 | 5.95 | 1.26 |

CP3–5 each contain one upstream skipped CP1 test. Thus 124/137 means 124 passed, 12 failed, one skipped—not 13 failures. We retain the raw benchmark denominator. The skipped test is explicitly scoped to CP1–2.

Costs include interrupted attempts and deduplicate copied resumed sessions by provider session/thread ID. Each Codex model has one interrupted attempt with unavailable aggregate usage, making its known cost a lower bound. Times sum model-session elapsed time, exclude grading, and are affected by concurrency and metadata waits. Sonnet uses corrected published pricing, not the stale CLI cost. No subscription cash spend is inferred. No execution-budget timeout occurred: original Opus attempts failed on HTTP 522; Codex attempts were interrupted by metadata-query failures. Recovery uses new -02 runs and restored completed snapshots; Sonnet -01 is unchanged. Rebuilt environments from requirements are a restart limitation.

## Observed failure mechanisms

### CP2: data movement and exact event contracts

- Opus 5 adds event fields such as `rows_affected` and `columns_created`; exact JSON event comparisons reject them. Many named data-migration failures therefore do not establish that the database changes themselves were wrong. They remain observable-contract failures under the official grader.
- Astra and Sol 5.6 fail the same two tests: SQL-quoted default value handling (`'unknown'` stored including quotes), and accepting/creating a missing transform target that the grader expects to reject.
- Sol 6 and Sonnet emit `columns` for transform events where the expected event schema differs; their two transform-event failures persist. Both also retain the default-value failure. Sonnet additionally fails the missing-target test.
- Opus 5.5 has five column-migration event failures plus the missing-transform-target failure.

### CP3: constraint support succeeds

Every model passes all 25 newly introduced tests. No model repairs its inherited CP2 failures. A strict-only summary hides this substantial shared success.

### CP4: rollback interoperability and behavior

All six fail the prebuilt-database tests for restoring dropped check constraints and foreign keys. Astra raises `AttributeError: 'str' object has no attribute 'get'`; its index restoration also raises `KeyError: 'sql'`. Sol 6 reports missing original definitions. These indicate disagreement with the fixture's stored metadata representation.

Sonnet has the broadest rollback failure set (9/30 new tests), including missing named constraints during rollback, multi-migration rollback, and the transactional-on-failure test. Opus 5 passes 28/30 new tests, the strongest isolated CP4 performance despite the worst cumulative score.

### CP5: dependency discovery and CLI/event mismatches

Astra/Sol implementations reject the requested migration and its copy in the discovery directory as duplicate versions. This breaks simple/transitive/already-applied-dependency cases. Opus 5 and Sonnet reject `migrate --migrations-dir` at the CLI instead. Other failures include missing circular-dependency events, basename-versus-absolute-path output, and validation rejecting an empty columns array in a fixture.

Astra and Sol 5.6 have identical test outcomes through CP4. At CP5, Sol 5.6 uniquely passes `test_validate_command` relative to Astra; their other outcomes remain identical. Astra's failure here is the validation event's absolute path where the test expects a basename. This one formatting contract accounts for Sol 5.6's final lead—not a broad functional advantage.

## Benchmark interpretation caveats

The common failures deserve specification review before treating them all as clear model defects:

1. CP2 says a transform column “must exist (for updates) or will be created (for new columns).” `test_transform_target_column_not_exists` nevertheless requires failure for a missing target without an obvious new-column discriminator. This is at least ambiguous.
2. CP4 describes the persisted `operations` field as a JSON array. The explicit-rollback seed actually stores an object containing `operations` and `rollback_operations`. Other seeds prescribe particular `original_definition` shapes. The tests consume prepared databases rather than always asking each agent's program to generate its own migration history. Success therefore depends partly on serialization interoperability that the prose does not fully specify.
3. The default-value test passes SQL source text `"'unknown'"` and expects the unquoted value. The CP2 prose only says the default is used for NULL source rows; this distinction warrants a closer spec audit.

Official scores are unchanged. These observations are not adjusted scores or proof that every disputed failure is invalid. Likewise, missing CLI flags, incorrect event output, and rollback failures should not all be dismissed as fixture issues. Inspection here used saved grader assertions, public specs, and read-only seed metadata—not inference or agent feedback.

## Implication for factory experiments

This task mostly exposes exact-contract handling, persistence-format assumptions, and unresolved early mistakes. More tokens alone did not improve the outcome: Opus 5 spent the most and finished lowest, while Sonnet finished fastest. A reviewer could target public output examples, persistence compatibility, and dependency discovery, but teaching these exact held-out failures to a new run would make that a diagnostic intervention, not an unseen-task result.

One trajectory per model, with infrastructure recovery, does not establish a stable ranking. Compare correctness with quality measures and inspect production code separately from generated tests before drawing maintainability conclusions.

Reproduce the score/attempt ledger with `python3.12 results/comparisons/20260928-dex-subset/reproduce_migration_analysis.py`. Machine-readable checkpoint failures, new-test results, and attempt accounting are in `migration_analysis.json`. Raw grader evidence is under each selected run's `intermediate/runs/<run-id>/gauntlet/training-build/database_migration/checkpoint_N/grading/evaluation/stdout.txt`.
