#!/bin/zsh
# Mutation check for the pure-NumPy S6 modules (sandbox r2, analysis) and the static selection test.
# Isolated copy: git archive HEAD + the current S6 files; PYTHONPATH points at the copy's src. No MLX.
set -u
ROOT=/Users/mac/AinerWorkFlow/AinerZero
PY=$ROOT/.venv/bin/python
WORK=$(mktemp -d "${TMPDIR:-/tmp}/s6-mut.XXXXXX")
cd $ROOT
git archive HEAD src tests pyproject.toml | tar -x -C $WORK
for f in src/ainerzero/v9/experiments/s6/sandbox.py src/ainerzero/v9/experiments/s6/analysis.py \
         src/ainerzero/v9/experiments/s6/cells.py src/ainerzero/v9/experiments/s4/world.py \
         tests/v9/experiments/test_s6_sandbox.py tests/v9/experiments/test_s6_analysis.py \
         tests/v9/experiments/test_s6_cells_static.py tests/conftest.py; do
  mkdir -p $WORK/$(dirname $f); cp $f $WORK/$f
done
cd $WORK
export PYTHONPATH=$WORK/src
echo "copy: $WORK"
$PY -c "import ainerzero.v9.experiments.s6.sandbox as a, ainerzero.v9.experiments.s6.analysis as b; print('modules from', a.__file__, b.__file__)"
T="tests/v9/experiments/test_s6_sandbox.py tests/v9/experiments/test_s6_analysis.py tests/v9/experiments/test_s6_cells_static.py"
run() { $PY -m pytest -q -p no:cacheprovider $=T 2>&1 | tail -1; }
echo "== baseline: $(run)"
SB=src/ainerzero/v9/experiments/s6/sandbox.py; AN=src/ainerzero/v9/experiments/s6/analysis.py; CE=src/ainerzero/v9/experiments/s6/cells.py
for f in $SB $AN $CE; do cp $f $f.orig; done

mutate() {  # file, name, old, new
  local file=$1 name=$2 old=$3 new=$4
  for f in $SB $AN $CE; do cp $f.orig $f; done
  $PY - "$file" "$old" "$new" <<'EOF'
import sys
p, old, new = sys.argv[1:]
s = open(p).read()
n = s.count(old)
assert n >= 1, f"mutation anchor not found in {p}: {old[:60]!r}"
open(p, "w").write(s.replace(old, new, 1))
EOF
  echo "== $name: $(run)"
}

# sandbox
mutate $SB "S1 states() simulates every candidate" \
  '        out = {}
        for n, e in self._states.items():
            ids = np.arange' \
  '        self._simulate(list(range(len(self._index))))
        out = {}
        for n, e in self._states.items():
            ids = np.arange'
mutate $SB "S2 reveal registers before simulating" \
  '        outcomes = self._simulate(ids)
        self._revealed.extend(ids)' \
  '        self._revealed.extend(ids)
        outcomes = self._simulate(ids)'
mutate $SB "S3 pick_top ties by id descending" 'order = np.lexsort((rem, -sr))' 'order = np.lexsort((-rem, -sr))'
mutate $SB "S4 pick_top uses the prototype argsort" 'order = np.lexsort((rem, -sr))' 'order = np.argsort(-sr)'
mutate $SB "S5 reveal does not check repeats" '        if again:
            raise ValueError(f"ids already revealed' '        if False:
            raise ValueError(f"ids already revealed'
mutate $SB "S6 a dunder hands out any outcome" '    def __len__(self) -> int:' '    def __getitem__(self, g):
        return self._simulate([g])

    def __len__(self) -> int:'
mutate $SB "S7 states() returns read-only views of the internal arrays" \
  'row = {"id": ids, **{k: v.astype(np.float32) for k, v in e.items()}}' \
  'row = {"id": ids, **{k: v.view() for k, v in e.items()}}'
mutate $SB "S8 reveal returns every revealed sample so far" '        return self._assemble(ids)
' '        return self._assemble(list(self._revealed))
'
mutate $SB "S9 picks accept negative ids" '    if srt.size and (srt[0] < 0 or' '    if srt.size and (False or'
mutate $SB "S10 geo_flags drops the overlapping-and-approaching clause" 'hit = ((c <= 0) & (b < 0)) | ((a > 0)' 'hit = ((a > 0)'
mutate $SB "S11 sim_labels sets only one side of a contact" '                contact[b, i, j] = contact[b, j, i] = 1.0' '                contact[b, i, j] = 1.0'
mutate $SB "S12 sim_labels rolls one step too many" '        for k in range(1, max(ROLLOUT) + 1):
            if k > 1:' '        for k in range(1, max(ROLLOUT) + 1):
            if k >= 1:'
# analysis
mutate $AN "A1 Bonferroni with m = 6" '    p_bonf, p_95 = 1 - ALPHA / (2 * M), 1 - ALPHA / 2' '    p_bonf, p_95 = 1 - ALPHA / (2 * 6), 1 - ALPHA / 2'
mutate $AN "A2 GZ-W upper bound non-strict" '"point": ("<=", 0.95), "interval": ("upper", "<", 1.0)}' '"point": ("<=", 0.95), "interval": ("upper", "<=", 1.0)}'
mutate $AN "A3 GT counts the whole truth-curriculum gain" '            return (a - b) - 0.5 * (c - b)' '            return (a - b) - 1.0 * (c - b)'
mutate $AN "A4 worlds redrawn for arm R (unpaired)" '            S = np.einsum("bw,knwc->bknc", Mw, np.asarray(d["sums"][arm], float))' \
  '            S = np.einsum("bw,knwc->bknc", np.roll(Mw, 1, 0) if arm == "R" else Mw, np.asarray(d["sums"][arm], float))'
mutate $AN "A5 ratios not on the log scale" '    if spec["form"] != "ratio":
        return x' '    if True:
        return x'
mutate $AN "A6 replicate variance not divided by K" '    se = math.sqrt(s_rep ** 2 / K + se_w ** 2)' '    se = math.sqrt(s_rep ** 2 + se_w ** 2)'
mutate $AN "A7 t with K degrees of freedom" '    q = t_ppf(p, K - 1) if K > 1 else norm_ppf(p)' '    q = t_ppf(p, K) if K > 1 else norm_ppf(p)'
mutate $AN "A8 per-replicate GS check dropped" '            row["per_replicate_ok"] = all(' '            row["per_replicate_ok"] = True or all('
mutate $AN "A9 GX on the main set" '    "GX":   {"set": "extrap10",' '    "GX":   {"set": "main6",'
mutate $AN "A10 NaN passes" '    return bool(math.isfinite(x) and _OPS[op](x, v))' '    return bool(not math.isfinite(x) or _OPS[op](x, v))'
mutate $AN "A11 world draws not shared: extrap drawn first" '        for t in TEST_SETS:
            out[t][b] = rng.integers' '        for t in reversed(TEST_SETS):
            out[t][b] = rng.integers'
# cells (static test)
mutate $CE "C1 the seal forgets reveal" '           (S.CandidatePool, "_simulate"), (S.CandidatePool, "reveal")]' '           (S.CandidatePool, "_simulate")]'
mutate $CE "C2 select reveals to score" '            rem = track.cp.remaining()' '            rem = track.cp.remaining(); track.cp.revealed_pool()'

for f in $SB $AN $CE; do cp $f.orig $f; done
echo "== restored: $(run)"
