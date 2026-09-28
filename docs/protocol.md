# Experiment protocol

## Recorded SCB baseline

- Problem catalog commit: `38d627ecf668a88f88f8d260f8df8df6116e9b03`.
- Official runner commit: `31ceea3add480edb33431e70475c4c70597e6b31`.
- GPT-6 Luna, low reasoning, Codex CLI 0.157.1, Python 3.12.8.
- Five ordered checkpoints of one problem, not five independent tasks.
- Checkpoint 1 reuses the prior frozen submission. Checkpoints 2–5 each get one
  session with a 300-second execution budget.
- Every checkpoint starts a new `codex exec --ephemeral` process without resuming
  a conversation. Saved event traces confirm five distinct thread IDs.
- Previous implementation files, agent-authored checks, and previous public specs
  carry forward. This is fresh conversation context, not an empty codebase.
- Memories, installed skills, user instructions, plugins, and host MCP connections
  are disabled. Offline request capture verifies the skill catalog is absent.
- Native sandbox rules deny the surrounding experiment repository and permit the
  current checkpoint directory. Offline canaries check this before execution.
- Public-spec self-testing is allowed. Hidden tests and grading feedback are
  withheld; all submissions are frozen before independent local evaluation.
- Scoring includes new requirements and previous checkpoint regression tests.
- Subscription quota is checked before, during, and after execution. Floor: 78%
  remaining in the approved weekly window; a conservative buffer stops earlier.
  Missing counters or a different weekly reset fail closed. Rounded account-wide
  counters do not provide an exact dollar cap.

See [recorded results](../results/runs/20260927-code-search-continuation-01/RESULTS.md) for limitations and
cost accounting. The hosted model alias cannot pin backend weights. The SCB static
quality analyzer did not recognize the extensionless entry file; no quality score
is claimed.

## Skill-learning experiment prepared; paid runs pending

Use the same cheap model, tools, execution budget, and development feedback for
baseline, initial skills, and learned skills. Only the skill artifact should vary.
Version revisions; select them on validation tasks and freeze before held-out tests.
Separate whole SCB problems across splits so related checkpoints cannot leak across
training and evaluation. `code_search` results have been inspected and therefore
belong to development data if they influence skill revisions.

A stronger model refining skills must be reported as stronger-model-assisted
learning, with its cost included. No SCB skill updater has run yet. The executable protocol and proposed budget are
in [gauntlet.md](gauntlet.md).
