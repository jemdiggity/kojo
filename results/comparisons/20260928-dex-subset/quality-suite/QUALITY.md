# Code quality across the complete three-problem suite

All 119 accepted checkpoint snapshots analyzed without executing submissions or calling models. Main results include all discovered Python, with extensionless Python entrypoints renamed only in analysis copies. Native filename-discovery and non-test-Python sensitivity results are retained.

## Main findings

Opus 5 leaves the most code and the lowest mean final erosion, despite weak strict correctness. Astra has the lowest mean final verbosity on all discovered Python; excluding test-named files raises its score substantially. No single static metric provides an overall model ranking.

| Model | Final SLOC, summed | Test-named SLOC | Final erosion, mean | Final verbosity, mean | Non-test erosion | Non-test verbosity |
|---|---:|---:|---:|---:|---:|---:|
| Sonnet 5.5 | 6.9K | 0.0K (0%) | 0.836 | 0.445 | 0.836 | 0.445 |
| Opus 5.5 | 10.4K | 0.4K (4%) | 0.747 | 0.381 | 0.740 | 0.388 |
| Sol 6 | 3.8K | 0.0K (0%) | 0.869 | 0.430 | 0.869 | 0.430 |
| Astra 6 | 5.4K | 1.9K (36%) | 0.752 | 0.252 | 0.836 | 0.366 |
| Fable 5.1 | 14.3K | 2.4K (17%) | 0.656 | 0.411 | 0.661 | 0.447 |
| Opus 5 | 21.8K | 9.4K (43%) | 0.455 | 0.299 | 0.535 | 0.393 |
| Sol 5.6 | 4.6K | 0.0K (0%) | 0.818 | 0.482 | 0.818 | 0.482 |

Final metrics are equal-weight means over the three problems. SLOC is summed across only the final snapshots, avoiding duplicate code across checkpoints. “Non-test” is a filename heuristic, not a guarantee that all remaining code is production code.

| Model | Trajectories with erosion increasing | Trajectories with verbosity increasing |
|---|---:|---:|
| Sonnet 5.5 | 2/3 | 1/3 |
| Opus 5.5 | 2/3 | 2/3 |
| Sol 6 | 2/3 | 1/3 |
| Astra 6 | 2/3 | 1/3 |
| Fable 5.1 | 2/3 | 2/3 |
| Opus 5 | 3/3 | 2/3 |
| Sol 5.6 | 3/3 | 2/3 |

## Chart guide

