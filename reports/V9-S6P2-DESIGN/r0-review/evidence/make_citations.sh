#!/bin/bash
set -euo pipefail
OUT="reports/V9-S6P2-DESIGN/r0-review/evidence/citations.txt"
rm -f "$OUT"

cite() {
  local file="$1"
  local range="$2"
  echo "=== ${file}:${range} ===" >> "$OUT"
  sed -n "${range}p" "$file" | nl -ba -v "${range%%,*}" >> "$OUT"
  echo "" >> "$OUT"
}

cite "ARCHITECTURE_V9.md" "141"
cite "ARCHITECTURE_V9.md" "183"
cite "ARCHITECTURE_V9.md" "211"
cite "reports/V9-S6P2-DESIGN/DESIGN-r0.md" "33,40"
cite "reports/V9-S6P2-DESIGN/DESIGN-r0.md" "105"
cite "reports/V9-S6P2-DESIGN/DESIGN-r0.md" "121,125"
cite "reports/V9-S6P2-DESIGN/DESIGN-r0.md" "147,151"
cite "reports/V9-S6P2-DESIGN/DESIGN-r0.md" "160,167"
cite "reports/V9-S6P2-DESIGN/DESIGN-r0.md" "195,200"
cite "reports/V9-S6P2-DESIGN/DESIGN-r0.md" "210,212"
cite "reports/V9-S6P2-DESIGN/DESIGN-r0.md" "219,221"
cite "reports/V9-S6P2-DESIGN/DESIGN-r0.md" "258,262"
cite "src/ainerzero/v9/experiments/s6/world_b.py" "51,58"
cite "src/ainerzero/v9/experiments/s6/world_b.py" "67,74"
cite "reports/V9-S6P2-DESIGN/tier1-explore/explore_p2d.py" "47,56"
cite "reports/V9-S6P2-DESIGN/tier1-explore/explore_p2d.py" "59,67"
cite "reports/V9-S6P2-DESIGN/tier1-explore/explore_p2f.py" "78,86"

echo "citations.txt generated successfully."
