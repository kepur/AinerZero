#!/bin/sh
# P216 引文生成脚本：原样取自被审提交 50f9edf（git show 50f9edf:...），与工作树此刻状态无关。
set -e
run() { echo "\$ $*"; "$@"; echo; }
cite() { echo "\$ git show 50f9edf:$1 | grep -n '' | sed -n '$2,$3p'"; git show "50f9edf:$1" | grep -n '' | sed -n "$2,$3p"; echo; }

S4=src/ainerzero/v9/experiments/s4
P2=reports/V9-S4-PHASE2
T=tests/v9/experiments
D=reports/V9-S4-P2-DESIGN/DESIGN-r1.md

echo "=== 1. Commit and Diff Context ==="
run git rev-parse 50f9edf
run git diff --stat c5387d8 50f9edf -- src/ tests/ reports/V9-S4-PHASE2/

echo "=== 2. Design Basis (DESIGN-r1.md) ==="
echo "\$ git show 50f9edf:$D | grep -n ... (Design r1 Table & §3, §5, §6)"
git show "50f9edf:$D" | grep -n "必修 M1\|建议 R1\|建议 R2\|建议 R3\|L-sc-g\|L-int-rand\|GR 学到的响应\|m = 12\|Bonferroni 上界\|derive_seed(ns, 'arm-rng'\|确定性"
echo

echo "=== 3. Implementation: gated.py ==="
cite $S4/gated.py 37 40
cite $S4/gated.py 66 70
cite $S4/gated.py 72 100
cite $S4/gated.py 102 126
cite $S4/gated.py 128 138

echo "=== 4. Implementation: analysis_p2.py ==="
cite $S4/analysis_p2.py 35 50
cite $S4/analysis_p2.py 60 67
cite $S4/analysis_p2.py 82 93
cite $S4/analysis_p2.py 145 152
cite $S4/analysis_p2.py 165 180
cite $S4/analysis_p2.py 295 301
cite $S4/analysis_p2.py 315 330
cite $S4/analysis_p2.py 385 400

echo "=== 5. Implementation: worker_p2.py, verify_replay_p2.py, make_prereg.py ==="
cite $S4/worker_p2.py 38 48
cite $P2/verify_replay_p2.py 35 45
cite $P2/make_prereg.py 70 76

echo "=== 6. Test Suite Evidence ==="
cite $T/test_s4_gated.py 160 219
cite $T/test_s4_analysis_p2.py 20 37
cite $T/test_s4_analysis_p2.py 150 165
cite $T/test_s4_analysis_p2.py 185 195
cite $T/test_s4_analysis_p2.py 290 305
cite $T/test_s4_analysis_p2.py 315 348
cite $T/test_s4p2_runner_native.py 135 152
