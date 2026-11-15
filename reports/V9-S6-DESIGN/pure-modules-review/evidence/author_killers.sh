#!/bin/zsh
# P256 review, item 5: which tests kill the author's A1, A4, A7, A11 (the author's log prints only counts).
# Same anchors as mutate_pure.sh, applied in my isolated copy (made by mutate_review.sh), then restored.
# Usage: author_killers.sh COPY_DIR
set -u
ROOT=/Users/mac/AinerWorkFlow/AinerZero
PY=$ROOT/.venv/bin/python
WORK=$1
cd $WORK
export PYTHONPATH=$WORK/src PYTHONDONTWRITEBYTECODE=1
AN=src/ainerzero/v9/experiments/s6/analysis.py
cmp -s $AN $ROOT/$AN && echo "copy analysis.py == working tree"
cp $AN $AN.orig2
T="tests/v9/experiments/test_s6_analysis.py tests/v9/experiments/test_zz_review_origin.py"
one() {
  cp $AN.orig2 $AN
  $PY - $AN "$2" "$3" <<'PYEOF'
import sys
p, old, new = sys.argv[1:]
s = open(p).read()
assert s.count(old) == 1
open(p, "w").write(s.replace(old, new, 1))
PYEOF
  echo "== $1"
  $PY -m pytest -q -p no:cacheprovider -rf $=T 2>&1 | grep -E "^FAILED|passed|failed"
}
one "A1 Bonferroni with m = 6" '    p_bonf, p_95 = 1 - ALPHA / (2 * M), 1 - ALPHA / 2' '    p_bonf, p_95 = 1 - ALPHA / (2 * 6), 1 - ALPHA / 2'
one "A1' m = 6 in the bound only (levels dict keeps M)" '        lo, hi, parts = interval(spec, x, tk, boot[g], p_bonf)' '        lo, hi, parts = interval(spec, x, tk, boot[g], 1 - ALPHA / (2 * 6))'
one "A4 worlds redrawn for arm R (unpaired)" '            S = np.einsum("bw,knwc->bknc", Mw, np.asarray(d["sums"][arm], float))' \
  '            S = np.einsum("bw,knwc->bknc", np.roll(Mw, 1, 0) if arm == "R" else Mw, np.asarray(d["sums"][arm], float))'
one "A7 t with K degrees of freedom" '    q = t_ppf(p, K - 1) if K > 1 else norm_ppf(p)' '    q = t_ppf(p, K) if K > 1 else norm_ppf(p)'
one "A11 world draws not shared: extrap drawn first" '        for t in TEST_SETS:
            out[t][b] = rng.integers' '        for t in reversed(TEST_SETS):
            out[t][b] = rng.integers'
cp $AN.orig2 $AN && rm $AN.orig2
cmp -s $AN $ROOT/$AN && echo "restored == working tree"
