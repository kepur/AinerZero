#!/usr/bin/env python3
"""生成 reports/V-V9-baseline/r3/SHA256SUMS（路径相对 AinerZero 仓库根）。"""
from __future__ import annotations

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
entries = []
for path in sorted(HERE.rglob("*")):
    if not path.is_file() or path.name == "SHA256SUMS.txt" or "__pycache__" in path.parts:
        continue
    rel = path.relative_to(REPO).as_posix()
    entries.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}")
(HERE / "SHA256SUMS.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")
print(f"wrote {len(entries)} entries to reports/V-V9-baseline/r3/SHA256SUMS.txt")
