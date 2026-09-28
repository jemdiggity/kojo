# One-review software factory

Run `PYTHONPATH=src python3.12 -m kojo.factory audit --run-id YOUR-ID` for three offline request/isolation audits (no inference), then replace `audit` with `run` to spend quota.

The pinned Luna/low CLI builds code_search checkpoints 1–5 in separate fresh conversations, carrying only its preceding source. A sixth fresh Luna reviews a disposable copy of the final source against all five public specs. A seventh fresh Luna receives the original final builder source, all specs, and the reviewer's final answer. Reviewer edits are discarded. There is exactly one review/follow-up cycle. No learned skills, cheat sheet, previous attempt outcomes, or hidden tests enter these conversations.

Every session has 300 seconds and the existing native filesystem/network isolation. Subscription quota is checked before and during every call, with the existing 78% remaining floor plus a conservative safety buffer. No automatic retries or resumes. Maximum seven inference sessions. Full native CLI transcripts remain under intermediate/runs; exact input verification receipts, prompts, frozen source and results are retained under results/runs.

The controller grades frozen builder checkpoints and the fixed final program only after all inference has finished or stopped. A quota stop produces partial results, not an automatic continuation. Compare the final builder and fixer on identical cumulative tests. This measures one review workflow on a previously explored task, with extra compute; it does not establish skill learning or generalization. API-equivalent costs use the existing recorded rates; subscription cash cost is unknown.
