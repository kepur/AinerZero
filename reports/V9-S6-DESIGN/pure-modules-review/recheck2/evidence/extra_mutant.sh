#!/bin/zsh
# P256 recheck2: one probe of the new import-time scan. F1 = an alias of W.physics bound as a default argument
# of CandidatePool.__init__ (evaluated at import time, inside a class body) that the constructor uses to
# precompute one-step outcomes into a module-level store (so vars(cp) stays the documented 9 attributes).
# Runs in the copy left by mutate_recheck.sh (restored to the working-tree files first). Usage: extra_mutant.sh COPY_DIR
set -u
ROOT=/Users/mac/AinerWorkFlow/AinerZero
PY=$ROOT/.venv/bin/python
cd $1
export PYTHONPATH=$1/src PYTHONDONTWRITEBYTECODE=1
SB=src/ainerzero/v9/experiments/s6/sandbox.py
cmp -s $SB $ROOT/$SB && echo "copy sandbox.py == working tree"
cp $SB $SB.f1orig
$PY - $SB <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
for old, new in [
    ('STATE_KEYS = ("p", "v", "pil")\n', 'STATE_KEYS = ("p", "v", "pil")\n_SEEN: dict = {}\n'),
    ('                 pool_type: Callable = LabelledPool):', '                 pool_type: Callable = LabelledPool, _p: Callable = W.physics):'),
    ('        self._log: list[dict[str, Any]] = []',
     '        self._log: list[dict[str, Any]] = []\n        _SEEN[id(self)] = {n: [_p(e["p"][i:i + 1], e["v"][i:i + 1], tuple(map(tuple, e["pil"][i]))) for i in range(len(e["p"]))]\n                           for n, e in self._states.items()}'),
]:
    assert s.count(old) == 1, old
    s = s.replace(old, new, 1)
open(p, "w").write(s)
PYEOF
echo "== F1 default-argument alias of W.physics in CandidatePool.__init__, outcomes kept in a module-level dict"
diff $SB.f1orig $SB | sed 's/^/   | /'
$PY -m pytest -q -p no:cacheprovider tests/v9/experiments/test_s6_sandbox.py tests/v9/experiments/test_s6_analysis.py \
  tests/v9/experiments/test_s6_cells_static.py tests/v9/experiments/test_zz_review_origin.py 2>&1 | grep -E "^FAILED|passed|failed"
cp $SB.f1orig $SB && rm $SB.f1orig
cmp -s $SB $ROOT/$SB && echo "restored == working tree"
