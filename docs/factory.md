# One-review software factory

Run `PYTHONPATH=src python3.12 -m kojo.factory audit --run-id YOUR-ID` for three offline request/isolation audits (no inference), then replace `audit` with `run` to spend quota.

The pinned Luna/low CLI builds code_search checkpoints 1–5 in separate fresh conversations, carrying only its preceding source. A sixth fresh Luna reviews a disposable copy of the final source against all five public specs. A seventh fresh Luna receives the original final builder source, all specs, and the reviewer's final answer. Reviewer edits are discarded. There is exactly one review/follow-up cycle. No learned skills, cheat sheet, previous attempt outcomes, or hidden tests enter these conversations.

Every session has 300 seconds and the existing native filesystem/network isolation. Subscription quota is checked before and during every call, with the existing 78% remaining floor plus a conservative safety buffer. No automatic retries or resumes. Maximum seven inference sessions. Full native CLI transcripts remain under intermediate/runs; exact input verification receipts, prompts, frozen source and results are retained under results/runs.

The controller grades frozen builder checkpoints and the fixed final program only after all inference has finished or stopped. A quota stop produces partial results, not an automatic continuation. Compare the final builder and fixer on identical cumulative tests. This measures one review workflow on a previously explored task, with extra compute; it does not establish skill learning or generalization. API-equivalent costs use the existing recorded rates; subscription cash cost is unknown.

## Native shell-write preflight

The harness sets both `TMPDIR` and zsh's independent `TMPPREFIX` inside each session's writable `src`. The previous harness set only TMPDIR/TMP/TEMP; zsh still used `/tmp/zsh` for heredocs and failed under the global `/tmp` deny rule. No sandbox read permissions were broadened.

These are tool-subprocess overrides via `shell_environment_policy.set` ([official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)). Do not set the controller's own TMPDIR to src: the `:tmpdir` deny rule resolves against the controller environment and would then deny source access.

Every isolated session's no-inference audit now writes a Python program and nested fixture with zsh heredocs, compiles and executes it, and checks Python temporary-file access. The smoke script fails on any failed command and cleans up afterward. This tests the native sandbox execution path with the same tool environment; it does not call a model or replay a synthetic model tool response. Existing audits still verify private files, symlink escapes, global temporary files and network access are denied.

Run the native regression test on macOS with sandbox access:

```sh
KOJO_NATIVE_TESTS=1 PYTHONPATH=src python3.12 -m unittest discover -s tests -q
```

The test first reproduces the old heredoc failure, then verifies the repaired write/compile/run flow and empty source directory. On 2026-09-27 all 28 tests and all three factory role audits passed without model calls. Historical benchmark scores are unchanged; no factory rerun was launched for this repair.

## Authorized Luna/Astra comparison

`python3.12 scripts/factory_compare.py` prints the fixed plan; add `--run` to execute it. Run IDs are single-use. Sequence: five fresh Luna builds + Luna review + Luna follow-up; five fresh Astra-low builds without review; Astra-low review of the **same frozen Luna builder source** + a separate fresh Luna follow-up. The Astra reviewer never sees the Luna review or its follow-up. All roles have 300 seconds, no learned guidance, the same public-spec prompts and repaired sandbox. This is 14 sessions total, no retries. The review feedback heading is model-neutral in both arms. Builder-model comparisons have equal five-checkpoint budgets; review arms share their initial source and have equal budgets. These remain single-sample exploratory results.

For this explicitly authorized batch, `--monitor-only` records quota throughout but waives the old weekly floor, following the user's instruction not to worry about the guard. The default factory still enforces the guard. No API keys or paid-credit resets are used. CLI subscription cash cost is unknown. Estimated API-equivalent cost before launch was $2–$6, with a hard execution cap of 14 × 300 seconds and no direct API billing. Dollar equivalents use standard short-context rates: Luna $0.10/$0.01/$0.50 and Astra $10/$1/$50 per million input/cached/output tokens ([official Astra pricing](https://developers.openai.com/api/docs/models/gpt-6-astra)). They are estimates, not subscription charges or exact long-context/service-tier billing.
