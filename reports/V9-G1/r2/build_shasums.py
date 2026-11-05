#!/usr/bin/env python3
"""生成 reports/V9-G1/r2/SHA256SUMS.txt（路径相对仓库根，格式同 r1 证据）。

排除 SHA256SUMS.txt 自身与 __pycache__；每次运行整体重写（只覆盖本目录的清单）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
entries = []
for path in sorted(HERE.rglob("*")):
    if not path.is_file() or path.name == "SHA256SUMS.txt" or "__pycache__" in path.parts:
        continue
    rel = path.relative_to(ROOT).as_posix()
    entries.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}")
(HERE / "SHA256SUMS.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")
print(f"wrote {len(entries)} entries to reports/V9-G1/r2/SHA256SUMS.txt")
