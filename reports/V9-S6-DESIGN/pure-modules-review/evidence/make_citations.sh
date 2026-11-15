#!/bin/zsh
# P256 review: raw sed -n / grep -n output for every passage quoted in REPORT.md (C1..C30).
cd /Users/mac/AinerWorkFlow/AinerZero
SB=src/ainerzero/v9/experiments/s6/sandbox.py
AN=src/ainerzero/v9/experiments/s6/analysis.py
CE=src/ainerzero/v9/experiments/s6/cells.py
LM=src/ainerzero/v9/experiments/s4/learned_mlx.py
TS=tests/v9/experiments/test_s6_sandbox.py
TA=tests/v9/experiments/test_s6_analysis.py
TC=tests/v9/experiments/test_s6_cells_static.py
D2=reports/V9-S6-DESIGN/DESIGN-r2.md
R1=reports/V9-S6-DESIGN/r1-review-sub/REPORT.md
PR=reports/V9-S6-DESIGN/sandbox-module-review/REPORT.md
AR=reports/V9-S6-DESIGN/analysis-module/REPORT.md
ML=reports/V9-S6-PHASE1/impl-evidence/mutate_pure.log
c() { echo; echo "===== $1"; echo "\$ $2"; eval "$2"; }
echo "HEAD $(git rev-parse HEAD)"
c C1 "sed -n '41,59p' $SB | nl -ba -v41"
c C2 "grep -n 'def reveal' -A 11 $SB"
c C3 "sed -n '173,193p' $SB | nl -ba -v173"
c C4 "sed -n '101,111p' $SB | nl -ba -v101"
c C5 "sed -n '191,226p' $LM | nl -ba -v191"
c C6 "sed -n '77,94p' $TS | nl -ba -v77"
c C7 "sed -n '108,115p' $TS | nl -ba -v108"
c C8 "sed -n '136,147p' $TS | nl -ba -v136"
c C9 "sed -n '197,213p' $TS | nl -ba -v197"
c C10 "sed -n '48,65p' $AN | nl -ba -v48"
c C11 "sed -n '72,90p' $AN | nl -ba -v72"
c C12 "sed -n '195,229p' $AN | nl -ba -v195"
c C13 "sed -n '237,275p' $AN | nl -ba -v237"
c C14 "sed -n '18,38p' $TA | nl -ba -v18"
c C15 "sed -n '203,212p' $TA | nl -ba -v203"
c C16 "sed -n '139,147p' $TA | nl -ba -v139"
c C17 "sed -n '218,227p' $D2 | nl -ba -v218"
c C18 "sed -n '237,252p' $D2 | nl -ba -v237"
c C19 "sed -n '280p' $D2 | nl -ba -v280"
c C20 "sed -n '20,27p' $R1 | nl -ba -v20"
c C21 "awk '(NR>=23 && NR<=34) || (NR>=43 && NR<=55) {print NR\": \"\$0}' $PR"
c C22 "sed -n '134,155p' $CE | nl -ba -v134"
c C23 "sed -n '280,300p' $CE | nl -ba -v280"
c C24 "awk '(NR>=8 && NR<=11) || (NR>=40 && NR<=47) {print NR\": \"\$0}' $TC"
c C25 "grep -n 'A1 \\|A11 \\|baseline' $ML"
c C26 "grep -n '11 个全部被杀死\\|本模块的 11 个变异' $AR $D2"
c C27 "grep -n 'If simulating fails, nothing is registered' $SB"
c C28 "grep -n 'K = 1 there is no' -A1 $AN"
c C29 "grep -n 'cp = C.make_candidate_pool\\|tracks = \\[Track(make_candidate_pool' $CE tests/v9/experiments/test_s6_cells_native.py"
c C30 "grep -n '冒烟运行' $D2"
