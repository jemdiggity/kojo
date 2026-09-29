# Language-aware entrypoint grading

`scripts/scb_entrypoint.py` launches entrypoints according to their shebang: Python uses the fresh grading environment's `.venv/bin/python`; `sh` and `bash` use `/bin/sh` and `/bin/bash`. `/usr/bin/env` and `env -S` forms are supported. Without a shebang, `.sh`/`.bash` suffixes select shell, and parseable Python is accepted (including legacy extensionless Python). Unrecognized languages or ambiguous extensionless non-Python source fail explicitly. Arguments and exit codes are preserved without shell interpolation.

This corrects the old grader's unconditional `python ENTRYPOINT` assumption. After all runs became idle, the launcher was integrated into the shared grading environment and included in the protocol digest. The standalone regrading adapter preserves historical results separately.

```sh
python3.12 scripts/scb_regrade.py RUN_ID --output results/comparisons/NEW_OUTPUT
```

Use a new output directory. Each source is verified against its frozen snapshot before and after evaluation. The adapter keeps upstream tests and include_prior_tests settings, uses the normal dependency setup, and writes corrected scores separately. Original raw scores are never overwritten. Grading executes submitted programs, but does not call a model. Detailed grader logs remain under `intermediate/regrading/NEW_OUTPUT`.

The first correction is `results/comparisons/20260928-dex-subset/astra-api-regraded`: Astra's `config_server` is a shell launcher for its Python service, so the old zero scores were all startup syntax errors rather than API assertions.

Directory entrypoints containing `__main__.py` are supported as Python modules
(`python -m package` from the submission root), preserving package imports.
Directories without `__main__.py` and invalid module names fail explicitly.
