#!/bin/zsh
# P256 recheck: my 14 mutants from the first review plus N1-N4 aimed at the new tests, on a copy that holds
# the uncommitted fixes (cells.py and the three pure test files copied in from the working tree).
# Isolated copy: git archive HEAD src tests pyproject.toml into the session scratchpad, then the four changed
# files; sandbox.py and analysis.py are unchanged since HEAD. PYTHONPATH points at the copy's src; an extra test asserts in-process that the
# modules come from the copy. No MLX: only the three pure test files run.
# Usage: mutate_recheck.sh COPY_DIR
set -u
ROOT=/Users/mac/AinerWorkFlow/AinerZero
PY=$ROOT/.venv/bin/python
WORK=$1
rm -rf $WORK && mkdir -p $WORK
cd $ROOT
echo "HEAD $(git rev-parse HEAD)"
git archive HEAD src tests pyproject.toml | tar -x -C $WORK
for f in src/ainerzero/v9/experiments/s6/cells.py tests/v9/experiments/test_s6_analysis.py \
         tests/v9/experiments/test_s6_sandbox.py tests/v9/experiments/test_s6_cells_static.py; do
  cp $ROOT/$f $WORK/$f
done
cd $WORK
export PYTHONPATH=$WORK/src PYTHONDONTWRITEBYTECODE=1
echo "copy: $WORK"
cat > tests/v9/experiments/test_zz_review_origin.py <<EOF
def test_modules_come_from_the_copy():
    from ainerzero.v9.experiments.s6 import analysis, sandbox
    from ainerzero.v9.experiments.s4 import world
    for m in (analysis, sandbox, world):
        assert m.__file__.startswith("$WORK/src/"), m.__file__
EOF
SB=src/ainerzero/v9/experiments/s6/sandbox.py; AN=src/ainerzero/v9/experiments/s6/analysis.py; CE=src/ainerzero/v9/experiments/s6/cells.py
for f in $SB $AN $CE tests/v9/experiments/test_s6_sandbox.py tests/v9/experiments/test_s6_analysis.py tests/v9/experiments/test_s6_cells_static.py; do
  echo "copy == working tree: $f $(cmp -s $f $ROOT/$f && echo identical || echo DIFFERENT)"
done
$PY -c "import ainerzero.v9.experiments.s6.sandbox as a, ainerzero.v9.experiments.s6.analysis as b; print('modules from', a.__file__, b.__file__)"
T="tests/v9/experiments/test_s6_sandbox.py tests/v9/experiments/test_s6_analysis.py tests/v9/experiments/test_s6_cells_static.py tests/v9/experiments/test_zz_review_origin.py"
run() { $PY -m pytest -q -p no:cacheprovider $=T 2>&1 | grep -E "^(FAILED|ERROR)|passed|failed|error" ; }
echo "== baseline:"; run
for f in $SB $AN $CE; do cp $f $f.orig; done

mutate() {  # file, name, old, new [, old2, new2]  (each anchor must occur exactly once)
  local file=$1 name=$2
  shift 2
  for f in $SB $AN $CE; do cp $f.orig $f; done
  $PY - "$file" "$@" <<'PYEOF'
import sys
p, *pairs = sys.argv[1:]
s = open(p).read()
for old, new in zip(pairs[::2], pairs[1::2]):
    assert s.count(old) == 1, f"anchor found {s.count(old)} times in {p}: {old[:70]!r}"
    s = s.replace(old, new, 1)
open(p, "w").write(s)
PYEOF
  echo "== $name"
  diff $file.orig $file | sed 's/^/   | /'
  run
}

# --- sandbox -------------------------------------------------------------------------------------------
mutate $SB "R1 a reveal spanning two disk counts that fails in the second leaves the first group's outcomes stored" \
  '                out[g] = {k: np.array(lab[k][j], dtype=np.float32, copy=True) for k in LABEL_KEYS}' \
  '                out[g] = self._outcomes[g] = {k: np.array(lab[k][j], dtype=np.float32, copy=True) for k in LABEL_KEYS}'
