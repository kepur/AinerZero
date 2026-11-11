#!/bin/sh
# P214 引文：报告里每处引用的代码行，原样取自被审提交 c5387d8（git show），不读工作树。
# 用法：cd /Users/mac/AinerWorkFlow/AinerZero && sh reports/V9-S4-PHASE2/impl-review/evidence/make_citations.sh > reports/V9-S4-PHASE2/impl-review/evidence/citations.txt
set -e
run() { echo "\$ $*"; "$@"; echo; }
# 引文一律取被审提交里的文件内容（git show c5387d8:文件），与工作树此刻的状态无关。
cite() { echo "\$ git show c5387d8:$1 | grep -n '' | sed -n '$2,$3p'"; git show "c5387d8:$1" | grep -n '' | sed -n "$2,$3p"; echo; }
S4=src/ainerzero/v9/experiments/s4
P2=reports/V9-S4-PHASE2
T=tests/v9/experiments
run git rev-parse HEAD
run git diff --stat c5387d8 HEAD -- src tests reports/V9-S4-PHASE2 reports/V9-S4-P2-DESIGN pyproject.toml
# --- 设计稿 ---
echo "\$ git show c5387d8:reports/V9-S4-P2-DESIGN/DESIGN-r0.md | grep -n ..."; git show c5387d8:reports/V9-S4-P2-DESIGN/DESIGN-r0.md | grep -n "门是 L-int 的接触头\|门只读成员状态\|门是逐成员\|代码约束\|一步覆盖率：\|按被检测盘\|重新出现时的覆盖率：\|m = 11\|95% 上界必须\|GA、GC、GX 作废\|下界 > −0.03\|启动顺序\|只读一次标记写在\|评测预留按\|三个种子的行合在一起\|每个事件三个种子取平均"; echo
# --- gated.py ---
cite $S4/gated.py 11 12
cite $S4/gated.py 30 53
cite $S4/gated.py 69 84
cite $S4/models.py 20 23
# --- world / filter / metrics ---
cite $S4/world.py 46 46
cite $S4/world.py 127 127
cite $S4/filter.py 106 110
cite $S4/metrics.py 84 99
echo "\$ git show c5387d8:$S4/analysis.py | grep -n ..."; git show c5387d8:$S4/analysis.py | grep -n "CHI2_2_90 =\|EXPECTED_COLL_DISK_STEPS_PER_40 =\|^SEEDS\|^SAMPLE_BAND\|^DYN_FLOOR"; echo
# --- analysis_p2.py ---
cite $S4/analysis_p2.py 36 55
cite $S4/analysis_p2.py 94 118
cite $S4/analysis_p2.py 157 158
cite $S4/analysis_p2.py 175 184
cite $S4/analysis_p2.py 224 242
cite $S4/analysis_p2.py 265 320
# --- runner / prereg ---
cite $P2/run_s4p2.py 12 14
cite $P2/run_s4p2.py 80 114
cite $P2/run_s4p2.py 222 266
cite $P2/run_s4p2.py 300 303
cite $P2/make_prereg.py 53 57
cite $P2/verify_replay_p2.py 33 51
# --- tests ---
cite $T/test_s4_analysis_p2.py 149 153
cite $T/test_s4_analysis_p2.py 210 222
cite $T/test_s4_analysis_p2.py 234 236
cite $T/test_s4_analysis_p2.py 99 119
cite $T/test_s4p2_runner_native.py 182 193
cite $T/test_s4p2_runner_native.py 247 286
cite $T/test_s4_gated.py 151 158
cite $P2/run_s4p2.py 117 146
cite $P2/run_s4p2.py 166 176
cite $T/test_s4_gated.py 62 86
cite $T/test_s4_analysis_p2.py 54 69
cite $S4/worker_p2.py 38 47
cite $S4/filter.py 35 43
cite $S4/analysis_p2.py 58 72
cite $S4/analysis_p2.py 121 128
cite $P2/run_s4p2.py 40 66
cite $P2/run_s4p2.py 149 163
cite reports/V9-S4-P2-DESIGN/tier1-explore/explore_p2e.py 38 45
echo "\$ git show c5387d8:$P2/make_prereg.py | grep -n training"; git show c5387d8:$P2/make_prereg.py | grep -n '"training": False'; echo
cite $S4/analysis.py 321 337
cite $S4/analysis_p2.py 243 263
cite $P2/make_prereg.py 17 22
cite $T/test_s4_gated.py 47 59
