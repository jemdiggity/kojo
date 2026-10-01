# Repository instructions

Store experiment results in the main checkout, including runs launched from a
linked worktree. Final artifacts belong in `results/runs/`; raw transcripts,
audit evidence, and logs belong in `intermediate/runs/` under the main checkout.
These outputs must survive worktree cleanup.

The harness resolves the main checkout automatically. Do not override
`KOJO_DATA_DIR` with the current worktree. The main checkout's gitignored `.env`
may set it (for example to the external volume); Kanna setup copies that file
into each worktree and the harness reads it. Use another output location only
when the user explicitly requests it. Writing experiment
outputs to the main checkout is expected; keep code changes in the task worktree.

Plans, batch records, vendor checkouts, and virtual environments stay in the
task worktree, following the existing launcher conventions.

Do not add agent attribution to commits or pull requests: no `Co-Authored-By`
trailers naming an AI agent and no "Generated with" lines.
