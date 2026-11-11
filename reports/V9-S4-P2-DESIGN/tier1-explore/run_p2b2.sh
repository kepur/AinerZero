#!/bin/bash
# Round B (restart) and rounds C, D in one lock hold.
set -euo pipefail
cd /Users/mac/AinerWorkFlow/AinerZero
D=reports/V9-S4-P2-DESIGN/tier1-explore
S=${P2B_SCRATCH:?}
PY=.venv/bin/python
$PY $D/explore_p2b.py trainr 20000 $S 1,2,3
$PY $D/explore_p2b.py trainqr $S 5000
$PY $D/explore_p2b.py eval 40 $S $D/results-p2b.json
$PY $D/explore_p2d.py 40 $S $D/results-p2d.json
$PY $D/explore_p2c.py 20 $S $D/results-p2c.json
