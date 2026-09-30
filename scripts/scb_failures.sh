#!/bin/bash
# Usage: scb_failures.sh RUN_ID [STAGE=build] [PROBLEM=circuit_eval] -> pytest failure output per checkpoint under .tmp/analysis/RUN_ID/
# Re-runs the official tests against each saved submission and keeps assertion detail.
set -u
W="$(cd "$(dirname "$0")/.." && pwd)"; R=$1; STAGE=${2:-build}; P=${3:-circuit_eval}
DATA=${KOJO_DATA_DIR:-$W}; PY=$W/intermediate/scb-runner-venv/bin/python
ENT="$W/.venv/bin/python $W/scripts/scb_entrypoint.py"; OUT=$W/.tmp/analysis/$R; mkdir -p "$OUT"
T="$W/intermediate/vendor/scb-problems/$P/tests"
for d in "$DATA"/results/runs/$R/$STAGE/checkpoint_*; do
  n=${d##*_}; [ -d "$d/submission" ] || continue
  if [ "$P" = circuit_eval ]; then S=$(ls -d "$d"/submission/circopt* | head -1); cd "$T"
  else S=$(grep '^entry_file:' "$W/intermediate/vendor/scb-problems/$P/config.yaml" | awk '{print $2}'); cd "$d/submission"; fi
  $PY -m pytest -q -p no:cacheprovider --tb=short \
    $(for k in $(seq 1 $n); do echo "$T/test_checkpoint_$k.py"; done) "--entrypoint=$ENT $S" --checkpoint=checkpoint_$n -rf 2>&1 | cut -c1-300 > "$OUT/checkpoint_$n.txt"
  echo "checkpoint_$n: $(tail -1 "$OUT/checkpoint_$n.txt")"
done
