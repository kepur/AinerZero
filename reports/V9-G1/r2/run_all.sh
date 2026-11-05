#!/usr/bin/env bash
# G1 r2 证据一键重跑（F1/F2 修复回归 + F3 重登记/消费门/参考重放 + 故意改坏对照）。
# 只写 reports/V9-G1/r2/ 与 /tmp 沙盒；不改 r1 证据、不训练、不下载、不安装。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv-ainerzero/bin/python"
R2="$ROOT/reports/V9-G1/r2"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$R2/evidence"

echo "== 1/11 F3 重登记（旧→新哈希、逐节差异） =="
"$PY" -B "$R2/build_r2_registration.py" 2>&1 | tee "$R2/evidence/build-registration.log"

echo "== 2/11 F3 消费门（文档不豁免、代码仍强制） =="
"$PY" -B "$R2/verify_registration_r2.py" --json-out "$R2/evidence/registration-verify.json" 2>&1 \
  | tee "$R2/evidence/registration-verify.log"

echo "== 3/11 r1 49 项回归测试 =="
"$PY" -m pytest tests/v9/geometry/test_geometry.py -q -p no:cacheprovider \
  --junitxml="$R2/evidence/pytest-r1.xml" 2>&1 | tee "$R2/evidence/pytest-r1.log"

echo "== 4/11 r2 新增正反例/G2 最小复现测试 =="
"$PY" -m pytest tests/v9/geometry/test_geometry_r2.py -q -p no:cacheprovider \
  --junitxml="$R2/evidence/pytest-r2.xml" 2>&1 | tee "$R2/evidence/pytest-r2.log"

echo "== 5/11 G2 最小复现（F1/F2）转绿核对 =="
"$PY" -B "$R2/g2_minimal_repro_r2.py" --json-out "$R2/evidence/g2-minimal-repro-r2.json" 2>&1 \
  | tee "$R2/evidence/g2-minimal-repro-r2.log"

echo "== 6/11 r2 消费门重放 G1 参考（期望 references 与 r1 0 差异） =="
"$PY" -B "$R2/run_reference_r2.py" 2>&1 | tee "$R2/evidence/replay-r2.log"

echo "== 7/11 r1 原件消费门复跑（stale 文档哈希 → 预期 exit 1，失败证据保留） =="
set +e
"$PY" -B reports/V9-G1/r1-codex-20261016/run_reference.py \
  > "$R2/evidence/r1-original-gate-still-fails.log" 2>&1
r1_original_gate_exit=$?
set -e
echo "r1 original consumer gate exit=${r1_original_gate_exit}（预期非 0）" \
  | tee -a "$R2/evidence/r1-original-gate-still-fails.log"
if [ "$r1_original_gate_exit" -eq 0 ]; then
  echo "r1 原件的消费门意外通过：stale 文档哈希没有被拦截" >&2
  exit 1
fi

echo "== 8/11 故意改坏必须变红（源码 6 + 登记门 2） =="
"$PY" -B "$R2/run_mutations_r2.py" 2>&1 | tee "$R2/evidence/mutations-r2.log"

echo "== 9/11 ruff 静态检查（changed src + r2 tests） =="
"$ROOT/.venv-ainerzero/bin/ruff" check --no-cache src/ainerzero/v9/geometry \
  tests/v9/geometry/test_geometry_r2.py 2>&1 | tee "$R2/evidence/ruff.log"

echo "== 10/11 聚合 metrics.json（不手抄数字） =="
"$PY" -B "$R2/build_metrics.py" 2>&1 | tee "$R2/evidence/build-metrics.log"

echo "== 11/11 r2 证据 SHA256SUMS =="
"$PY" -B "$R2/build_shasums.py"

echo "r2 证据全部完成：$R2/（report.md 另行撰写，写完再跑一次 build_shasums.py）"
