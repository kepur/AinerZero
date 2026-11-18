#!/bin/zsh
# 探索（不算证据）：拓扑组与旧潜空间组、地图组同表，m1/m2 各 3 个种子，留出图为探索段那套（7_900_000 起 30 张）。
cd /Users/mac/AinerWorkFlow/AinerZero
ARMS=random,latent_euclid,latent_learned,graph_memory,gru_belief,latent_topo,map_analytic,map_hybrid,oracle
for w in m1 m2; do for s in 0 1 2; do
  .venv/bin/python -m ainerzero.v9.mini.run --preset medium --world $w --seed $s --arms $ARMS \
    --out reports/V9-MINI/explore/topo-batch/$w-s$s > /dev/null 2>&1
  echo "$(date -u +%FT%TZ) $w s$s exit=$?" >> reports/V9-MINI/explore/topo-batch/ledger.txt
done; done
echo "全部完成" >> reports/V9-MINI/explore/topo-batch/ledger.txt