mutate $SB "R1b reveal stores each disk-count group's outcomes as it simulates it (a later failing group leaves the earlier ones)" \
  '        outcomes = self._simulate(ids)
        self._revealed.extend(ids)
        self._revealed_set.update(ids)
        self._outcomes.update(outcomes)' \
  '        for n, (gs, rows) in self._groups(ids).items():
            self._outcomes.update(self._simulate(gs))
        self._revealed.extend(ids)
        self._revealed_set.update(ids)'
mutate $SB "R2 _simulate labels the whole disk-count bucket and keeps the chosen rows" \
  '            lab = self._labeller(e["p"][rows], e["v"][rows], e["pil"][rows])' \
  '            full = self._labeller(e["p"], e["v"], e["pil"])
            lab = {k: v[rows] for k, v in full.items()}'
mutate $SB "R3 states stored at float32 precision (the simulator gets rounded states)" \
  '            self._states[n] = {k: np.array(e[k], dtype=np.float64, copy=True) for k in STATE_KEYS}' \
  '            self._states[n] = {k: np.array(e[k], dtype=np.float32).astype(np.float64) for k in STATE_KEYS}'
mutate $SB "R4 sim_labels marks every contact kind (wall, pillar) in the disk-contact matrix" \
  '            if kind == "disk":' \
  '            if True:'
mutate $SB "R5 the constructor simulates every candidate straight through sim_labels and keeps the result (not via the labeller)" \
  '        self._log: list[dict[str, Any]] = []' \
  '        self._log: list[dict[str, Any]] = []
        self._cache = {n: sim_labels(e["p"], e["v"], e["pil"]) for n, e in self._states.items()}'
# --- analysis ------------------------------------------------------------------------------------------
mutate $AN "Q1 gate intervals at the 95% level (levels dict unchanged)" \
  '        lo, hi, parts = interval(spec, x, tk, boot[g], p_bonf)' \
  '        lo, hi, parts = interval(spec, x, tk, boot[g], p_95)'
mutate $AN "Q2 theta_k not paired by replicate: R and Z use replicate k+1 (point value unchanged)" \
  '    return {arm: stats(d["sums"][arm], d["counts"], d["eb"], reps, np.arange(W_)) for arm in GATE_ARMS}' \
  '    return {arm: stats(d["sums"][arm], d["counts"], d["eb"], (reps + (arm in ("R", "Z"))) % K, np.arange(W_)) for arm in GATE_ARMS}'
mutate $AN "Q3 ratio-gate point value = geometric mean of the per-replicate ratios" \
  '        tk = [float(_gate_value(spec, per_rep[spec["set"]][k])) for k in range(K)]' \
  '        tk = [float(_gate_value(spec, per_rep[spec["set"]][k])) for k in range(K)]
        if spec["form"] == "ratio":
            x = float(np.exp(np.mean(np.log(tk))))'
mutate $AN "Q4 world bootstrap nested: replicate k gets its own draw (shared across arms only)" \
  '            S = np.einsum("bw,knwc->bknc", Mw, np.asarray(d["sums"][arm], float))   # [n, K, N, 4]
            per = _per_rep_net(S, C[:, None, None, :], B[:, None, None])           # [n, K, N]' \
  '            s_ = np.asarray(d["sums"][arm], float)
            Mk = np.stack([np.roll(Mw, k, 0) for k in range(s_.shape[0])], 1)
            S = np.einsum("bkw,knwc->bknc", Mk, s_)
            per = _per_rep_net(S, (Mk @ np.asarray(d["counts"], float))[:, :, None, :], (Mk @ np.asarray(d["eb"], float))[:, :, None])'
mutate $AN "Q5 t_cdf odd-df series uses the even-df factor (matters from df = 5, i.e. K = 6)" \
  '                term *= c2 * (2 * j) / (2 * j + 1)' \
  '                term *= c2 * (2 * j - 1) / (2 * j)'
mutate $AN "Q6 s_rep with ddof 0" \
  '    s_rep = float(np.std(tk, ddof=1)) if K > 1 else 0.0' \
  '    s_rep = float(np.std(tk)) if K > 1 else 0.0'
