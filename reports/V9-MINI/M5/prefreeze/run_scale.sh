#!/bin/bash
# M5 冻结前检查 2：登记规模（80 张留出图、12 组）实测耗时与完整流程。
# 用探索段没用过的留出图 7_960_000 起；不碰 7_900_000 / 7_950_000 起的探索集，也不碰 8_000_000 / 8_100_000 起的确认集。
cd "$(dirname "$0")/../../../.."
ARMS=random,latent_euclid,latent_learned,graph_memory,gru_belief,latent_topo,topo_oracle_ctrl,latent_attn,map_analytic,map_hybrid,map_hybrid_self,oracle
for w in m2 m1; do
  t0=$(date +%s)
  for try in $(seq 1 120); do
    .venv/bin/python -m ainerzero.v9.mini.run --preset medium --world $w --seed 0 --eval-seed0 7960000 --eval-layouts 80 \
      --arms $ARMS --out reports/V9-MINI/explore/scale80-m5/$w-s0 > /dev/null 2>&1
    rc=$?
    [ $rc -ne 75 ] && break
    sleep 30
  done
  echo "$(date -u +%FT%TZ) $w exit=$rc tries=$try sec=$(( $(date +%s) - t0 ))" >> reports/V9-MINI/explore/scale80-m5/ledger.txt
done
echo "全部完成" >> reports/V9-MINI/explore/scale80-m5/ledger.txt
