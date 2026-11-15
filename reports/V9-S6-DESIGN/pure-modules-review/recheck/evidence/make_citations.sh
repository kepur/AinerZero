#!/bin/zsh
# P256 recheck: raw grep -n / sed -n output for the passages quoted in the recheck report (D1..D6).
cd /Users/mac/AinerWorkFlow/AinerZero
c() { echo; echo "===== $1"; echo "\$ $2"; eval "$2"; }
echo "HEAD $(git rev-parse HEAD) (fixes uncommitted in the working tree)"
c D1 "grep -n 'monkeypatch.setattr(W, \"physics\", counting)\|assert calls == \[\]\|assert len(calls) == 3 \* max(S.ROLLOUT)' tests/v9/experiments/test_s6_sandbox.py"
c D2 "grep -n 'point_ok\|passed\|interval_ok' tests/v9/experiments/test_s6_analysis.py"
c D3 "sed -n '57,58p' tests/v9/experiments/test_s6_cells_static.py | nl -ba -v57"
c D4 "grep -n 'point_ok = ' src/ainerzero/v9/experiments/s6/analysis.py"
c D5 "grep -n 'CELLS = ' tests/v9/experiments/test_s6_cells_static.py"
c D6 "grep -n 'revealed_pool\"),\|\"_assemble\")\]' src/ainerzero/v9/experiments/s6/cells.py"
