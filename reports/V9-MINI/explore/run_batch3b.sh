#!/bin/bash
# 批次 3 补跑：第一次有 4 个运行撞上锁忙（run.py 拿不到 m0-worker 锁就以 75 退出，当时 A28 复核在用锁）。
# 锁忙时等 30 秒重试，最多 120 次。
cd "$(dirname "$0")/../../.."
for ws in "m2 2" "m1 0" "m1 1" "m1 2"; do
  set -- $ws
  for try in $(seq 1 120); do
    .venv/bin/python -m ainerzero.v9.mini.run --preset medium --world $1 --seed $2 \
      --out reports/V9-MINI/explore/batch3/$1-s$2 > /dev/null 2>&1
    rc=$?
    [ $rc -ne 75 ] && break
    sleep 30
  done
  echo "$1 s$2 exit=$rc tries=$try"
done
