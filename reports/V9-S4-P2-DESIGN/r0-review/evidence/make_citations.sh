#!/bin/sh
# P213: raw `sed -n` / `grep -n` output for every quotation in REPORT.md (run from anywhere; writes evidence/citations.txt).
cd "$(dirname "$0")/../../../.." || exit 1
D=reports/V9-S4-P2-DESIGN
OUT=$D/r0-review/evidence/citations.txt
{
echo "# citations for $D/r0-review/REPORT.md; repository HEAD $(git rev-parse HEAD)"
echo "# each block: the command, then its raw output (cat -n numbering = file line numbers)"
c() { echo; echo "\$ sed -n '$2,$3p' $1 | cat -n (offset $2)"; sed -n "$2,$3p" "$1" | awk -v o="$2" '{printf "%6d\t%s\n", NR+o-1, $0}'; }
g() { echo; echo "\$ grep -n '$2' $1"; grep -n "$2" "$1"; }
echo "\$ shasum -a 256 $D/DESIGN-r0.md; git diff --stat ff1a162 HEAD -- $D/DESIGN-r0.md"
shasum -a 256 $D/DESIGN-r0.md; git diff --stat ff1a162 HEAD -- $D/DESIGN-r0.md
c $D/DESIGN-r0.md 14 17
c $D/DESIGN-r0.md 20 21
c $D/DESIGN-r0.md 30 30
c $D/DESIGN-r0.md 59 59
c $D/DESIGN-r0.md 74 74
c $D/DESIGN-r0.md 84 86
c $D/DESIGN-r0.md 110 110
c $D/DESIGN-r0.md 117 119
c $D/DESIGN-r0.md 129 131
c $D/DESIGN-r0.md 135 147
c $D/DESIGN-r0.md 150 158
c $D/DESIGN-r0.md 196 197
c $D/DESIGN-r0.md 216 225
c reports/V9-S4-DESIGN/DESIGN-r3.md 204 204
c src/ainerzero/v9/experiments/s4/world.py 60 64
c src/ainerzero/v9/experiments/s4/world.py 99 113
c src/ainerzero/v9/experiments/s4/world.py 127 127
c src/ainerzero/v9/experiments/s4/models.py 20 22
c src/ainerzero/v9/experiments/s4/gated.py 46 53
c src/ainerzero/v9/experiments/s4/gated.py 69 83
c src/ainerzero/v9/experiments/s4/analysis_p2.py 11 13
c src/ainerzero/v9/experiments/s4/analysis_p2.py 33 39
c src/ainerzero/v9/experiments/s4/analysis_p2.py 64 67
c src/ainerzero/v9/experiments/s4/analysis_p2.py 94 107
c src/ainerzero/v9/experiments/s4/analysis_p2.py 110 118
c src/ainerzero/v9/experiments/s4/analysis_p2.py 265 273
c src/ainerzero/v9/experiments/s4/analysis_p2.py 297 298
c src/ainerzero/v9/experiments/s4/analysis_p2.py 314 316
c src/ainerzero/v9/experiments/s4/metrics.py 89 94
c src/ainerzero/v9/experiments/s4/filter.py 108 110
c $D/tier1-explore/explore_p2f.py 95 95
c $D/tier1-explore/run-p2b2.log 13 13
c $D/tier1-explore/run-p2f.log 40 41
c $D/tier1-explore/run-p2f.log 60 61
c $D/tier1-explore/run-p2e.log 41 41
g $D/tier1-explore/summary-p2f-main.txt 'L-int-g@0.5\|^E-B\|^E-P'
g tests/v9/experiments/test_s4_gated.py 'def test_gates_never_read_the_world_or_its_physics'
} > $OUT 2>&1
echo "wrote $OUT ($(wc -l < $OUT) lines)"
