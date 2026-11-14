#!/bin/bash
set -euo pipefail

WORKSPACE=/tmp/s6_epinet_mutation_workspace
EVIDENCE_DIR=/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN/epinet-module/evidence
PYTHON=/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python
SRC_FILE=$WORKSPACE/src/ainerzero/v9/experiments/s6/epinet_mlx.py
BACKUP_FILE=$WORKSPACE/src/ainerzero/v9/experiments/s6/epinet_mlx.py.orig

cp "$SRC_FILE" "$BACKUP_FILE"

cd "$WORKSPACE"
export PYTHONPATH="$WORKSPACE/src"

echo "=== Running Baseline ==="
set +e
$PYTHON -m pytest -q --native-mlx tests/v9/experiments/test_s6_epinet_mlx.py > "$EVIDENCE_DIR/baseline.log" 2>&1
RC_BASE=$?
set -e
echo "Baseline exit code: $RC_BASE"
cat "$EVIDENCE_DIR/baseline.log"

echo "=== Running Mutation 1: 去掉 stop_gradient(hid) ==="
sed -i '' 's/hs = mx.stop_gradient(hid)/hs = hid/g' "$SRC_FILE"
set +e
$PYTHON -m pytest -q --native-mlx tests/v9/experiments/test_s6_epinet_mlx.py > "$EVIDENCE_DIR/mutation1.log" 2>&1
RC_M1=$?
set -e
echo "Mutation 1 exit code: $RC_M1"
cat "$EVIDENCE_DIR/mutation1.log"
cp "$BACKUP_FILE" "$SRC_FILE"

echo "=== Running Mutation 2: 去掉 self.prior.freeze() ==="
sed -i '' 's/self.prior.freeze()/# self.prior.freeze()/g' "$SRC_FILE"
set +e
$PYTHON -m pytest -q --native-mlx tests/v9/experiments/test_s6_epinet_mlx.py > "$EVIDENCE_DIR/mutation2.log" 2>&1
RC_M2=$?
set -e
echo "Mutation 2 exit code: $RC_M2"
cat "$EVIDENCE_DIR/mutation2.log"
cp "$BACKUP_FILE" "$SRC_FILE"

echo "=== Running Mutation 3: spread 改为不固定种子 ==="
sed -i '' 's/rng = np.random.default_rng(index_seed + k)/rng = np.random.default_rng()/g' "$SRC_FILE"
set +e
$PYTHON -m pytest -q --native-mlx tests/v9/experiments/test_s6_epinet_mlx.py > "$EVIDENCE_DIR/mutation3.log" 2>&1
RC_M3=$?
set -e
echo "Mutation 3 exit code: $RC_M3"
cat "$EVIDENCE_DIR/mutation3.log"
cp "$BACKUP_FILE" "$SRC_FILE"

echo "All mutations executed successfully."
