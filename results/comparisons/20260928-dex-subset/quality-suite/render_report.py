"""Generate quality interpretation and chart index from measured snapshots."""
import json,statistics
from pathlib import Path
P=Path(__file__).resolve().parent;BASE=P.parent
rows=json.loads((P/'quality.json').read_text())['rows']
models=['opus5','opus55','sonnet55','astra6','sol56','sol6'];names=dict(zip(models,['Opus 5','Opus 5.5','Sonnet 5.5','Astra 6','Sol 5.6','Sol 6']))
release=json.loads((BASE/'model_release_dates.json').read_text())['models']
models.sort(key=lambda m:(-int(release[m]['date'].replace('-','')),names[m]))
problems=['circuit_eval','database_migration','dynamic_config_service_api']
def subset(m,p):return sorted([r for r in rows if '-'+m+'-medium-' in r['run_id'] and r['problem']==p],key=lambda r:r['checkpoint'])
def finals(m):return [subset(m,p)[-1] for p in problems]
def meanfinal(m,k,v='entrypoint-normalized'):return statistics.mean(r['variants'][v]['metrics'][k] for r in finals(m))
lines=['# Code quality across the complete three-problem suite','',
'All 102 accepted checkpoint snapshots analyzed without executing submissions or calling models. Main results include all discovered Python, with extensionless Python entrypoints renamed only in analysis copies. Native filename-discovery and non-test-Python sensitivity results are retained.','',
'## Main findings','',
'Opus 5 leaves the most code and the lowest mean final erosion, but achieves the lowest strict correctness score. Astra has the lowest mean final verbosity on all discovered Python; excluding test-named files raises its score substantially. No single static metric provides an overall model ranking.','',
'| Model | Final SLOC, summed | Test-named SLOC | Final erosion, mean | Final verbosity, mean | Non-test erosion | Non-test verbosity |','|---|---:|---:|---:|---:|---:|---:|']
for m in models:
 fs=finals(m);loc=sum(r['variants']['entrypoint-normalized']['metrics']['total_loc'] for r in fs);test=sum(r['variants']['entrypoint-normalized']['metrics']['test_sloc'] for r in fs)
 lines.append(f"| {names[m]} | {loc/1000:.1f}K | {test/1000:.1f}K ({100*test/loc:.0f}%) | {meanfinal(m,'erosion'):.3f} | {meanfinal(m,'verbosity'):.3f} | {meanfinal(m,'erosion','non-test-python'):.3f} | {meanfinal(m,'verbosity','non-test-python'):.3f} |")
lines+=['','Final metrics are equal-weight means over the three problems. SLOC is summed across only the final snapshots, avoiding duplicate code across checkpoints. “Non-test” is a filename heuristic, not a guarantee that all remaining code is production code.','',
'| Model | Trajectories with erosion increasing | Trajectories with verbosity increasing |','|---|---:|---:|']
for m in models:
 counts=[]
 for k in ['erosion','verbosity']:counts.append(sum(subset(m,p)[-1]['variants']['entrypoint-normalized']['metrics'][k]>subset(m,p)[0]['variants']['entrypoint-normalized']['metrics'][k] for p in problems))
 lines.append(f'| {names[m]} | {counts[0]}/3 | {counts[1]}/3 |')
lines+=['','## Chart guide','',
'The following charts adapt the questions and presentation in [Dex Horthy’s write-up](https://github.com/humanlayer/advanced-context-engineering-for-coding-agents/blob/main/benchmarking-opus-5-on-slop-code-bench.md) and [SlopCodeBench v2](https://arxiv.org/pdf/2603.24755v2). They use our six models and three problems; they do not reproduce the papers’ measured populations.']
figs=[(1,'strict-pass-bars','Strict pass rate'),(2,'checkpoint-grid','Checkpoint pass grid'),(9,'code-volume','Final code volume and function counts'),(10,'test-code-split','Test-named versus other Python source'),(11,'complexity-duplication','Complexity and duplication across checkpoints'),(12,'functions-complexity','Callable count versus mean complexity'),(13,'single-use-functions','Callables with one statically detected use'),(14,'quality-progress','Paper-style normalized erosion and verbosity trajectories'),(15,'quality-by-problem','Erosion and verbosity for each problem'),(16,'quality-test-sensitivity','Quality scores with and without generated tests'),(17,'metric-spread','Relative metric growth in circuit_eval')]
figure_numbers=json.loads((BASE/'figure_numbers.json').read_text())
for _,file,title in figs:
 n=figure_numbers[file]
 lines+=['',f'### Figure {n}. '+(title.replace('circuit_eval','`circuit_eval`')),'',f'![Figure {n}. {title}](../charts/figure-{n:02d}-{file}.png)']
