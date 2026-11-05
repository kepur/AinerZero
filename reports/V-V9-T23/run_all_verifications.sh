#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=== [1/2] Running Independent Non-Author CPU Audit ==="
"${REPO_ROOT}/.venv/bin/python" "${SCRIPT_DIR}/independent_audit.py"

echo ""
echo "=== [2/2] Running 4-Gate Isolated Source Mutations (3-Way Control) ==="
"${REPO_ROOT}/.venv/bin/python" "${SCRIPT_DIR}/run_isolated_mutations.py"

echo ""
echo "=== All T24 CPU Verifications Successfully Passed ==="
