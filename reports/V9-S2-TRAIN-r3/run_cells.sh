#!/bin/sh
# S2 phase-1 registered training: 9 cells (arm_a/b/c x seed 42/43/44), seed-major order.
# CLI defaults only; stops at the first failing cell (no retry, no parameter changes).
cd /Users/mac/AinerWorkFlow/AinerZero || exit 2
OUT=reports/V9-S2-TRAIN-r3
for seed in 42 43 44; do
  for arm in arm_a arm_b arm_c; do
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
done
echo "all 9 cells completed"
