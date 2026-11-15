#!/bin/zsh
# Everything that imports MLX for the final-version recheck, run back to back under one lock hold.
# Usage: hold_lock.py artifacts/locks/m0-worker.lock /bin/zsh lock_batch.sh <mutation copy dir>
set -u
ROOT=/Users/mac/AinerWorkFlow/AinerZero
E=$ROOT/reports/V9-S6-DESIGN/sandbox-module-review/evidence
PY=$ROOT/.venv/bin/python
export PYTHONDONTWRITEBYTECODE=1
cd $ROOT
echo "sandbox.py sha256 at start: $(shasum -a 256 src/ainerzero/v9/experiments/s6/sandbox.py)"
{ echo '$ .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx -rA tests/v9/experiments/test_s6_sandbox_native.py tests/v9/experiments/test_s6_epinet_mlx.py tests/v9/experiments/test_s6_sandbox.py'
  $PY -m pytest -q -p no:cacheprovider --native-mlx -rA tests/v9/experiments/test_s6_sandbox_native.py tests/v9/experiments/test_s6_epinet_mlx.py tests/v9/experiments/test_s6_sandbox.py 2>&1 | grep -E "PASSED|FAILED|ERROR|passed|failed"; } > $E/e03-native-tests.txt 2>&1
/bin/zsh $E/mutate_review.sh $1 > $E/e08-mutations.txt 2>&1
{ echo "\$ /bin/zsh reports/V9-S6-DESIGN/sandbox-module/mutate.sh   # the author's script, unchanged, on the final files"
  /bin/zsh reports/V9-S6-DESIGN/sandbox-module/mutate.sh; } > $E/e10-author-mutations-rerun.txt 2>&1
$PY $E/equiv_realscale.py > $E/e05-equiv-realscale.txt 2>&1
$PY $E/n7_probe.py > $E/e11-n7-probe.txt 2>&1
echo "sandbox.py sha256 at end: $(shasum -a 256 src/ainerzero/v9/experiments/s6/sandbox.py)"
echo batch-done
