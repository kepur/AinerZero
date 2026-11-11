#!/bin/sh
# P213 surrogate runs (s4x-p2a, main worlds 0-39 and extrapolation worlds 1000-1019), each under the shared lock.
# Usage: run_surrogates.sh main|extrap ; run from anywhere.
set -e
cd "$(dirname "$0")/../../../../.."
S=reports/V9-S4-P2-DESIGN/r0-review/evidence/surrogates
N=40; [ "$1" = extrap ] && N=20
.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock \
  .venv/bin/python -I -B $S/track_surrogates.py "$1" $N $S/records-$1.json
