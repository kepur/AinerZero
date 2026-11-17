#!/bin/bash
# 探索批次 2（M3）：m2 世界，3 个种子，只跑地图类臂；任务集合与批次 1 相同
cd "$(dirname "$0")/../../.."
for s in 0 1 2; do
  .venv/bin/python -m ainerzero.v9.mini.run --preset medium --world m2 --seed $s \
    --arms map_analytic,map_memory,map_hybrid,map_hybrid_self,oracle \
    --out reports/V9-MINI/explore/batch2-m3/m2-s$s > /dev/null 2>&1
  echo "m2 s$s exit=$?"
done
