# Round 1 batch analysis (fresh Fable 5.1): dc2, sonnet55:medium, dynamic_config_service_api
Scores: d1a-empty-state 91.8 (45/47 90/93 70/76 67/81), d1d-combined-card 71.4, d1e-replay 70.5, d1b-error-set 70.2, d1c-exact-words 70.0 (47/47 93/93 25/76 38/81), none 68.4 (earlier no-skill 68.8, 69.7).

## Why d1a fixed the skip gate and d1d/d1e did not
Gate: when a test body has base_version 0, the helper reads "current active"; unless HTTP 200 with an integer version, it skips. Server needs (i) 200+integer on the read for "versions exist, none active" and (ii) propose accepts that integer. d1a: 200 with version 0 and empty config (new branch); d1d and d1e already had 0 in the store and accepted 0 on input, but ADDED a 404 branch to the pre-existing read for a condition the spec doesn't name (violating even their own rule). none/d1b/d1c: null + 404. d1a had zero skipped tests; the rest had 46 (cp3) + 61 (cp4). Dose-response, n=1 each.
d1d ran the state-(b) curl, saw 404, shipped anyway and documented it as a decision; d1e never curled the read and never ran its replay step.
Load-bearing wording in d1a, absent/vacuous in d1d/d1e: (1) "This is a normal state, not an error. Do not reuse the not-found path for it." (2) "Decide what each read returns at each step before writing handlers." (3) "Inputs accept the same sentinel the reads emit, so a client can echo a read straight back into a write." (4) "Keep sentinel handling in one helper so every endpoint agrees." (5) verify step (curl three states) is necessary but not sufficient; wording (1) makes a 404 read as a bug not a decision.
d1a gap: "for each NEW read endpoint" excludes the earlier-part read. Fix: "each read a new write depends on, including reads defined in earlier parts"; add "a not-found in state (b) is a bug in the read: fix the read, do not document it."

## d1a residual failures (cp1 2, cp2 3, cp3 6, cp4 14 failing)
- inherit-from-active whole-attribute substitution instead of nested deep merge (4 test-runs): d1c's field-level-inheritance section fixed it (d1c cp1/cp2 100%).
- route spelling from a later part not served (3): d1c served both; noise for d1a.
- "always error X" precondition validated after body validation (1): d1b passed.
- helper computation failure (merge conflict in preview) surfaced as an error code not listed for the endpoint (1): d1b lever.
- invented reason enum value (1, noise): "only emit outcomes/reason strings the spec lists".
- strict "must expose A and B" (6 tests): d1d's liberal-acceptance line fixed it (A and/or B). Note d1a's base rule "read conditions literally" pushes strict; needs a bridge: literal for error conditions, liberal for what to accept.
- partial-scope lookup (8 tests) and stale-base test quirk (1): CEILING.
Compliance: Skill loaded 4/4 each. Verification is throwaway curl only, no persisted files. Time/cost: d1a +11% / +12% vs control (within spread).

## Round 2 plan
Keep d1a's core verbatim (three base rules, empty-state section, type-stable sentinel bullets, echo-input bullet, one-helper bullet, verify) + two edits above. Drop: "objects {} only if spec shows", "re-run worked examples and compare whole bodies" (never executed). Five variants = core + ONE lever: r2-inherit (deep merge), r2-accept (liberal acceptance with bridge), r2-alias (route spellings), r2-errorset (helper degrade, always-precondition first, only listed outcomes), r2-lean (core only, de-fluffed; tests gate reliability). Realistic ceiling ~97%; merged skill expected 93-95%.
