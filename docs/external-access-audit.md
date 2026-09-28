# External-source auditing

New factory runs enable network access for all roles. Filesystem isolation,
stock base instructions, fresh conversations, and controller-only grading remain
in place. `--no-network` reproduces the historical restricted-network setting.

After each session, the controller inspects its native `transcript.jsonl` and
writes `external-access.json` beside the frozen role/checkpoint results. The
inventory pairs tool calls with outputs and records source URLs, search/package
operations, excerpts, transcript hashes and record numbers. It flags SCBench,
SlopCodeBench, benchmark repositories, and task-specific solution searches.
Ordinary dependency downloads and documentation lookups are inventoried without
automatically being classified as contamination.

Auditing is report-only. Findings, missing/malformed evidence and audit errors
are recorded without stopping model calls, excluding results or assigning a
validity verdict. `review_suggested` highlights evidence for the user to inspect.
The user decides whether the model cheated. A failed targeted request is evidence
of an attempt, not proof the answer was retrieved; inspect the cited tool output.

## Standalone check

```sh
PYTHONPATH=src python3.12 -m kojo.external_access   intermediate/runs/RUN/gauntlet/training-build/code_search/checkpoint_1/transcript.jsonl   --output intermediate/audits/RUN-checkpoint-1.json
```

A successfully written report exits 0 even when findings are flagged. This command makes no model calls.
Raw transcripts stay under ignored `intermediate/`; compact audit receipts
accompany frozen results.

## Requirements

The agent owns `requirements.txt`, and can install packages during development.
For network-enabled grading, each frozen source snapshot gets a fresh virtual
environment with those requirements installed. The controller saves pip's
`dependency-install.json` (resolved artifacts, URLs and hashes) and
`dependency-freeze.txt` alongside that checkpoint's final results. These files
are separate from the agent transcript and should also be inspected when
reviewing dependency sources. Unpinned requirements may resolve differently on
a later run; use the receipts to identify the evaluated versions.

## Limits

This is a heuristic transcript audit, not packet capture or proof of absence of
contamination. URLs in outputs can be references rather than fetched resources.
Generated/encoded scripts, redirects, transitive package downloads, missing tool
outputs and truncation can conceal destinations. Coverage notes are retained;
`no_benchmark_access_observed` is deliberately not an automatic validity verdict.
Reports are written after each session; findings never gate execution.
