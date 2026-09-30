# Round 1 analysis (fresh Fable 5.1): sonnet55:medium on dynamic_config_service_api, no skill (dc1a 68.8%, dc1b 69.7%)
Scores per checkpoint: 45/47 87/93 25/76 43/81 and 45/47 87/93 24/76 47/81. SKIPPED TESTS COUNT AS NOT PASSED.

## Why 46 of 76 cp3 tests (and 15 cp4) are skipped
Test helpers for cp3/cp4 probe "read the current active version" of a name whose versions exist but none is active before the first propose; if that probe is not HTTP 200 with an integer version, the test pytest.skip()s, and dependent tests skip when no proposal exists. Both submissions returned 404 for that state and used null as the "no base version" sentinel (both documented this choice in answer.txt). Reference behavior: 404 only when no versions exist at all; when versions exist but none is active return 200 with an integer 0 sentinel. What-if patch (~330 bytes) lifts cp3 25->71/76 and overall 68.8->~90.7 and 69.7->~91.6, with zero new failures. Largest lever by an order of magnitude (~+21 pts).

## Other clusters
- cp4 lookup with a partial scope (10-11 tests, ~3.3 pts): reference does subset match; cp1 spec says exact match, so nothing in the spec reveals it. CEILING.
- cp2 regression: a later checkpoint added a conditional field emitted as null when not applicable; earlier tests compare whole bodies with exact equality (4 tests x regression, ~1.1). Both runs documented "null".
- cp1 inherit-from-active: both only substituted a whole top-level attribute when omitted; tests expect nested field-level deep merge (~1.6).
- cp3 residuals: merge supersedes approved proposals though spec says "open" (both runs documented the generalization); precondition ("always returns approval_required") must be checked before generic body validation (both validated fields first -> 400); helper error (merge conflict in a preview/diff) surfaced as 422 where the endpoint's spec lists no such code; one ceiling test.
- Noise: route spelling changed by later checkpoint (dc1b served only old form, ~1 pt); strict "must expose A and B" policy check (dc1a lost ~6 tests, dc1b lenient lost none); schema snapshot at propose reused at merge.

## Process
Sessions short (74-590 s), 3-15 Bash calls; verification is throwaway curl/urllib, never pytest, never persisted; earlier checkpoints never replayed. PyPI unreachable; hand-written stdlib engines scored full marks so dependency absence is not an issue. In every big cluster the agent SAW the ambiguity, documented its choice in answer.txt, and chose the losing one (null / 404 / generalize).

## Levers (ranked) - all generic
1. Empty-state walk-through: drive the first use of every new workflow from an empty store; a "read current X" returns 404 only for the exact condition the spec names (identity missing); when the identity exists but X not set yet, 200 with an explicit typed empty/sentinel representation.
2. Type-stable sentinels: an integer-documented field is always an integer in responses and accepted inputs; when numbering starts at 1, 0 means "none yet", never null.
3. Conditional fields are omitted, never null (earlier checkpoints' tests compare whole bodies with exact equality).
4. Endpoint error-set discipline: only emit error codes the spec lists for that endpoint; helper failures (diff/preview/summary) degrade, not surface; preconditions the spec says "always" yield an error are checked before generic field validation.
5. Exact state words: apply a rule to the named status only; do not widen to similar states.
6. Alias every path spelling when a later checkpoint writes an existing route differently.
7. Liberal acceptance where rejection has no explicit example; "must expose A and B" = A and/or B.
8. Field-level inheritance = nested deep-merge.
9. (low transfer) replay earlier checkpoints' worked examples and diff exact bodies.

## AVOID
Notes files, persisted test suites, write-pytest-first mandates; strictness rules; "return 404/409 whenever state doesn't permit"; blanket "use partial matching"; naming fields/endpoints/status tables/sentinel bodies (leakage; catastrophic in prior rounds); "install the real dependency"; "generalize for consistency / choose the more coherent reading"; and any rule about output shape not checked against the grader's comparison semantics.
Likely ceiling: partial-scope lookup, one stubbed-read test, strict-entrypoint literal reading. Realistic target ~93-94%.
