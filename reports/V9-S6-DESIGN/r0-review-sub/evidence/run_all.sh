#!/bin/bash
# S6 r0 review runs. Each job takes the shared MLX lock on its own (exit 75 = busy: wait and retry),
# so other sessions can interleave between jobs. Outputs only under r0-review-sub/evidence/.
cd /Users/mac/AinerWorkFlow/AinerZero
E=reports/V9-S6-DESIGN/r0-review-sub/evidence
LOCK=".venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock"

# job 1 (item 2): zero-knowledge proxy rules, round C's world
until $LOCK .venv/bin/python $E/proxy_rules.py 3000 4 2500 $E/proxy-s6x.json s6x-cand s6x-test maxspeed,mindist > $E/run-proxy-s6x.log 2>&1; [ $? -ne 75 ]; do sleep 60; done
echo "job1 exit done" >> $E/run-proxy-s6x.log

# job 2 (item 4): explore_s6c.py itself, random arm, one round, round C's world
until $LOCK .venv/bin/python reports/V9-S6-DESIGN/tier1-explore/explore_s6c.py 3000 1 2500 $E/rerun-s6c-random-r0.json s6x-cand s6x-test random > $E/rerun-s6c-random-r0.log 2>&1; [ $? -ne 75 ]; do sleep 60; done

# job 3 (items 3, 4): round-C arms again with per-world sums (4 rounds), round C's world
until $LOCK .venv/bin/python $E/proxy_rules.py 3000 4 2500 $E/perworld-s6x.json s6x-cand s6x-test random,disagree,truthcur > $E/run-perworld-s6x.log 2>&1; [ $? -ne 75 ]; do sleep 60; done
echo "all jobs done"
