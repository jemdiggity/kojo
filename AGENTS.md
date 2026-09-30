# Repository instructions

Store experiment results in the main checkout, including runs launched from a
linked worktree. Final artifacts belong in `results/runs/`; raw transcripts,
audit evidence, and logs belong in `intermediate/runs/` under the main checkout.
These outputs must survive worktree cleanup.

The harness resolves the main checkout automatically. Leave `KOJO_DATA_DIR`
unset for normal runs; do not override it with the current worktree. Use another
output location only when the user explicitly requests it. Writing experiment
outputs to the main checkout is expected; keep code changes in the task worktree.

Plans, batch records, vendor checkouts, and virtual environments stay in the
task worktree, following the existing launcher conventions.

Do not add agent attribution to commits or pull requests: no `Co-Authored-By`
trailers naming an AI agent and no "Generated with" lines.