# --- cells (static test) -------------------------------------------------------------------------------
mutate $CE "X1 select reads revealed labels through an alias of the pool (pool = track.cp; pool._assemble(...))" \
  '            rem = track.cp.remaining()' \
  '            rem = track.cp.remaining()
            pool = track.cp
            seen = pool._assemble(pool.revealed_ids().tolist())'
mutate $CE "X2 a module-level alias of W.physics, called inside closest_pair (bypasses the name check and the seal)" \
  'from ainerzero.v9.experiments.s6 import sandbox as S
' \
  'from ainerzero.v9.experiments.s6 import sandbox as S

_step = W.physics
' \
  '        p = np.asarray(e["p"], dtype=np.float64)
        d = np.linalg.norm' \
  '        p = np.asarray(e["p"], dtype=np.float64)
        _peek = _step(p[:1], np.asarray(e["v"][:1], dtype=np.float64), tuple(map(tuple, np.asarray(e["pil"][0], dtype=np.float64))))
        d = np.linalg.norm'

# --- N1-N4: aimed at the new tests ------------------------------------------------------------------------
mutate $SB "N1 the constructor precomputes every one-step outcome through a module-level alias of W.physics" \
  'STATE_KEYS = ("p", "v", "pil")
' \
  'STATE_KEYS = ("p", "v", "pil")
_phys = W.physics
' \
  '        self._log: list[dict[str, Any]] = []' \
  '        self._log: list[dict[str, Any]] = []
        self._cache = {n: [_phys(e["p"][i:i + 1], e["v"][i:i + 1], tuple(map(tuple, e["pil"][i]))) for i in range(len(e["p"]))]
                       for n, e in self._states.items()}'
mutate $AN "N2 decide ignores the point criterion (point_ok = finite)" \
  '        point_ok = math.isfinite(x) and (spec["point"] is None or _holds(spec["point"][0], x, spec["point"][1]))' \
  '        point_ok = math.isfinite(x)'
mutate $CE "N3 an alias of W.physics inside a module-level try block, called in closest_pair" \
  'from ainerzero.v9.experiments.s6 import sandbox as S
' \
  'from ainerzero.v9.experiments.s6 import sandbox as S

try:                       # optional fast path
    _step = W.physics
except AttributeError:
    _step = None
' \
  '        p = np.asarray(e["p"], dtype=np.float64)
        d = np.linalg.norm' \
  '        p = np.asarray(e["p"], dtype=np.float64)
        _peek = _step(p[:1], np.asarray(e["v"][:1], dtype=np.float64), tuple(map(tuple, np.asarray(e["pil"][0], dtype=np.float64))))
        d = np.linalg.norm'
# N4 edits two files: sandbox.py gets the alias, cells.closest_pair calls S._phys
for f in $SB $AN $CE; do cp $f.orig $f; done
$PY - $SB $CE <<'PYEOF'
import sys
sb, ce = sys.argv[1:]
s = open(sb).read(); old = 'STATE_KEYS = ("p", "v", "pil")\n'; assert s.count(old) == 1
open(sb, "w").write(s.replace(old, old + "_phys = W.physics\n", 1))
s = open(ce).read(); old = '        p = np.asarray(e["p"], dtype=np.float64)\n        d = np.linalg.norm'; assert s.count(old) == 1
open(ce, "w").write(s.replace(old, '        p = np.asarray(e["p"], dtype=np.float64)\n        _peek = S._phys(p[:1], np.asarray(e["v"][:1], dtype=np.float64), tuple(map(tuple, np.asarray(e["pil"][0], dtype=np.float64))))\n        d = np.linalg.norm', 1))
PYEOF
echo "== N4 sandbox.py holds an alias of W.physics; cells.closest_pair calls S._phys (another module's alias)"
diff $SB.orig $SB | sed 's/^/   | /'; diff $CE.orig $CE | sed 's/^/   | /'
run

for f in $SB $AN $CE; do cp $f.orig $f; done
echo "== restored:"; run
for f in $SB $AN $CE; do cmp -s $f $ROOT/$f && echo "restored == working tree: $f"; done
