# External defect-count comparison

Figures 6–7 compare our final-checkpoint failing tests with [Dexter’s published chart](https://github.com/humanlayer/advanced-context-engineering-for-coding-agents/blob/f2bc7aec4575418d2d2e83fec078266cc56d3e6a/images/scb-defects.png). His printed values are transcribed, not reconstructed from pixels. Exact source commit/blob and extraction notes are saved in `external_defect_sources.json`.

“All tasks” here means the same three named problems. Totals sum their final snapshots once; repeated failures across earlier checkpoints are not added. The two Opus 5 rows are separate studies. Raw counts do not adjust for different test collections, harnesses, or effort. Dexter’s skipped-test counts and test-level records were not located. Our skipped tests remain separate, not counted as passes or failing tests.

| Model | Study | `circuit_eval` | `database_migration` | `dynamic_config_service_api` | Total failing | Total skipped |
|---|---|---:|---:|---:|---:|---:|
| Sonnet 5.5 | Kojo | 4 | 17 | 19 | 40 | 16 |
| Opus 5.5 | Kojo | 4 | 13 | 23 | 40 | 16 |
| Sol 6 | Kojo | 4 | 16 | 40 | 60 | 16 |
| Astra 6 | Kojo | 0 | 13 | 40 | 53 | 16 |
| Opus 5 | Dexter | 2 | 11 | 9 | 22 | Not reported |
| Opus 5 | Kojo | 58 | 21 | 17 | 96 | 16 |
| Sol 5.6 | Kojo | 7 | 12 | 36 | 55 | 15 |
| Sonnet 5 | Dexter | 7 | 26 | 37 | 70 | Not reported |
| Opus 4.8 | Dexter | 12 | 15 | 14 | 41 | Not reported |

![Figure 6](/Users/jeremyhale/work/kojo/results/comparisons/20260928-dex-subset/charts/figure-06-external-final-failures.png)


![Figure 7](/Users/jeremyhale/work/kojo/results/comparisons/20260928-dex-subset/charts/figure-07-external-total-failures.png)

## Original paper: count data unavailable

The [original paper, v1 Table 1](https://arxiv.org/html/2603.24755v1#S4.T1), reports strict checkpoint rates over 20 problems. These cannot be converted into final failing-test counts for our three problems or the full benchmark. The current public leaderboard also provides aggregate rates rather than the required test counts. The two linked Zenodo manifests contain PDFs, not raw grading records. Missing values below are not zeros.

| Original-paper model | Published strict checkpoint rate | Final failing-test counts |
|---|---:|---|
| Sonnet 4.5 | 5.4% | Unavailable |
| Sonnet 4.6 | 8.5% | Unavailable |
| Opus 4.5 | 10.9% | Unavailable |
| Opus 4.6 | 17.2% | Unavailable |
| GPT 5.1 Codex Max | 10.8% | Unavailable |
| GPT 5.2 | 10.8% | Unavailable |
| GPT 5.2 Codex | 9.7% | Unavailable |
| GPT 5.3 Spark | 5.4% | Unavailable |
| GPT 5.3 Codex | 9.7% | Unavailable |
| GPT 5.4 | 11.8% | Unavailable |
| GLM 4.7 | 4.3% | Unavailable |

Paper models are therefore documented but not given fabricated defect bars. Matching per-checkpoint grading records would let us add the shared subset and a separately scoped full-benchmark total.

## Reproduction

`intermediate/reporting-venv/bin/python results/comparisons/20260928-dex-subset/render_external_defect_charts.py`

Uses saved suite measurements and the transcribed source manifest; no inference or network calls. Derived chart values are in `external_defect_values.json`.