The following charts adapt the questions and presentation in [Dex Horthy’s write-up](https://github.com/humanlayer/advanced-context-engineering-for-coding-agents/blob/main/benchmarking-opus-5-on-slop-code-bench.md) and [SlopCodeBench v2](https://arxiv.org/pdf/2603.24755v2). They use our seven models and three problems; they do not reproduce the papers’ measured populations.

### Figure 1. Strict pass rate

![Figure 1. Strict pass rate](../charts/figure-01-strict-pass-bars.png)

### Figure 2. Checkpoint pass grid

![Figure 2. Checkpoint pass grid](../charts/figure-02-checkpoint-grid.png)

### Figure 9. Final code volume and function counts

![Figure 9. Final code volume and function counts](../charts/figure-09-code-volume.png)

### Figure 10. Test-named versus other Python source

![Figure 10. Test-named versus other Python source](../charts/figure-10-test-code-split.png)

### Figure 11. Complexity and duplication across checkpoints

![Figure 11. Complexity and duplication across checkpoints](../charts/figure-11-complexity-duplication.png)

### Figure 12. Callable count versus mean complexity

![Figure 12. Callable count versus mean complexity](../charts/figure-12-functions-complexity.png)

### Figure 13. Callables with one statically detected use

![Figure 13. Callables with one statically detected use](../charts/figure-13-single-use-functions.png)

### Figure 14. Paper-style normalized erosion and verbosity trajectories

![Figure 14. Paper-style normalized erosion and verbosity trajectories](../charts/figure-14-quality-progress.png)

### Figure 15. Erosion and verbosity for each problem

![Figure 15. Erosion and verbosity for each problem](../charts/figure-15-quality-by-problem.png)

### Figure 16. Quality scores with and without generated tests

![Figure 16. Quality scores with and without generated tests](../charts/figure-16-quality-test-sensitivity.png)

### Figure 17. Relative metric growth in `circuit_eval`

![Figure 17. Relative metric growth in circuit_eval](../charts/figure-17-metric-spread.png)

## Metric and coverage details

- Analyzer: `scb-check==0.1.3`, Python 3.12.8, with dependencies pinned in `scripts/quality-requirements.lock`; the same rule engine and `include_all=True` setting used by the pinned benchmark runner.
- Erosion is the analyzer’s share of complexity mass in high-complexity callables; verbosity is its union of flagged lines, structural clone lines, and trivial-wrapper lines divided by source LOC. The trivial-wrapper term and current rules mean this is not an exact recreation of the historical paper analyzer.
- Figure 14 adapts paper Figure 3: interpolate each problem trajectory to 0%, 25%, 50%, 75%, 100%, then take an equal-weight mean across three problems. This differs from an unspecified original progress-binning implementation. No confidence intervals or statistical-significance claims are made from three trajectories per model.
- Figures 11–13 use the same analyzer’s per-callable complexity and usage data. “Single use” means one statically detected reference, not one runtime call. Tests, framework callbacks and dynamic dispatch can distort the count.
- Figure 17 uses relative change `(final / initial - 1) × 100`, omitting zero baselines. Large ratios can arise from small initial values.
- Tests are identified by `tests/`, `test/`, `testing/`, `test_*.py`, `*_test.py`, `conftest.py`, and `smoke_test*.py`. Other test names may be missed. The non-test variant reruns clone detection and all metrics on the reduced file set.
- Python package directories are naturally discovered. Shell entrypoints are left unchanged and excluded from Python metrics; their Python implementations remain discoverable. No shell code is mislabeled as Python.
- Source hashes are checked before and after every analysis. Analyzer output, file lists, callable metrics and normalization mappings are recorded in `quality.json`; intermediate copies remain under `intermediate/quality/quality-suite/`.

### Disclosed analyzer fix

Pinned scb-check splits source on Unicode line separators, causing its tokenizer to reject valid Python containing U+2028/U+2029 string contents. Our wrapper supplies a string subclass whose `splitlines()` uses physical LF lines. The original source text and bytes remain unchanged; no analyzer package files or scoring formulas are edited. The patch applies consistently to all snapshots and is recorded as `physical-lines-v1`. A regression fixture compiles valid Unicode-containing Python, verifies its two physical SLOC lines, and verifies unchanged source. Six snapshots contain separator characters and eight snapshots have shell entrypoints omitted from Python analysis.

### Comparisons deliberately omitted

We have not collected Horthy’s TypeScript repository, the paper’s 473-repository human panel, or anti-slop/plan-first experimental runs. Their corresponding comparison figures cannot be reproduced from our data. No historical paper scores or human baselines are placed beside ours as though protocols matched.

## Reproduction

```sh
uv venv intermediate/quality-suite-venv
uv pip install --python intermediate/quality-suite-venv/bin/python --require-hashes -r scripts/quality-requirements.lock
PATH="$PWD/intermediate/quality-suite-venv/bin:$PATH" intermediate/quality-suite-venv/bin/python scripts/scb_quality_suite.py --jobs 2
intermediate/reporting-venv/bin/python results/comparisons/20260928-dex-subset/render_quality_charts.py
python3 results/comparisons/20260928-dex-subset/quality-suite/render_report.py
python3 results/comparisons/20260928-dex-subset/refresh_suite_report.py
```

The plotting environment is pinned in `chart-requirements.txt` one directory above. Exact measurements remain in JSON; K/M formatting affects presentation only.
