#!/usr/bin/env bash
set -euo pipefail

REPO="/Users/mac/AinerWorkFlow/AinerZero"
cd "$REPO"

LOCK="artifacts/locks/m0-worker.lock"
HOLD="reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py"
MUTATE="reports/V9-S4-PHASE2/boundary-tests/evidence/mutate_boundary.py"
EVID="reports/V9-S4-PHASE2/boundary-tests/evidence"

echo "=== 1. Gated Mutants in isolated copies (locked) ==="
WORK_GATED=$(mktemp -d "${TMPDIR:-/tmp}/p219_gated_XXXXXX")
.venv/bin/python "$HOLD" "$LOCK" .venv/bin/python "$MUTATE" "$WORK_GATED" clean_gated X09_geo_gate_tau_le_dt | tee "$EVID/mutants-gated.txt"
rm -rf "$WORK_GATED"

echo "=== 2. Runner Reserve Mutants in isolated copies (locked) ==="
WORK_RUN=$(mktemp -d "${TMPDIR:-/tmp}/p219_run_XXXXXX")
.venv/bin/python "$HOLD" "$LOCK" .venv/bin/python "$MUTATE" "$WORK_RUN" clean_runner_reserve ru_reserve_tenth | tee "$EVID/mutants-runner.txt"
rm -rf "$WORK_RUN"

echo "=== 3. Live test re-runs (locked) ==="
.venv/bin/python "$HOLD" "$LOCK" .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s4_gated.py | tee "$EVID/tests-live-gated.txt"
.venv/bin/python "$HOLD" "$LOCK" .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s4p2_runner_native.py | tee "$EVID/tests-live-runner.txt"

echo "=== 4. Git diff and artifacts check ==="
git diff tests/ > "$EVID/git-diff.patch"

find artifacts/v9/s4/phase2 -type f | sort > "$EVID/artifacts-check.txt"

echo "ALL CHECKS COMPLETED!"
