#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=== Running Sabotage Control Verification for V9-T23 ==="
"${REPO_ROOT}/.venv/bin/python" "${SCRIPT_DIR}/verify_sabotage.py"
echo "=== Sabotage Control Completed Successfully ==="
