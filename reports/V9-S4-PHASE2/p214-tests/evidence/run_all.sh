#!/usr/bin/env bash
set -euo pipefail

REPO="/Users/mac/AinerWorkFlow/AinerZero"
cd "$REPO"

LOCK="artifacts/locks/m0-worker.lock"
HOLD="reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py"
MUTATE="reports/V9-S4-PHASE2/p214-tests/evidence/mutate_p217.py"

echo "=== 1. CPU Mutants in isolated copies ==="
WORK_CPU=$(mktemp -d "${TMPDIR:-/tmp}/p217_cpu_XXXXXX")
.venv/bin/python "$MUTATE" "$WORK_CPU" clean_analysis X01_GC_uses_95_not_bonferroni X01_GR_uses_95_not_bonferroni X02_GD_D_bonferroni_m1 X03_GX_C_from_main_records X04_seed_average_seed1_only X07_neg_control_uses_95_high
rm -rf "$WORK_CPU"

echo "=== 2. MLX Runner Mutants in isolated copies (locked) ==="
WORK_RUN=$(mktemp -d "${TMPDIR:-/tmp}/p217_run_XXXXXX")
.venv/bin/python "$HOLD" "$LOCK" .venv/bin/python "$MUTATE" "$WORK_RUN" clean_runner M08b_weight_files_checked_after_marker_in_final X06_reserve_check_removed
rm -rf "$WORK_RUN"

echo "=== 3. Live test re-runs ==="
.venv/bin/python "$HOLD" "$LOCK" .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s4_gated.py
.venv/bin/python -m pytest -q -p no:cacheprovider tests/v9/experiments/test_s4_analysis_p2.py
.venv/bin/python "$HOLD" "$LOCK" .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s4p2_runner_native.py

echo "ALL CHECKS PASSED!"
