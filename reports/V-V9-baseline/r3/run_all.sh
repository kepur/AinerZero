#!/usr/bin/env bash
# ainerzero.V9.A10 独立复核一键重跑：只读真实 artifacts/A2/A3/A4 产物；
# 只写 reports/V-V9-baseline/r3/ 与 /tmp 案例沙盒。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv-ainerzero/bin/python"
OUT="$ROOT/reports/V-V9-baseline/r3"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$OUT/evidence"

echo "== 1/3 独立复核：C3/policy/T3/RunStore/真实拷贝 + 10 自建案例 + 真实树前后完整性 =="
"$PY" -B "$OUT/review_r3.py" --json-out "$OUT/evidence/review.json" 2>&1 \
  | tee "$OUT/evidence/review.log"

echo "== 2/3 聚合 metrics.json（从 evidence/review.json 生成，不手抄） =="
"$PY" -B "$OUT/build_metrics.py" 2>&1 | tee "$OUT/evidence/build-metrics.log"

echo "== 3/3 SHA256SUMS =="
"$PY" -B "$OUT/build_shasums.py"
echo "V9.A10 复核证据完成：$OUT/（REPORT.md 撰写后需再跑一次 build_shasums.py）"
