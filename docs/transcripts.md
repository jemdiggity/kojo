# Native transcript capture

New `run_session` executions omit `--ephemeral`, while still starting a new CLI
conversation every checkpoint. After exit, the controller finds exactly that
thread's native session JSONL, copies it beside `events.jsonl`, renders a readable
`transcript.md`, and verifies:

- the session ID matches the live CLI event stream;
- recorded base instructions exactly match the supplied instruction file;
- the designated guidance appears in those recorded instructions;
- the exact user specification prompt is present as a recorded user message.

A capture or verification error stops the controller before the next model call.
An interrupted started process also attempts capture. Failure before a thread
starts cannot produce a transcript. Raw session logs and rendered transcripts
stay under ignored `intermediate/runs/<run-id>/`; verification receipts are
published beside each frozen checkpoint. The root-deny tool sandbox blocks
reads of these logs and the user's Codex session directory. Persistence does not
resume a previous conversation or expose its history to the next one.

These are native CLI session records, not provider-side wire receipts. They retain
the input messages, tool calls/results and responses the CLI records. Output may
be truncated by the harness and this does not claim access to unexposed model
reasoning or every internal request. The separate offline HTTP request audit is
retained as additional evidence and is explicitly labeled non-inference.

Older continuation, baseline and guided runs used `--ephemeral`; their missing
input transcripts cannot be recovered. Their log indexes accurately describe
what remains.

Offline verification uses the installed CLI with a local endpoint returning an
error before inference. A native session log containing the input is sufficient
to check capture and input verification; this does not fabricate assistant replies.

The installed CLI help and [official non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode)
describe the distinction between event output and session persistence.
