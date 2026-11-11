#!/bin/bash
# Round B in one lock hold: filter-state pool -> error heads -> residual hybrids -> evaluation.
set -euo pipefail
cd /Users/mac/AinerWorkFlow/AinerZero
D=reports/V9-S4-P2-DESIGN/tier1-explore
S=${P2B_SCRATCH:?}
PY=.venv/bin/python
$PY $D/explore_p2b.py pool 120 5 4 $S/p2b-pool.npz
$PY $D/explore_p2b.py trainq $S/p2b-pool.npz 5000 $S
$PY $D/explore_p2b.py trainr 20000 $S 1,2,3
$PY $D/explore_p2b.py eval 40 $S $D/results-p2b.json
