# Claude Code adapter

The factory can select `claude-opus-4-6` or `claude-sonnet-4-6` for a builder or
reviewer. The fixer uses the builder's model. Claude Code is pinned to **2.1.283**;
The adapter resolves the installed versioned executable directly, avoiding the auto-updated `claude` symlink; version drift fails preflight. Live Sonnet trials and their frozen configurations are recorded under `results/runs/`.

## Controls

- Stock CLI system instructions: no replacement, append, or `--bare` flag.
- `--safe-mode`, `--disable-slash-commands`, empty setting sources, strict empty
  MCP configuration, and disabled hooks/memory. Installed customizations stay off.
- Explicit model IDs and `--claude-effort low|medium|high` (factory default: low).
  The adapter sanitizes inherited provider/model/effort environment overrides.
- As in SCB's adapter, the legacy thinking budget is also set: 4,000 / 10,000 /
  31,999 tokens. The audited 4.6 requests actually use **adaptive thinking** and
  the selected effort; these numbers must not be represented as effective caps.
- Fresh session UUID at every build/review/fix; source and virtual environment
  carry forward according to the existing factory protocol.
- Native restricted mode and sandboxed Bash; six native shell/file tools.
  Home-directory reads are denied except the source workspace. Native file tools
  cannot read the controller or grading data. Claude's necessary temporary
  bookkeeping directories remain available; this is not an identical sandbox
  or toolset to Codex.
- An empty Git repository inside the initial source directory prevents Claude
  from including the parent factory's history/status in its prompt. Git metadata
  is excluded from submissions.
- Network enabled by default. External sources are inventoried from Claude's
  native transcript using the same report-only policy as Codex.

## No-inference verification

```sh
PYTHONPATH=src python3.12 -m kojo.factory audit \
  --run-id claude-adapter-opus-high-final \
  --build-model claude-opus-4-6 --claude-effort high --no-review
```

The audit sends requests to a loopback dummy endpoint with fake credentials,
returns scripted tool calls, and checks native shell writes, blocked controller
reads through Bash and Read, an exact task prompt, model/effort, and native
transcript/system-prompt capture. It plants a dummy user instruction and skill
and checks their canary is absent. With networking enabled it also fetches PyPI
package metadata to confirm HTTPS works; this incurs no model inference.

Verified locally: Opus 4.6 high and Sonnet 4.6 high/medium; requests emitted adaptive thinking. The explicit 128,000 output-token override was also verified on the wire without inference.
The complete factory audit with the actual checkpoint-one prompt passed for
both models; the final Opus audit also checked PyPI access. Raw evidence stays
under `intermediate/claude-adapter-preflight/` and
`intermediate/runs/claude-adapter-*/offline-audit/`.

The live session path records streamed events, copies the native transcript,
verifies the exact task/model/effort and system-prompt snapshot, saves the final
answer, and enforces the existing wall-clock timeout. Claude's reported list-price
cost and cache-aware token usage are normalized into factory accounting.
Missing terminal usage remains unknown, rather than zero. Authentication was
checked separately: a Claude Max login is available. No credentials are recorded.

Live Sonnet runs have completed CP1/CP2 and encountered response limits and
wall-clock timeouts at CP3. See each run's report rather than treating an
incomplete trajectory as five measured checkpoint scores. Claude subscription
quota is separate from Codex. The user explicitly requested usage reporting
after each checkpoint with no usage-based stopping rule; no CLI dollar cap is
supplied for these runs.

## Comparability

This is an additional provider adapter for the same controller, not an exact
paper replication. The paper used Claude Code 2.1.32 for Opus 4.6 and 2.1.44 for
Sonnet 4.6, both high (Appendix A), with two hours per checkpoint. Our factory
retains its ten-minute default and current CLI. Model identity alone does not
make results directly comparable.

Builder prompts use the pinned upstream `just-solve` renderer and current-only
specification. Review/fix prompts are separately versioned custom interventions.
The paper's Appendix B calls the template a system prompt, but the pinned
upstream Claude adapter appends the rendered task as a CLI positional prompt;
its separate append-system-prompt option is optional. We preserve that distinction.

Sources: [SCB paper, Appendices A/B](https://arxiv.org/html/2603.24755v1),
[Claude CLI](https://code.claude.com/docs/en/cli-reference),
[sandboxing](https://code.claude.com/docs/en/sandboxing),
[environment variables](https://code.claude.com/docs/en/env-vars).

## Sonnet run management

The launcher reads `configs/experiments/sonnet-46-baseline.json`. Each trial keeps
an immutable copy in `results/runs/<run-id>/experiment-plan.json`. The successive
trials are distinct experiments: high at 10 minutes, an explicit CP2 restart
with 20 minutes, fresh medium at 30 minutes, and fresh medium at 30 minutes with
an explicit 128,000-token response allowance. The last intervention was selected
during authorized run management; it is not a stock-default baseline.

The installed CLI's normal Sonnet 4.6 request uses `max_tokens: 32000`, verified
with both headless and interactive terminal modes against a loopback dummy
endpoint. `--claude-max-output-tokens 128000` explicitly sets
`CLAUDE_CODE_MAX_OUTPUT_TOKENS`; offline verification checks the resulting API
request. Output allowance is per response, includes thinking, and differs from
the checkpoint's wall-clock limit. Raising it does not guarantee completion.

Incomplete checkpoints stop the chain; their source is never carried forward.
`--resume-run` with `--resume-checkpoint` explicitly restores completed source
and rebuilds its environment from requirements.txt. Fresh runs omit both flags.
The launcher forwards cancellation to the controller so its model child can be
terminated and evidence recovered.

```sh
# Print the configured command without inference:
python3.12 scripts/sonnet_baseline.py
# Spend usage on the configured, approved run (requires a new run ID):
python3.12 scripts/sonnet_baseline.py --run
# Rebuild a completed or stopped run's report from its frozen configuration:
python3.12 scripts/report_sonnet_baseline.py --run-id <completed-run-id>
python3.12 scripts/report_sonnet_timeout.py --run-id <stopped-run-id>
# View the running trial:
tmux attach -t sonnet46-baseline
```

Token counts and API-equivalent cost are printed and saved. Missing final usage
is reported as unknown. `--claude-max-budget-usd` remains optional for future
capped runs. External-access reports are transcript inventories, not complete
network logs or automatic validity decisions.

The no-inference smoke script is a temporary plain Python file, removed after
the audit. An encoded inline probe had triggered Claude's command classifier.

The 128k trial completed CP3 but CP4 preflight detected a CLI symlink update to
2.1.284. No CP4 inference occurred. The continuation restores completed CP3 and
uses the still-installed 2.1.283 binary directly. If CP4/CP5 times out, the user
has authorized one retry of the affected checkpoint with a one-hour limit; a
one-hour timeout stops further retries pending instructions. Both the original
and restarted trajectories retain their receipts.
