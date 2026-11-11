#!/bin/sh
# Write ../SHA256SUMS.txt over every file in evidence/ (and REPORT.md), paths relative to r0-review/.
cd "$(dirname "$0")/.." || exit 1
{ shasum -a 256 REPORT.md; find evidence -type f ! -name '.DS_Store' | LC_ALL=C sort | xargs shasum -a 256; } > SHA256SUMS.txt
shasum -a 256 -c SHA256SUMS.txt | grep -vc ': OK$' | sed 's/^/files failing check: /'
wc -l < SHA256SUMS.txt | sed 's/^/entries: /'
