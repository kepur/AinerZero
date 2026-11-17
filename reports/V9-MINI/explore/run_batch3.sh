#!/bin/bash
# 探索批次 3：A27 修复后（c92c0abd：强连通判据、并图前整块碎片验证），m2 与 m1 各 3 个种子，全部臂。
# 地图变了，批次 1/2 的数字不再对应当前代码；这一批用来重新定 M4 预登记的门槛。
cd "$(dirname "$0")/../../.."
for w in m2 m1; do
  for s in 0 1 2; do
    .venv/bin/python -m ainerzero.v9.mini.run --preset medium --world $w --seed $s \
      --out reports/V9-MINI/explore/batch3/$w-s$s > /dev/null 2>&1
    echo "$w s$s exit=$?"
  done
done
