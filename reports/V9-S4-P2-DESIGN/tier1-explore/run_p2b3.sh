#!/bin/bash
# After the divergence of L-int+Q in round B's first evaluation: the evaluations again, cells that
# diverge are recorded instead of stopping the run; capped error-variance variants added.
set -uo pipefail
cd /Users/mac/AinerWorkFlow/AinerZero
D=reports/V9-S4-P2-DESIGN/tier1-explore
S=${P2B_SCRATCH:?}
PY=.venv/bin/python
$PY $D/explore_p2b.py eval 40 $S $D/results-p2b.json
$PY $D/explore_p2d.py 40 $S $D/results-p2d.json
$PY $D/explore_p2c.py 20 $S $D/results-p2c.json
