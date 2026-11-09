#!/bin/sh
# S2 phase-1 registered training under r4: the 8 cells not yet completed (arm_a seed 42 was
# completed under r3 / P193 and is kept; the CLI refuses an already-completed cell).
# Seed-major order; CLI defaults only; stops at the first failing cell (no retry, no parameter changes).
cd /Users/mac/AinerWorkFlow/AinerZero || exit 2
OUT=reports/V9-S2-TRAIN-r4
for cell in arm_b:42 arm_c:42 arm_a:43 arm_b:43 arm_c:43 arm_a:44 arm_b:44 arm_c:44; do
  arm=${cell%%:*}; seed=${cell##*:}
  tag="${arm}_s${seed}"
  date -u "+%FT%TZ" > "$OUT/${tag}.started_at"
  .venv/bin/python -m ainerzero s2-phase1 --mode train --arm "$arm" --seed "$seed" > "$OUT/${tag}.stdout.json" 2> "$OUT/${tag}.stderr.log"
  rc=$?
  echo "$rc" > "$OUT/${tag}.exit_code"
  date -u "+%FT%TZ" > "$OUT/${tag}.finished_at"
  if [ "$rc" -ne 0 ]; then
    echo "cell $tag failed rc=$rc; stopping"
    exit "$rc"
  fi
done
echo "all 8 remaining cells completed"
