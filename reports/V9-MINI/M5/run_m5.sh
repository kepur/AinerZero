#!/bin/bash
# V9-mini M5 确认性运行（预登记 reports/V9-MINI/M5/M5-PREREG.md，冻结记录 reports/V9-MINI/M5/FREEZE.json）。
# 守卫：
#   1. 冻结记录里的代码哈希（run._code_sha）和预登记文件的 sha256 必须与当前一致，MLX 必须是冻结记录里的版本，否则不跑；
#   2. 输出目录已有 result.json 就不跑（不覆盖）；
#   3. Preview 在运行就不跑（会触发 GPU 复位）；
#   4. 单次运行上限 3600 秒，超时就杀掉并停止整批；累计上限 36000 秒（10 小时），超过就停止；
#   5. m0-worker 锁忙（run.py 退出码 75）就等 30 秒重试，等待时间不计入预算。
# 用法：caffeinate -i bash reports/V9-MINI/M5/run_m5.sh
set -u
cd "$(dirname "$0")/../../.."
PY=${M5_PY:-.venv/bin/python}
CAP_RUN=${M5_CAP_RUN:-3600}      # 只供守卫测试覆盖
CAP_TOTAL=${M5_CAP_TOTAL:-36000}
LEDGER=reports/V9-MINI/M5/ledger.txt
ARMS=random,latent_euclid,latent_learned,graph_memory,gru_belief,latent_topo,topo_oracle_ctrl,latent_attn,map_analytic,map_hybrid,map_hybrid_self,oracle
$PY - <<'PYEOF' || exit 2
import hashlib, json, sys
from pathlib import Path
from ainerzero.v9.mini import run
f = json.loads(Path("reports/V9-MINI/M5/FREEZE.json").read_text())
code = run._code_sha()
pre = hashlib.sha256(Path("reports/V9-MINI/M5/M5-PREREG.md").read_bytes()).hexdigest()
import mlx.core as mx
if code != f["code_sha256"] or pre != f["prereg_sha256"] or mx.__version__ != f["mlx"]:
    print(f"冻结不一致：代码 {code[:12]} 对 {f['code_sha256'][:12]}，预登记 {pre[:12]} 对 {f['prereg_sha256'][:12]}，MLX {mx.__version__} 对 {f['mlx']}")
    sys.exit(1)
print("冻结一致", code[:12], pre[:12], mx.__version__)
PYEOF
if pgrep -x Preview > /dev/null; then echo "Preview 在运行，先关掉"; exit 3; fi
total=0
for w in m2 m1; do
  for s in 0 1 2 3 4; do
    out=reports/V9-MINI/M5/$w-s$s
    if [ -f $out/result.json ]; then echo "$w s$s 已有结果，跳过（不覆盖）" | tee -a $LEDGER; continue; fi
    if [ $total -gt $CAP_TOTAL ]; then echo "累计 ${total}s 超过 ${CAP_TOTAL}s 上限，停止" | tee -a $LEDGER; exit 4; fi
    while true; do
      start=$(date +%s)
      $PY -m ainerzero.v9.mini.run --preset medium --world $w --seed $s --eval-seed0 $((8100000 + 1000 * s)) \
        --eval-layouts 80 --arms $ARMS --out $out > /dev/null 2>&1 &
      pid=$!
      killed=0
      while kill -0 $pid 2>/dev/null; do
        if [ $(( $(date +%s) - start )) -gt $CAP_RUN ]; then kill $pid; killed=1; fi
        sleep 5
      done
      wait $pid; rc=$?
      [ $rc -ne 75 ] && break
      sleep 30
    done
    el=$(( $(date +%s) - start )); total=$(( total + el ))
    echo "$(date -u +%FT%TZ) $w s$s exit=$rc 用时 ${el}s 累计 ${total}s" | tee -a $LEDGER
    if [ $killed -eq 1 ]; then echo "$w s$s 超过单次 ${CAP_RUN}s 上限被停止，整批停止" | tee -a $LEDGER; exit 5; fi
    if [ $rc -ne 0 ]; then echo "$w s$s 失败（exit=$rc），整批停止" | tee -a $LEDGER; exit 6; fi
  done
done
echo "全部完成，累计 ${total}s" | tee -a $LEDGER
