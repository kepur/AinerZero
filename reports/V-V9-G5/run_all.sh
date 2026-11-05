#!/usr/bin/env bash
# V9.G6 独立复核 G5 一键完整验证脚本（reports/V-V9-G5/run_all.sh）。
# 纯 CPU，只读复核；只写 reports/V-V9-G5/ 与 /tmp 沙盒；不修改任何源码与历史证据。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv-ainerzero/bin/python"
HERE="$ROOT/reports/V-V9-G5"
EVIDENCE="$HERE/evidence"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$EVIDENCE"

echo "=== 1/8 身份与哈希链冻结复核 ==="
"$PY" -B "$HERE/freeze_and_provenance.py" > "$EVIDENCE/freeze_check.log" 2>&1
echo "freeze_and_provenance PASS"

echo "=== 2/8 r1 49 项数学核心回归测试 ==="
"$PY" -m pytest tests/v9/geometry/test_geometry.py -q -p no:cacheprovider \
  --junitxml="$EVIDENCE/pytest-r1.xml" 2>&1 | tee "$EVIDENCE/pytest-r1.log"

echo "=== 3/8 r2 43 项小修与回归测试 ==="
"$PY" -m pytest tests/v9/geometry/test_geometry_r2.py -q -p no:cacheprovider \
  --junitxml="$EVIDENCE/pytest-r2.xml" 2>&1 | tee "$EVIDENCE/pytest-r2.log"

echo "=== 4/8 G2 原复现转绿核对 ==="
"$PY" -B "$ROOT/reports/V9-G1/r2/g2_minimal_repro_r2.py" \
  --json-out "$EVIDENCE/g2_minimal_repro.json" 2>&1 | tee "$EVIDENCE/g2_minimal_repro.log"

echo "=== 5/8 r2 消费门重放与 r1 登记 0 差异核实 ==="
"$PY" -B "$ROOT/reports/V9-G1/r2/run_reference_r2.py" > "$EVIDENCE/replay_reference.log" 2>&1
echo "reference replay PASS"

echo "=== 6/8 7 个独立不利反例套件 ==="
"$PY" -B "$HERE/independent_verification.py" \
  --json-out "$EVIDENCE/counterexamples.json" 2>&1 | tee "$EVIDENCE/counterexamples.log"

echo "=== 7/8 故意改坏必须变红对照套件（源码 6 项） ==="
"$PY" -B "$HERE/mutations_verification.py" 2>&1 | tee "$EVIDENCE/mutations.log"

echo "=== 8/8 聚合指标与证据清单 ==="
"$PY" -B "$HERE/build_metrics.py"
(cd "$HERE" && find . -type f ! -name "SHA256SUMS.txt" ! -name ".*" -exec shasum -a 256 {} + | sort -k 2) > "$HERE/SHA256SUMS.txt"

echo "================================================="
echo "V9.G6 独立复核全套验证顺利通过！"
echo "产物目录: $HERE"
echo "================================================="
