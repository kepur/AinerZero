#!/bin/zsh
# P253 review, item 3: reviewer's own mutations (none of them is among the author's M1-M10).
# Isolated copy prepared beforehand: git archive HEAD src tests pyproject.toml (+ examples,
# reports/V9-S5-PHASE1 for whole-tree collection), then the P253 new/changed files copied in.
# Usage (under the shared MLX lock, the native test imports MLX): mutate_review.sh <copy dir>
set -u
WORK=$1
ROOT=/Users/mac/AinerWorkFlow/AinerZero
PY=$ROOT/.venv/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=$WORK/src
export REVIEW_COPY=$WORK
cd $WORK
SRC=src/ainerzero/v9/experiments/s6/sandbox.py
echo "copy: $WORK"
echo "copy sandbox.py sha256 vs live: $(shasum -a 256 $SRC | cut -d' ' -f1) / $(shasum -a 256 $ROOT/$SRC | cut -d' ' -f1)"
cat > tests/v9/experiments/test_zz_review_origin.py <<'EOF'
import os
from ainerzero.v9.experiments.s6 import sandbox as S
def test_sandbox_is_loaded_from_the_copy():
    assert S.__file__.startswith(os.environ["REVIEW_COPY"]), S.__file__
EOF
cp $SRC $WORK/sandbox.orig
T="tests/v9/experiments/test_zz_review_origin.py tests/v9/experiments/test_s6_sandbox.py tests/v9/experiments/test_s6_sandbox_native.py"
run() { $PY -m pytest -q -rf -p no:cacheprovider --native-mlx $=T 2>&1 | grep -E "^FAILED|passed|failed|error" ; }
echo "== baseline:"; run

mutate() {  # name, old, new
  local name=$1 old=$2 new=$3
  cp $WORK/sandbox.orig $SRC
  $PY - "$SRC" "$old" "$new" <<'EOF'
import sys
p, old, new = sys.argv[1:]
s = open(p).read()
n = s.count(old)
print(f"anchor found {n}x")
assert n == 1, "mutation anchor must occur exactly once"
open(p, "w").write(s.replace(old, new))
EOF
  echo "== $name:"; run
}

mutate "N1 a dunder (__getitem__) hands out any sample through _take, bypassing reveal's check and log" \
  '    def __len__(self) -> int:' \
  '    def __getitem__(self, g):
        return self._take([int(g)])

    def __len__(self) -> int:'
mutate "N2 reveal returns every sample revealed so far, not just these ids" \
  '        out = self._take(ids)              # read first: if this fails, nothing is registered' \
  '        out = self._take(list(self._revealed) + ids)'
mutate "N3 pick_top uses the prototype argsort (unstable, ties not by id)" \
  '    order = np.lexsort((rem, -sr))' \
  '    order = np.argsort(-sr)'
mutate "N4 geo_flags evaluates on the float32 state (no float64 cast)" \
  '        P = np.asarray(e["p"], dtype=np.float64)
        V = np.asarray(e["v"], dtype=np.float64)' \
  '        P = np.asarray(e["p"])
        V = np.asarray(e["v"])'
mutate "N5 states() returns read-only views of the internal arrays, not copies" \
  '        row = {"id": ids, **{k: np.array(v, copy=True) for k, v in e.items()}}' \
  '        row = {"id": ids, **{k: v.view() for k, v in e.items()}}'
mutate "N6 a failed reveal (repeat) still marks its new ids as revealed in the lookup set" \
  '        again = sorted(set(out) & self._revealed_set)
        if again:' \
  '        again = sorted(set(out) & self._revealed_set)
        self._revealed_set.update(out)
        if again:'
mutate "N7 revealed_pool smuggles in the last unrevealed sample once anything was revealed" \
  '        return self._take(list(self._revealed))' \
  '        extra = [g for g in [len(self) - 1] if self._revealed and g not in self._revealed_set]
        return self._take(list(self._revealed) + extra)'
mutate "N7b revealed_pool smuggles in the smallest unrevealed sample once anything was revealed" \
  '        return self._take(list(self._revealed))' \
  '        extra = [g for g in range(len(self)) if g not in self._revealed_set][:1] if self._revealed else []
        return self._take(list(self._revealed) + extra)'
mutate "N9 the late fix reverted: reveal registers ids and log before reading labels" \
  '        out = self._take(ids)              # read first: if this fails, nothing is registered
        self._revealed.extend(ids)
        self._revealed_set.update(ids)
        self._log.append({"call": len(self._log), "ids": list(ids)})
        return out' \
  '        self._revealed.extend(ids)
        self._revealed_set.update(ids)
        self._log.append({"call": len(self._log), "ids": list(ids)})
        return self._take(ids)'
mutate "N8 revealed_pool lists samples in id order instead of reveal order" \
  '        return self._take(list(self._revealed))' \
  '        return self._take(sorted(self._revealed))'

cp $WORK/sandbox.orig $SRC
echo "== restored:"; run
echo "copy sandbox.py sha256 after restore: $(shasum -a 256 $SRC | cut -d' ' -f1)"
