#!/bin/sh
# Replay round G (first 2 main worlds, first extrapolation world) under the shared lock; run from anywhere.
cd "$(dirname "$0")/../../../../.." || exit 1
.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock \
  .venv/bin/python -I -B reports/V9-S4-P2-DESIGN/r1-review/evidence/repro/replay_p2g.py reports/V9-S4-P2-DESIGN/tier1-explore/results-p2g.json 2 1
