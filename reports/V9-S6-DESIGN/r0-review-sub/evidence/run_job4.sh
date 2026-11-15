#!/bin/bash
# job 4 (item 2, robustness): mindist on round D's world (s6x-cand2 / s6x-test2), then the budget timing check.
# (A first attempt from zsh failed before starting anything: zsh did not word-split $LOCK; see run-proxy-s6x2.log history in REPORT.)
cd /Users/mac/AinerWorkFlow/AinerZero
E=reports/V9-S6-DESIGN/r0-review-sub/evidence
LOCK=".venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock"
until $LOCK .venv/bin/python $E/proxy_rules.py 3000 4 2500 $E/proxy-s6x2.json s6x-cand2 s6x-test2 mindist > $E/run-proxy-s6x2.log 2>&1; [ $? -ne 75 ]; do sleep 60; done
until $LOCK .venv/bin/python $E/timing_check.py > $E/timing_check.log 2>&1; [ $? -ne 75 ]; do sleep 60; done
echo "job4 done"
