# Fresh checkpoint-factory comparison

This batch tests changes to the factory workflow on SCB `code_search`. The user requested all four conditions run again from scratch under the same harness, rather than repairing failed checkpoints or reusing earlier builder outputs.

| Condition | Builder | Reviewer | Fixer | Maximum sessions |
|---|---|---|---|---:|
| Luna | Luna low | none | none | 5 |
| Luna reviewed by Luna | Luna low | Luna low | Luna low | 15 |
| Astra | Astra low | none | none | 5 |
| Luna reviewed by Astra | Luna low | Astra low | Luna low | 15 |

Every condition starts with an empty source workspace. Each reviewed checkpoint runs build → review → fix exactly once. The repaired code and builder environment carry forward to the next checkpoint. Every model invocation starts a fresh conversation. Stock Codex base instructions, installed-skill isolation, tools, Python runtime, pinned dataset/evaluator, and 600-second session limits are common. Builders get only the current upstream SCB checkpoint prompt; review/fix receive public specifications through that checkpoint, plus the appropriate role request and reviewer feedback. Neither receives hidden grades, future specs, earlier-run source, or cheat sheets.

The controller freezes both builder and fixer submissions and grades them only after that condition's model calls finish. The primary checkpoint outcome for reviewed arms is the fixer's submission. Builder snapshots provide within-checkpoint before/after comparisons. Different conditions have independently generated starting implementations; cross-condition differences therefore include model randomness. Reviewed conditions consume additional inference. This is a one-task workflow pilot, not a compute-matched study or a test of learned reusable skills.

The maximum is 40 sessions × 600 seconds (400 model minutes), no automatic retries. Estimated API-equivalent usage is $6–$15 based on the previous pilot; exact subscription cost is unavailable, and this estimate is not a billing guarantee. Weekly quota is monitored with the user's previous floor waiver. Timed-out usage may only yield a lower bound. No large benchmark or Docker images are needed.

`python3.12 scripts/checkpoint_compare.py` prints the exact commands without inference. `--run` executes the explicitly authorized batch using new IDs. It refuses reused IDs and requires one protocol hash throughout all four conditions. A reproduction needs new IDs and explicit authorization before spending again.

The live tmux session is `checkpoint-compare-01`. Controller and preflight logs live under ignored `intermediate/checkpoint-compare-01/`. Each run's source, native transcripts, and scratch are under ignored `intermediate/runs/<run-id>/`; frozen artifacts and grades go under `results/runs/<run-id>/`.

The adapter remains Dockerless macOS with package-network access disabled and a specified Python 3.12 entry command. These restrictions can affect implementations and differ from the official container environment. The preceding batch used 300-second limits and final-only reviews; comparisons with it cannot isolate the effect of time from review placement.