lines+=['','## Metric and coverage details','',
'- Analyzer: `scb-check==0.1.3`, Python 3.12.8, with dependencies pinned in `scripts/quality-requirements.lock`; the same rule engine and `include_all=True` setting used by the pinned benchmark runner.',
'- Erosion is the analyzer’s share of complexity mass in high-complexity callables; verbosity is its union of flagged lines, structural clone lines, and trivial-wrapper lines divided by source LOC. The trivial-wrapper term and current rules mean this is not an exact recreation of the historical paper analyzer.',
'- Figure 14 adapts paper Figure 3: interpolate each problem trajectory to 0%, 25%, 50%, 75%, 100%, then take an equal-weight mean across three problems. This differs from an unspecified original progress-binning implementation. No confidence intervals or statistical-significance claims are made from three trajectories per model.',
'- Figures 11–13 use the same analyzer’s per-callable complexity and usage data. “Single use” means one statically detected reference, not one runtime call. Tests, framework callbacks and dynamic dispatch can distort the count.',
'- Figure 17 uses relative change `(final / initial - 1) × 100`, omitting zero baselines. Large ratios can arise from small initial values.',
'- Tests are identified by `tests/`, `test/`, `testing/`, `test_*.py`, `*_test.py`, `conftest.py`, and `smoke_test*.py`. Other test names may be missed. The non-test variant reruns clone detection and all metrics on the reduced file set.',
'- Python package directories are naturally discovered. Shell entrypoints are left unchanged and excluded from Python metrics; their Python implementations remain discoverable. No shell code is mislabeled as Python.',
'- Source hashes are checked before and after every analysis. Analyzer output, file lists, callable metrics and normalization mappings are recorded in `quality.json`; intermediate copies remain under `intermediate/quality/quality-suite/`.','',
'### Disclosed analyzer fix','',
'Pinned scb-check splits source on Unicode line separators, causing its tokenizer to reject valid Python containing U+2028/U+2029 string contents. Our wrapper supplies a string subclass whose `splitlines()` uses physical LF lines. The original source text and bytes remain unchanged; no analyzer package files or scoring formulas are edited. The patch applies consistently to all snapshots and is recorded as `physical-lines-v1`. A regression fixture compiles valid Unicode-containing Python, verifies its two physical SLOC lines, and verifies unchanged source. Six snapshots contain separator characters and eight snapshots have shell entrypoints omitted from Python analysis.','',
'### Comparisons deliberately omitted','',
'We have not collected Horthy’s TypeScript repository, the paper’s 473-repository human panel, or anti-slop/plan-first experimental runs. Their corresponding comparison figures cannot be reproduced from our data. No historical paper scores or human baselines are placed beside ours as though protocols matched.','',
'## Reproduction','',
'```sh',
'uv venv intermediate/quality-suite-venv',
'uv pip install --python intermediate/quality-suite-venv/bin/python --require-hashes -r scripts/quality-requirements.lock',
'PATH="$PWD/intermediate/quality-suite-venv/bin:$PATH" intermediate/quality-suite-venv/bin/python scripts/scb_quality_suite.py --jobs 2',
'intermediate/reporting-venv/bin/python results/comparisons/20260928-dex-subset/render_quality_charts.py',
'python3 results/comparisons/20260928-dex-subset/quality-suite/render_report.py',
'python3 results/comparisons/20260928-dex-subset/refresh_suite_report.py',
'```','',
'The plotting environment is pinned in `chart-requirements.txt` one directory above. Exact measurements remain in JSON; K/M formatting affects presentation only.']
(P/'QUALITY.md').write_text('\n'.join(lines)+'\n')
print('Wrote quality-suite/QUALITY.md')
