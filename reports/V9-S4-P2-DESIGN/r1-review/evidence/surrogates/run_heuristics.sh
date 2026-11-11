#!/bin/sh
# P215: response sanity check, then the crude-response arms on s4x-p2a main worlds 0-39, each under the shared lock.
# A busy lock (exit 75) is retried every 30 s; the lock is never bypassed. Run from anywhere.
cd "$(dirname "$0")/../../../../.." || exit 1
S=reports/V9-S4-P2-DESIGN/r1-review/evidence/surrogates
H=reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py
L=artifacts/locks/m0-worker.lock
run() { while :; do .venv/bin/python $H $L "$@"; rc=$?; [ $rc -ne 75 ] && return $rc; echo "lock busy, retry in 30 s"; sleep 30; done; }
run .venv/bin/python -I -B $S/check_responses.py $S/track_heuristics.py > $S/check_responses.txt 2>&1 || exit 1
run .venv/bin/python -I -B $S/track_heuristics.py 40 $S/records-heuristics.json
