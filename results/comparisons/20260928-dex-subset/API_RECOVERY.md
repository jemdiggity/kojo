# dynamic_config_service_api recovery — 2026-09-29

Root cause correction: both native transcripts are valid JSONL. `str.splitlines()`
splits Unicode U+2028/U+2029 inside JSON strings as well as physical newlines.
Using LF delimiters with the standard strict `json.loads` reads the original
bytes successfully. No permissive JSON parsing or transcript rewriting was needed.
All harness JSONL consumers now use LF delimiters. Regression coverage includes
Unicode separators and rejection of truncated JSON. Python directory entrypoints
with `__main__.py` now run as modules, preserving imports.

Offline suite: 83 tests run, 82 passed, 1 skipped. Both no-inference native CLI
continuation audits passed. Model, medium effort, exact prompt and stock system
prompt verified for both saved CP2 transcripts.

`recover_api_transcripts.py` created new recovered seed IDs, preserving original
receipts. CP1 frozen hashes match. CP2 came from the terminal workspace; source
mtimes precede the final CLI receipt, hashes match before/after copying, and native
session IDs match. This is a post-event freeze, not an original completion-time
snapshot. No inference was repeated. Original source and failure receipts remain.

Corrected grades using language-aware invocation:

| Model | checkpoint 1 | checkpoint 2 |
|---|---:|---:|
| Opus 5.5 | 45/47 | 91/93 |
| Sonnet 5.5 | 45/47 | 90/93 |

Full grading receipts: `opus55-api-recovered-regraded/regrading.json` and
`sonnet55-api-recovered-regraded/regrading.json`. These are model test failures,
not startup zeros. No grading feedback is supplied to continuation agents.

Approved continuation plan: `intermediate/plans/20260929-api-transcript-recovery.json`.
Batch `20260929-dynamic-config-service-api-recovery`, two parallel runs:
`20260929-dynamic-config-service-api-{opus55,sonnet55}-medium-02`.
Resume is autodetected after verified CP2. Only CP3/4 require new inference.
Settings unchanged: medium, default output limits, no review, 1800 seconds per
checkpoint, network on, memory/skills off, fresh conversations, current spec only.
Environment is rebuilt from completed requirements. No automatic timeout retries.
Deduplicate original/recovered/copied session IDs in final cost accounting.

## Completion

Both resumed runs completed CP3/4 and grading. Opus 5.5: 45/47, 91/93, 25/76, 43/81. Sonnet 5.5: 45/47, 90/93, 24/76, 47/81. Both CP3 collections have 46 skips; both CP4 collections have 15 skips. No timeouts or further inference retries. All 102 accepted suite checkpoints passed source/handoff/transcript hash and prompt/model-effort receipt checks; see suite_verification.json.
