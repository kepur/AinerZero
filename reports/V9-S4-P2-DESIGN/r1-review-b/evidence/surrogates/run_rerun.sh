#!/bin/sh
# P215 复核者 b：在共享锁下复跑前一持有者 track_heuristics.py（原样复制，SHA 见 inputs-from-previous-holder.sha256）的前 3 个主世界，再比对。
cd "$(dirname "$0")/../../../../.." || exit 1
B=reports/V9-S4-P2-DESIGN/r1-review-b/evidence/surrogates
H=reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py
L=artifacts/locks/m0-worker.lock
run() { while :; do .venv/bin/python $H $L "$@"; rc=$?; [ $rc -ne 75 ] && return $rc; echo "lock busy, retry in 30 s"; sleep 30; done; }
run .venv/bin/python -I -B $B/track_heuristics.py 3 $B/rerun-3-worlds.json || exit 1
.venv/bin/python -I -B $B/compare_rerun.py reports/V9-S4-P2-DESIGN/r1-review/evidence/surrogates/records-heuristics.json $B/rerun-3-worlds.json
