#!/bin/sh
# Re-run exploration round F on the first 3 main worlds (no extrapolation worlds), under the shared lock.
# -B: no bytecode written into tier1-explore/__pycache__. Run from the repository root.
set -e
cd "$(dirname "$0")/../../../../.."
OUT=reports/V9-S4-P2-DESIGN/r0-review/evidence/repro
.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock \
  .venv/bin/python -B reports/V9-S4-P2-DESIGN/tier1-explore/explore_p2f.py 3 0 $OUT/results-p2f-first3.json
