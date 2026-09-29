# circuit_eval: six medium-effort baselines

Astra 6 alone passed all eight checkpoints. Opus 5.5 and Sonnet 5.5 produced identical test outcomes at every checkpoint; Sonnet used less time and has a lower recalculated API-equivalent cost. Sol 6 was cheapest, but one persistent edge-case failure reduced its strict score to 3/8 despite a 99.81% mean checkpoint pass fraction. Opus 5's early parser regression persisted through the rest of its trajectory.

These are completed baseline runs, not skill learning or review-loop experiments. Each checkpoint used a fresh conversation, the current checkpoint spec, stock provider instructions, and the preceding completed source snapshot. Installed skills/memory were disabled. Original five models ran concurrently; Sonnet ran later alone. All 48 sessions completed without timeout/retry.

## Checkpoint results

| CP | Opus 5 | Opus 5.5 | Astra 6 | Sol 5.6 | Sol 6 | Sonnet 5.5 |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 36/36 | 36/36 | 36/36 | 36/36 | 36/36 | 36/36 |
| 2 | 99/99 | 99/99 | 99/99 | 99/99 | 99/99 | 99/99 |
| 3 | 171/205 | 205/205 | 205/205 | 205/205 | 205/205 | 205/205 |
| 4 | 384/430 | 430/430 | 430/430 | 430/430 | 429/430 | 430/430 |
| 5 | 404/457 | 457/457 | 457/457 | 457/457 | 456/457 | 457/457 |
| 6 | 455/508 | 508/508 | 508/508 | 508/508 | 507/508 | 508/508 |
| 7 | 474/529 | 527/529 | 529/529 | 527/529 | 528/529 | 527/529 |
| 8 | 508/566 | 562/566 | 566/566 | 559/566 | 562/566 | 562/566 |
| Strict checkpoints | 2/8 | 6/8 | 8/8 | 6/8 | 3/8 | 6/8 |
| Mean checkpoint fraction | 91.25% | 99.86% | 100% | 99.80% | 99.81% | 99.86% |

Strict means every required test passed, including regression tests. Fractional score here is the unweighted mean of the eight checkpoint fractions. Cumulative suites repeatedly exercise earlier behavior: these are not 2,830 independent tasks, and parameterized failures can share one cause. For example, Opus 5's 34 CP3 failures largely reflect a single parser restriction.

## What failed and where

- **Opus 5:** CP1–2 were perfect. CP3 rejects the signal name `eq` as a reserved word. Actual grader stderr confirms this for the comparator and shared-vector fixtures. It breaks a previously passing CP1 comparator check and all 16 CP2 comparator cases, and also fails their CP3 repetitions plus the shared vector pipeline. This is a real regression, not just incomplete new functionality. Failures persist and extend to three-valued and JSON vector tests. CP7 adds the invalid-seed errors; CP8 adds optimizer equivalence and absorption failures. More tokens and time did not recover the earlier behavior.
- **Opus 5.5 and Sonnet 5.5:** perfect through CP6, then both fail `test_equiv_invalid_seed[-1]` and `[not-an-int]`. At CP8 those two failures remain and both fail `test_opt_postcondition_absorption` and `_and`. The Sonnet grader shows the invalid seed is rejected with the correct exit code but JSON labels the command `__cli__` instead of `equiv`. Absorption tests find an OR/AND pattern still present through an intermediate assignment. These are specific contract/optimization omissions, not wholesale inability to implement equivalence or optimization.
- **Sol 5.6:** matches the Opus 5.5/Sonnet outcome set through CP7. CP8 additionally regresses `test_bench_errors` and fails two BENCH export tests. The export traceback is concrete: `InternalError: name 'assignment_lines' is not defined`. The four common failures plus these three account for 559/566.
- **Sol 6:** its first failure is CP4 `test_eval_3val_width_one_vector_x`, retained through CP8. Grader stderr treats declared vector `a[0:0]` as scalar and rejects `1'bX`. It correctly handles the invalid-seed cases that four other models miss. CP8 adds the two absorption failures and regresses `test_bench_errors`: a BENCH literal that should be rejected is accepted.
- **Astra 6:** passes all these edge cases and every other required test. This trajectory has neither observed regression nor unfinished checkpoint.

These diagnoses use saved grader assertion output. They identify observed failure mechanisms, not an exhaustive code review or causal explanation of model reasoning.

## Paired differences

Opus 5.5 and Sonnet are identical at the test level across all eight checkpoints. Sol 5.6 is also identical to them through CP7, then loses three CP8 tests without gaining any.

Equal final scores do not imply equal implementations: Sol 6 and Sonnet both score 562/566, but Sol 6 wins the two invalid-seed tests and loses width-one-vector evaluation and BENCH error validation relative to Sonnet. All five non-Astra models share the two final absorption failures. Astra's final gains over Opus 5, Opus 5.5, Sol 5.6, Sol 6, and Sonnet are respectively 58, 4, 7, 4, and 4 tests, with no reverse losses.

