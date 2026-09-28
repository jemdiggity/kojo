# SCB Docker-optional fork review

Reviewed 2026-09-27. GitHub returned 41 fork entries; 40 were accessible and one
returned 404. Compared their default branches to upstream and inspected 32 distinct
additional branch heads after deduplicating shared commits. This covers the visible
fork network, not every independently copied repository or deleted branch.
Read-only review; no new inference, installations, forks or PRs.

## Relevant existing work

[robdmac/slop-code-bench: feat/host-tmux-executor](https://github.com/robdmac/slop-code-bench/tree/feat/host-tmux-executor)
at `147d61d258dfe4252a82973ad210c6aaaef97bca` explicitly implements host/no-Docker workflows. Its
[design document](https://github.com/robdmac/slop-code-bench/blob/147d61d258dfe4252a82973ad210c6aaaef97bca/docs/HOST_TMUX_EXECUTOR.md)
describes optional read-only tmux log viewing, local skill copy-in, and host execution
inside an existing VM. tmux is optional; failure disables the viewer rather than
failing the benchmark. The branch also contains OpenCode credential/config delivery
fixes and many unrelated skill-experiment scripts. It is not a minimal patch or a
verified macOS + current Codex CLI integration. No end-to-end run of this branch was
performed here.

The `kelchm/local-models` branch concerns local OpenAI-compatible model serving,
which is different from removing the benchmark's Docker runtime. Other inspected
Codex changes mainly concern telemetry, model support and experiment workflows.

## Upstream already has local execution

Pinned upstream: `31ceea3add480edb33431e70475c4c70597e6b31`.

- [local-py environment](https://github.com/SprocketLab/slop-code-bench/blob/31ceea3add480edb33431e70475c4c70597e6b31/configs/environments/local-py.yaml): `type: local`.
- [runtime registry](https://github.com/SprocketLab/slop-code-bench/blob/31ceea3add480edb33431e70475c4c70597e6b31/src/slop_code/execution/runtime.py): registers both LocalExecRuntime and LocalStreamingRuntime.
- [run CLI](https://github.com/SprocketLab/slop-code-bench/blob/31ceea3add480edb33431e70475c4c70597e6b31/src/slop_code/entrypoints/commands/run_agent.py): `_prepare_run_artifacts` builds images only for Docker environments; local returns an empty image string.
- [Codex adapter](https://github.com/SprocketLab/slop-code-bench/blob/31ceea3add480edb33431e70475c4c70597e6b31/src/slop_code/agent_runner/agents/codex/agent.py): rejects `image is None`, but the CLI's empty string is not None. Thus this guard alone does NOT establish a Docker requirement. My initial progress update overstated that conclusion.

The Codex adapter still contains container-shaped authentication/HOME assumptions.
Upstream local streaming stores spawn-time env_vars but `_start_process` only merges
per-command env with the environment spec. The fork adds spawn-env merging; that
interacts with the adapter's temporary HOME and needs checking with ChatGPT login.
The existing local YAML also assumes a Python entrypoint and requirements.txt, so
it needs configuration appropriate to the selected problem.

## Recommendation

First exercise upstream's existing local backend with a fake Codex executable and
our frozen submission, without model calls or Docker. Verify auth-path handling,
CLI 0.157.1 compatibility, skill isolation, quota checks and official grading. Patch
only concrete failures; use the host fork as a reference, rather than importing its
whole experiment stack. Keep native Codex filesystem restrictions: separate folders
alone do not hide grading tests from the agent.

No new fork has been created: existing local support makes a blanket Docker-optional
rewrite premature. Raw fork and branch comparisons are preserved in
`intermediate/scb-fork-review/`.
