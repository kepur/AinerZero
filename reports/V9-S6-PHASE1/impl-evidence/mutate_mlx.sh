#!/bin/zsh
# Mutations of the MLX parts (cells, verify) against the native tests. Isolated copy: git archive HEAD + the
# working-tree S6 files; PYTHONPATH points at the copy. Run under the shared MLX lock.
set -u
ROOT=/Users/mac/AinerWorkFlow/AinerZero
PY=$ROOT/.venv/bin/python
WORK=$(mktemp -d "${TMPDIR:-/tmp}/s6-mlx-mut.XXXXXX")
cd $ROOT
git archive HEAD src tests pyproject.toml reports/V9-S6-PHASE1 | tar -x -C $WORK
for f in src/ainerzero/v9/experiments/s6/cells.py src/ainerzero/v9/experiments/s6/sandbox.py src/ainerzero/v9/experiments/s6/analysis.py \
         reports/V9-S6-PHASE1/run_s6p1.py reports/V9-S6-PHASE1/verify_s6p1.py \
         tests/v9/experiments/test_s6_cells_native.py tests/v9/experiments/test_s6p1_runner_native.py; do
  cp $f $WORK/$f
done
cd $WORK
export PYTHONPATH=$WORK/src
$PY -c "import ainerzero.v9.experiments.s6.cells as c; print('cells from', c.__file__)"
CE=src/ainerzero/v9/experiments/s6/cells.py; VE=reports/V9-S6-PHASE1/verify_s6p1.py
cp $CE $CE.orig; cp $VE $VE.orig
run() { $PY -m pytest -q -p no:cacheprovider --native-mlx $=1 2>&1 | tail -1; }
mutate() {  # file, name, tests, old, new
  local file=$1 name=$2 tests=$3 old=$4 new=$5
  cp $CE.orig $CE; cp $VE.orig $VE
  $PY - "$file" "$old" "$new" <<'PYEOF'
import sys
p, old, new = sys.argv[1:]
s = open(p).read()
assert s.count(old) == 1, f"anchor not found once in {p}: {old[:60]!r}"
open(p, "w").write(s.replace(old, new))
PYEOF
  echo "== $name: $(run $tests)"
}
CN=tests/v9/experiments/test_s6_cells_native.py; RN=tests/v9/experiments/test_s6p1_runner_native.py
echo "== baseline cells: $(run $CN)"
mutate $CE "M1 candidate ids sorted by (disks, world, step) again" $CN \
  'chosen = sorted((eps[pairs[i][0]].n_disks, rank, pairs[i][0], pairs[i][1]) for rank, i in enumerate(pick))' \
  'chosen = sorted((eps[pairs[i][0]].n_disks, pairs[i][0] * 10**6 + pairs[i][1], pairs[i][0], pairs[i][1]) for rank, i in enumerate(pick))'
mutate $CE "M2 closest_pair scores the farthest pair (inside closest_pair)" $CN \
  '        per[n] = -d.min((1, 2))' '        per[n] = d.min((1, 2))'
mutate $CE "M3 the seal forgets revealed_pool (equivalent while _assemble stays sealed)" $CN \
  '(S.CandidatePool, "reveal"), (S.CandidatePool, "revealed_pool"),' '(S.CandidatePool, "reveal"),'
mutate $CE "M3b the seal forgets revealed_pool and _assemble" $CN \
  '(S.CandidatePool, "reveal"), (S.CandidatePool, "revealed_pool"),
           (S.CandidatePool, "_assemble")]' '(S.CandidatePool, "reveal")]'
mutate $VE "M4 replay always passes (P257 mutant 6)" $RN \
  '    out["passed"] = bool(out["first_ok"] and all(out["rounds_ok"]))' '    out["passed"] = True'
mutate $CE "M5 T trains without the collision curriculum" $CN \
  'lr.train(pool, sizes.steps, T_COLL_SHARE if arm == "T" else 0.0)' 'lr.train(pool, sizes.steps, 0.0)'
cp $CE.orig $CE; cp $VE.orig $VE
echo "== restored cells: $(run $CN)"