The accompanying JSON records every pair's exact wins/losses at every checkpoint, keyed by originating checkpoint and test name. This retains duplicated comparator cases in different checkpoint modules while matching the same test across regression/functionality labeling changes.

## Usage and cost

| Model | Model minutes | Input incl. cache | Cache reads | Output | API equivalent | Cost / strict CP |
|---|---:|---:|---:|---:|---:|---:|
| Opus 5 | 82.56 | 26,384,757 | 25,729,214 | 346,839 | $28.09 | $14.04 |
| Opus 5.5 | 27.46 | 4,920,820 | 4,518,838 | 184,414 | $7.81 | $1.30 |
| Astra 6 | 29.25 | 1,362,517 | 1,107,456 | 53,142 | $6.32 | $0.79 |
| Sol 5.6 | 41.53 | 4,754,813 | 4,429,696 | 114,789 | $5.37 | $0.89 |
| Sol 6 | 24.71 | 3,197,572 | 2,920,192 | 65,435 | $1.79 | $0.60 |
| Sonnet 5.5 | 16.88 | 1,728,926 | 1,464,594 | 129,445 | **$2.64 corrected** | $0.44 |

Time sums model session elapsed time, excludes grading, and is affected by concurrency. Input includes cache reads and, for Claude, cache creation; output already includes thinking tokens, so thinking is not added again. Cross-provider token counts use different tokenizers. Cost per strict checkpoint is descriptive and inherits the correlation between checkpoints; it is not cost per independent successful software task. Only Astra solved the final problem completely, at $6.32 in this run.

**Sonnet cost correction:** raw receipts retain the CLI-reported **$4.9960508**. Official Sonnet 5.5 prices are $2/M uncached input, $10/M output, $0.20/M cache reads, $2.50/M five-minute writes and $4/M one-hour writes. Applying those rates to provider usage gives **$2.6444848**: 106 ordinary input tokens, 264,226 one-hour cache-write tokens, 1,464,594 read tokens and 129,445 output tokens. The report uses that recomputation; no raw receipt was changed. The exact CLI pricing bug is not established. Opus 5 and 5.5 independently reconcile to their reported costs using current official rates. [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)

Codex costs retain the harness's configured API-equivalent estimates. These figures are not subscription bills or verified cash charges. Sonnet remains cheaper than Opus 5.5 even on the uncorrected CLI estimate, but any subsequent aggregate must use consistent corrected pricing.

## Verification, external access and limitations

All 48 saved transcript-verification receipts affirm exact user-prompt inclusion; all run receipts record medium effort and completed status. Claude receipts identify the expected model and stock prompt snapshot; Codex receipts record stock base-instruction provenance. This analysis checked the receipts, not every native transcript line anew. Existing external-access audits cover all 48 transcripts, report no benchmark access, and have no parse/coverage errors or flagged records. Only two events are recorded: Opus 5 CP1 and Sol 5.6 CP1 run `pip install -r requirements.txt`; neither shows fetched benchmark material. These are heuristic transcript audits, not complete egress logs or proof of no contamination.

Dataset pin `38d627ecf668a88f88f8d260f8df8df6116e9b03`; runner `31ceea3add480edb33431e70475c4c70597e6b31`. Claude CLI 2.1.283, Codex 0.158.0; native macOS, no Docker. Provider default output limits differ; Sonnet's audited default is 32K, Opus 5 64K, Opus 5.5 128K. A session can emit more tokens across multiple responses. Sonnet also ran alone after an adapter model-allowlist addition, so this is not perfectly identical execution timing/protocol across all six.

One trajectory per model cannot separate stable model differences from randomness. These tests are highly correlated. Horthy's write-up reports Opus 5 passing circuit CP1–3 (3/8), whereas this run passes CP1–2 (2/8); his exact dataset pin and effort are unspecified, so this is not an exact replication or evidence of a model regression. His 4/17 figure includes the other two problems and must not be compared directly to these circuit-only denominators. [Horthy write-up](https://github.com/humanlayer/advanced-context-engineering-for-coding-agents/blob/main/benchmarking-opus-5-on-slop-code-bench.md)

For future factory experiments, these results motivate checking preserved behavior after syntax changes, validating CLI error envelopes, and testing optimizer postconditions through named intermediate signals. Those are hypotheses for a new held-out experiment, not guidance to inject into reruns scored as untouched baselines. No skill-learning break-even estimate is supported here because no skills were learned.

## Reproduce the analysis

From the repository root, run `python3 results/comparisons/20260928-dex-subset/reproduce_circuit_analysis.py`. It reads saved receipts only, makes no model calls, verifies completed sessions/medium effort/exact-prompt flags, and writes `circuit_analysis.json` with checkpoint metrics, full paired test outcomes, usage, external-access receipts, and SHA-256 hashes of the source receipts. The explanatory diagnosis additionally reads saved `grading/evaluation/report.json` under the matching intermediate run/checkpoint. It does not alter source, scoring, or original receipts.
