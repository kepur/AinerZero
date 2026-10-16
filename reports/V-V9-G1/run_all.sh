#!/bin/bash
# G2 复核：一键重跑全部证据（约 10 分钟，纯 CPU）。
# 期望退出码：反例套件 1（有发现 F1/F2/F4）、解析界 0、最小复现 0、冻结核对 0、
#             pytest 0、原始参考脚本 1（F3 登记门）、补丁副本重放 0。
# 只读被验文件；所有输出写入 reports/V-V9-G1/。
set -u
cd /Users/mac/AinerWorkFlow/AinerZero || exit 2
export PYTHONDONTWRITEBYTECODE=1
PY=.venv-ainerzero/bin/python
V=reports/V-V9-G1
mkdir -p "$V/evidence"

echo "== 1/7 反例套件（9 例 + poison 对照） =="
$PY -B "$V/independent_counterexamples.py" --json-out "$V/evidence/counterexamples-summary.json" \
  > "$V/evidence/counterexamples.log" 2>&1
echo "   exit=$?（期望 1：F1/F2/F4）"

echo "== 2/7 解析界（自写推导 + 可达性 + G1 数字复算） =="
$PY -B "$V/independent_bounds.py" --json-out "$V/evidence/bounds-summary.json" \
  > "$V/evidence/bounds.log" 2>&1
echo "   exit=$?（期望 0）"

echo "== 3/7 发现最小复现 =="
$PY -B "$V/findings_minimal_repro.py" > "$V/evidence/findings-minimal-repro.log" 2>&1
echo "   exit=$?（期望 0 = 发现复现成功）"

echo "== 4/7 冻结核对 =="
$PY -B "$V/freeze_check.py" > "$V/evidence/freeze-check.log" 2>&1
echo "   exit=$?（期望 0）"

echo "== 5/7 独立重跑 G1 测试 =="
$PY -m pytest tests/v9/geometry -q -p no:cacheprovider \
  --junitxml="$V/evidence/g1-tests-replay.xml" > "$V/evidence/g1-tests-replay.log" 2>&1
echo "   exit=$?（期望 0，49 passed）"

echo "== 6/7 原始参考脚本（只读安全：写文件前先过源码门） =="
$PY -B reports/V9-G1/r1-codex-20261016/run_reference.py > "$V/evidence/original-replay-gate-failure.log" 2>&1
echo "   exit=$?（期望 1 = F3 登记文档 stale）"

echo "== 7/7 补丁副本重放 + 与报告 JSON 对比 =="
# 不删除任何历史证据：每次重放写到新的时间戳目录（replay-template/ 是副本模板）。
RUN="$V/replay-$(date +%Y%m%dT%H%M%S)"
mkdir -p "$RUN"
cp "$V/replay-template/run_reference.py" "$V/replay-template/cpu_registration.json" "$RUN/"
$PY -B "$RUN/run_reference.py" > "$V/evidence/replay-$(basename "$RUN").log" 2>&1
echo "   exit=$?（期望 0）；新证据目录 $RUN"
$PY -c "
import json,sys
a=json.load(open('reports/V9-G1/r1-codex-20261016/reference-results-r1.json'))
b=json.load(open('$RUN/reference-results-r1.json'))
def cmp(x,y,p=''):
    d=[]
    if isinstance(x,dict):
        d+=[f'{p}: keys {set(x)^set(y)}'] if set(x)!=set(y) else []
        for k in set(x)&set(y): d+=cmp(x[k],y[k],p+'/'+str(k))
    elif isinstance(x,list):
        d+=[f'{p}: len'] if len(x)!=len(y) else []
        for i,(xi,yi) in enumerate(zip(x,y)): d+=cmp(xi,yi,p+f'[{i}]')
    elif x!=y: d.append(f'{p}: {x!r} != {y!r}')
    return d
d=cmp(a,b); print('report JSON vs replay JSON field diffs =', len(d)); [print(' ',x) for x in d[:10]]
" > "$V/evidence/replay-vs-g1-json-diff.txt" 2>&1
cat "$V/evidence/replay-vs-g1-json-diff.txt"

echo "== 重建 metrics.json =="
$PY -B "$V/build_metrics.py"
echo "完成：逐条退出码语义见 $V/report.md §3/§9。"
