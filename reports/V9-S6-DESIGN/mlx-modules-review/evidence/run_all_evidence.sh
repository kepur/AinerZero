#!/usr/bin/env bash
set -e

REPO="/Users/mac/AinerWorkFlow/AinerZero"
cd "$REPO"

LOCK="artifacts/locks/m0-worker.lock"
HARNESS="reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py"
EV_DIR="reports/V9-S6-DESIGN/mlx-modules-review/evidence"

run_locked() {
    while true; do
        set +e
        .venv/bin/python "$HARNESS" "$LOCK" "$@"
        rc=$?
        set -e
        if [ $rc -eq 75 ]; then
            echo "[$(date +%T)] Lock busy ($LOCK held by another process), waiting 30s..."
            sleep 30
        else
            return $rc
        fi
    done
}

echo "=== 1. Evaluation Arithmetic Parity ==="
run_locked .venv/bin/python "$EV_DIR/probe_evaluation_arithmetic.py" > "$EV_DIR/probe_evaluation_arithmetic.out" 2>&1
cat "$EV_DIR/probe_evaluation_arithmetic.out"

echo "=== 2. Tamper Detection ==="
run_locked .venv/bin/python "$EV_DIR/test_tamper_detection.py" > "$EV_DIR/test_tamper_detection.out" 2>&1
cat "$EV_DIR/test_tamper_detection.out"

echo "=== 3. Resumption & Ledger ==="
run_locked .venv/bin/python "$EV_DIR/test_resumption_and_ledger.py" > "$EV_DIR/test_resumption_and_ledger.out" 2>&1
cat "$EV_DIR/test_resumption_and_ledger.out"

echo "=== 4. Native Tests Baseline ==="
run_locked .venv/bin/pytest --native-mlx \
    tests/v9/experiments/test_s6_cells_native.py \
    tests/v9/experiments/test_s6_cells_static.py \
    tests/v9/experiments/test_s6_epinet_mlx.py \
    tests/v9/experiments/test_s6_sandbox_native.py \
    tests/v9/experiments/test_s6p1_runner_native.py \
    -v > "$EV_DIR/native_tests_baseline.out" 2>&1 || true
cat "$EV_DIR/native_tests_baseline.out"

echo "=== 5. Mutation Testing ==="
run_locked .venv/bin/python "$EV_DIR/test_mutations.py" > "$EV_DIR/test_mutations.out" 2>&1
cat "$EV_DIR/test_mutations.out"

echo "=== ALL EVIDENCE RUNS COMPLETE ==="
