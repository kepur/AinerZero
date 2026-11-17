#!/bin/bash
# 探索批次 1：medium 档，3 个种子 × 2 个世界，顺序跑（共享 MLX 锁）
cd "$(dirname "$0")/../../.."
for w in m2 m1; do for s in 0 1 2; do
  .venv/bin/python -m ainerzero.v9.mini.run --preset medium --world $w --seed $s --out reports/V9-MINI/explore/batch1/$w-s$s > /dev/null 2>&1
  echo "$w s$s exit=$?"
done; done
