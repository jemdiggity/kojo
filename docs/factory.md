# Stock Codex and SCB checkpoint protocol

Testing is canceled. The historical comparison launcher refuses to resume. A new inference run requires explicit authorization and a new run ID.

## Active factory behavior

`kojo.factory` now uses:

- The pinned upstream SCB `just-solve.jinja` and `slop_code.common.render.render_prompt`, unchanged. The builder receives **only the current checkpoint specification**. SCB handles canary stripping and entrypoint substitution.
- A fresh Codex CLI conversation for every checkpoint, with one persistent builder workspace across the chain. Source, agent-created tests, notes, and virtual environments survive between checkpoints. Frozen submissions exclude environment/cache files, as before.
- The model-provided **stock Codex base instructions**. The factory never sets `model_instructions_file`. Offline and live native transcripts must identify the base as model-provided, and its hash must match between preflight and execution.
- Installed skills isolated separately: host skill discovery disabled, discovered skill paths disabled, and ambient skill catalogs rejected. Generic stock instructions explaining skills are retained; they are not an installed catalog. Host custom config, memories, plugins and MCP integrations remain excluded.
- Official pinned SCB grading outside agent access. No prior grades or hidden tests are passed to builders, reviewers or fixers.

The optional reviewer/fixer stages are our experimental addition, not normal SCB behavior. Their role requests are **user messages**, not base-prompt replacements. They receive the full public contract to review the final program; that does not change current-only builder prompts. The reviewer sees a disposable code copy, and the fixer receives the original builder code plus only the review text. Exactly one review/follow-up cycle is permitted.

## Reproduction without model calls

```sh
PYTHONPATH=src python3.12 -m kojo.factory audit --run-id UNIQUE-ID
KOJO_NATIVE_TESTS=1 PYTHONPATH=src python3.12 -m unittest discover -s tests -q
```

`audit` uses a local dummy endpoint that rejects the request without inference. It checks stock base provenance, exact prompt delivery, tools, runtime access and native sandbox isolation. Native regression tests require macOS sandbox access. `run` is the separate spending action; it has not been restarted.

## Explicit environment differences

This remains a Dockerless macOS execution adapter, not an identical upstream container. Python/CLI/dataset/evaluator versions are pinned. The current local profile exposes the framework Python and pinned libraries, denies outside task-data reads, and disables tool network/package downloads. Virtual environments can persist in the builder workspace; these runtime constraints can still differ from an upstream benchmark image. Do not present results as interchangeable with official SCB leaderboard numbers. The 300-second per-session budget and configurable model/low reasoning are experiment settings.

The upstream references inspected are `agent_runner/runner.py` (current-only spec render and `finish_checkpoint(reset_context=True)`), `evaluation/config.py::get_checkpoint_spec`, and `configs/prompts/just-solve.jinja`, at runner commit `31ceea3add480edb33431e70475c4c70597e6b31`.

## Native shell write fix

Tool subprocesses set both TMPDIR and zsh's independent TMPPREFIX inside their writable source directory. Setting only TMPDIR left heredocs trying to write `/tmp/zsh`. Every isolated preflight now writes nested fixtures and a Python program using heredocs, compiles and runs it, tests Python temporary files, and cleans up. The controller's own TMPDIR stays unchanged so the `:tmpdir` deny rule cannot accidentally deny src.

[Official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) documents tool environment settings. Private-file/global-temp/symlink/network denial checks remain active.

## Historical experiments

Earlier factory runs used cumulative specs and a replacement base prompt. They are **nonstandard diagnostics**, not stock Codex / standard SCB measurements. Preserve their manifests, prompts and outputs unchanged. The old `run_chain run` path and canceled `factory_compare.py --run` launcher are disabled to prevent accidental reuse. Older gauntlet code is historical and is not the active stock factory path.

The canceled comparison used seven Luna sessions plus an Astra chain that was stopped before final results were frozen. Astra review never started. Its quota-floor waiver applied to that batch; the default factory still enforces its configured quota guard. No retries or new model calls were made while correcting this protocol.

## 2026-09-28 authorized stock comparison

The user subsequently authorized a new four-condition batch: Luna builder; Luna review with Luna follow-up; Astra-low builder; Astra-low review with Luna follow-up. Both review arms start from the identical new Luna checkpoint-5 snapshot. `python3.12 scripts/stock_compare.py` prints the plan; `--run` spends subscription usage. This is a distinct authorization and new IDs, not a resumption of the canceled historical batch.

Maximum 14 sessions, 300 seconds each, no retries. Estimated $2–$6 standard-short-context API-equivalent; subscription cash cost unknown. Quota monitoring continues with the previously authorized floor waiver. Snapshot validation now excludes generated environments before rejecting source symlinks, so normal `.venv/bin/python` links do not break checkpoint capture; source symlink escapes remain rejected. Builders use stock base instructions and current-only specs. Reviews are the explicit custom intervention and receive the full public contract. All roles use low reasoning and the same native tools/runtime restrictions.
