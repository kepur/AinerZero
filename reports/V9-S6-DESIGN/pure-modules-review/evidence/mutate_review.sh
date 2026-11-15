#!/bin/zsh
# P256 review, item 4: my own mutations (none of them in the author's mutate_pure.sh).
# Isolated copy: git archive HEAD src tests pyproject.toml into the session scratchpad (HEAD 34a1753 holds
# every reviewed file). PYTHONPATH points at the copy's src; an extra test asserts in-process that the
# modules come from the copy. No MLX: only the three pure test files run.
# Usage: mutate_review.sh COPY_DIR
set -u
ROOT=/Users/mac/AinerWorkFlow/AinerZero
PY=$ROOT/.venv/bin/python
WORK=$1
rm -rf $WORK && mkdir -p $WORK
cd $ROOT
echo "HEAD $(git rev-parse HEAD)"
git archive HEAD src tests pyproject.toml | tar -x -C $WORK
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

for f in $SB $AN $CE; do cp $f.orig $f; done
echo "== restored:"; run
for f in $SB $AN $CE; do cmp -s $f $ROOT/$f && echo "restored == working tree: $f"; done
