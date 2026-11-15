#!/bin/zsh
# Mutation check for the S6 sandbox (P253). Isolated copy: git archive HEAD + the new/changed files;
# PYTHONPATH points at the copy's src. Run under the MLX lock (the native test imports MLX).
set -u
ROOT=/Users/mac/AinerWorkFlow/AinerZero
PY=$ROOT/.venv/bin/python
WORK=$(mktemp -d "${TMPDIR:-/tmp}/p253-mut.XXXXXX")
cd $ROOT
git archive HEAD src tests pyproject.toml | tar -x -C $WORK
for f in src/ainerzero/v9/experiments/s6/sandbox.py tests/v9/experiments/test_s6_sandbox.py \
         tests/v9/experiments/test_s6_sandbox_native.py tests/conftest.py; do
  cp $f $WORK/$f
done
cd $WORK
export PYTHONPATH=$WORK/src
echo "copy: $WORK"
$PY -c "import ainerzero.v9.experiments.s6.sandbox as m; print('module from', m.__file__)"
T="tests/v9/experiments/test_s6_sandbox.py tests/v9/experiments/test_s6_sandbox_native.py"
SRC=src/ainerzero/v9/experiments/s6/sandbox.py
cp $SRC $WORK/sandbox.orig
run() { $PY -m pytest -q -p no:cacheprovider --native-mlx $=T 2>&1 | tail -1; }
echo "== baseline: $(run)"

mutate() {  # name, python replacement snippet (old -> new)
  local name=$1 old=$2 new=$3
  cp $WORK/sandbox.orig $SRC
  $PY - "$SRC" "$old" "$new" <<'EOF'
import sys
p, old, new = sys.argv[1:]
s = open(p).read()
n = s.count(old)
print(f"replaced {n}")
assert n >= 1, "mutation anchor not found"
open(p, "w").write(s.replace(old, new))
EOF
  echo "== $name: $(run)"
}

# required by the card
mutate "M1 states() also carries a label field (p1)" \
  'row = {"id": ids, **{k: np.array(v, copy=True) for k, v in e.items()}}' \
  'row = {"id": ids, **{k: np.array(v, copy=True) for k, v in e.items()}, "p1": np.array(self._sealed_labels[n]["p1"], copy=True)}'
mutate "M2 pick_top ties by id descending" \
  'order = np.lexsort((rem, -sr))' \
  'order = np.lexsort((-rem, -sr))'
mutate "M3 reveal does not check repeats" \
  '        again = sorted(set(out) & self._revealed_set)
        if again:' \
  '        again = sorted(set(out) & self._revealed_set)
        if False:'
# extra
mutate "M4 geo_flags drops the overlapping-and-approaching clause" \
  'hit = ((c <= 0) & (b < 0)) | ((a > 0)' \
  'hit = ((a > 0)'
mutate "M5 geo_flags ignores approach (b < 0) in the touch-within-dt clause" \
  '(disc >= 0) & (b < 0) & (tau >= 0)' \
  '(disc >= 0) & (tau >= 0)'
mutate "M6 reveal skips the log" \
  '        self._log.append({"call": len(self._log), "ids": list(ids)})' \
  '        pass'
mutate "M7 a public property leaks the label store" \
  '    def __len__(self) -> int:' \
  '    @property
    def labels(self):
        return self._sealed_labels

    def __len__(self) -> int:'
mutate "M8 picks do not sort remaining (caller order leaks into the draw)" \
  '    srt = np.unique(rem)
    if len(srt) != len(rem):' \
  '    srt = rem
    if len(np.unique(rem)) != len(rem):'
mutate "M9 pick_geo fills from all remaining (may repeat a flagged pick)" \
  'fill = rng.choice(np.setdiff1d(rem, take), k - len(take), replace=False)' \
  'fill = rng.choice(rem, k - len(take), replace=False)'
mutate "M10 reveal returns rows in sorted order, not the given order" \
  '            rows = np.array(groups[n], dtype=np.int64)' \
  '            rows = np.sort(np.array(groups[n], dtype=np.int64))'

cp $WORK/sandbox.orig $SRC
echo "== restored: $(run)"
