#!/bin/bash
# Tier-1 check of P252: run its tests on the live tree, then three mutations in a fresh copy (git archive HEAD + the new files).
set -u
cd /Users/mac/AinerWorkFlow/AinerZero
S=/private/tmp/claude-501/-Users-mac-AinerWorkFlow-AinerZero/5118e0e1-b57e-4d08-9ee5-a303f5852c7e/scratchpad
PY=/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python
echo "== live tests"; $PY -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s6_epinet_mlx.py 2>&1 | tail -3
M=$S/mut-p252; rm -rf $M; mkdir -p $M
git archive HEAD | tar -x -C $M
cp -R src/ainerzero/v9/experiments/s6 $M/src/ainerzero/v9/experiments/ ; rm -rf $M/src/ainerzero/v9/experiments/s6/__pycache__
cp tests/v9/experiments/test_s6_epinet_mlx.py $M/tests/v9/experiments/; cp tests/conftest.py $M/tests/conftest.py
F=$M/src/ainerzero/v9/experiments/s6/epinet_mlx.py; cp $F $F.orig
run() { (cd $M && PYTHONPATH=$M/src $PY -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s6_epinet_mlx.py 2>&1 | tail -1); }
echo "== baseline in copy: $(run)"
mut() { cp $F.orig $F; $PY - "$F" "$1" "$2" <<'PY'
import sys
p, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(p).read(); n = s.count(old); assert n >= 1, ("pattern not found", old)
open(p, "w").write(s.replace(old, new)); print("replaced", n)
PY
echo "== $3: $(run)"; }
mut "hs = mx.stop_gradient(hid)" "hs = hid" "no stop_gradient on hid"
mut "self.prior.freeze()" "pass" "prior not frozen"
mut "rng = np.random.default_rng(index_seed + k)" "rng = np.random.default_rng()" "spread unseeded"
mut "pred = mx.stop_gradient(o) +" "pred = o +" "no stop_gradient on base output"
cp $F.orig $F; echo "== restored: $(run)"
