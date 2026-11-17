#!/bin/bash
# 冻结前检查：登记规模（每个种子 80 张留出图）实测耗时。用探索段没用过的留出图 7_950_000 起，不碰 8_000_000 起的确认段。
cd "$(dirname "$0")/../../.."
for w in m2 m1; do
  for try in $(seq 1 120); do
    .venv/bin/python -m ainerzero.v9.mini.run --preset medium --world $w --seed 0 --eval-seed0 7950000 --eval-layouts 80 \
      --out reports/V9-MINI/explore/scale80/$w-s0 > /dev/null 2>&1
    rc=$?
    [ $rc -ne 75 ] && break
    sleep 30
  done
  echo "$w exit=$rc tries=$try"
done
