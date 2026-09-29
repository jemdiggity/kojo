# SCB static quality analysis

The [paper, §2.3](https://arxiv.org/html/2603.24755v1#S2.SS3) defines:

- Erosion: fraction of `CC × sqrt(SLOC)` complexity mass in callables with cyclomatic complexity greater than 10.
- Verbosity: union of AST-grep-flagged and clone lines, divided by source LOC.

The pinned SCB runner already invokes `uvx scb-check==0.1.3 check --report --include-all` in `src/slop_code/metrics/checkpoint/driver.py`. Our standalone `scripts/scb_quality.py` reuses this analyzer without touching the solver harness, executing submitted code, or calling a model. Python 3.12.8 and tool dependencies are pinned in `scripts/quality-requirements.lock`. Package source: https://github.com/gabeorlanski/scb-check.

This is the current pinned benchmark implementation, not a verified exact reconstruction of the March paper's rule set. Version 0.1.3 also unions trivial-wrapper lines into verbosity and reports cognitive erosion separately. We retain the full report and use cyclomatic `erosion` for the primary metric.

## Reproduce

```sh
python3.12 scripts/scb_quality.py \
  20260928-circuit-eval-astra6-medium-01 \
  --output results/comparisons/astra-quality-new
```

Use a fresh output name. Multiple run IDs can be supplied. Only completed, hash-verified frozen build checkpoints are analyzed. Source hashes are checked again afterward. Existing receipts and source remain unchanged. Raw analysis copies and stderr live under `intermediate/quality/<output-name>`; final JSON and Markdown are saved in the requested output directory. This works after any run, including resumed trajectories; use only the selected latest run per trajectory to avoid duplicate checkpoints.

## Coverage and comparability

The analyzer discovers only `.py` files. SCB entrypoints are often extensionless; a native scan can therefore report zero quality problems while omitting the entire implementation. We report two variants:

1. `upstream`: untouched analysis copy, native file discovery.
2. `entrypoint-normalized`: rename the designated Python entrypoint to `<entrypoint>.py` in a separate copy, without changing bytes or retaining a duplicate. Parsing is validated, and name collisions fail explicitly.

The second is a disclosed coverage adaptation, not an exact upstream invocation on the original filenames. It includes agent-written tests and any discoverable vendored Python per upstream defaults. Inspect file/LOC coverage and retained stderr before comparing models. Zero files/functions means absent coverage, not clean code. These are static proxies, not a proof of maintainability or correctness; interpret alongside test scores. No analysis feedback goes to agents.

The initial six-model circuit report is under `results/comparisons/20260928-dex-subset/quality-circuit/`. All eight checkpoints are included, allowing start-to-final changes as well as final values to be compared.

## Complete three-problem suite

`scripts/scb_quality_suite.py` analyzes all 102 selected frozen snapshots using the
pinned analyzer API, retaining per-file and per-callable metrics as well as the
CLI-equivalent score report. Native discovery, normalized entrypoints and a
non-test-Python sensitivity variant are recorded. Shell launchers are excluded
from Python analysis; package directories are discovered normally.

A disclosed `physical-lines-v1` adapter fixes the upstream analyzer's use of
`str.splitlines()` on Unicode separators embedded in valid Python strings. It
changes line framing only, preserves source bytes, and leaves installed package
files untouched. Three regression tests and agreement with all 48 previous
`circuit_eval` checkpoints validate the change.

Report and reproduction: `results/comparisons/20260928-dex-subset/quality-suite/QUALITY.md`.
The latest linked paper is v2 (May 2026). Figures inspired by its layout use our
own models and three-problem trajectories, with interpolation and metric-version
differences explicitly documented.
