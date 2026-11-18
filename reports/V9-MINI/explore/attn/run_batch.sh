#!/bin/zsh
# 探索（不算证据）：注意力记忆组 m1/m2 各 3 个种子，留出图为探索段那套（7_900_000 起 30 张）。
# 只训练注意力组；其他组的回合取自 explore/topo-batch（同样的种子、同样的留出图，任务逐个相同）。
cd /Users/mac/AinerWorkFlow/AinerZero
for w in m1 m2; do for s in 0 1 2; do
  [[ -f reports/V9-MINI/explore/attn/batch/$w-s$s/result.json ]] && continue
  .venv/bin/python reports/V9-MINI/explore/attn/attn_explore.py --world $w --seed $s \
    --out reports/V9-MINI/explore/attn/batch/$w-s$s > /dev/null 2>&1
  echo "$(date -u +%FT%TZ) $w s$s exit=$?" >> reports/V9-MINI/explore/attn/batch/ledger.txt
done; done
echo "全部完成" >> reports/V9-MINI/explore/attn/batch/ledger.txt
