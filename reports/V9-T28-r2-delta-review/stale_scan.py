#!/usr/bin/env python3
"""T46 独立复核：在新版 r2 的三份人读/机读文件里找旧数字与旧措辞残留。

扫 proposal.json（按 JSON 路径逐条字符串值）、PROTOCOL.md、AMENDMENT.md，
对每个模式报出命中位置与原文，供人工判定「该保留的历史说明」还是「漏改」。
"""
import json
import re
import sys
from pathlib import Path

R2 = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-T28/r2")

PATTERNS = [
    ("half_parity", re.compile(r"half_parity")),
    ("MPS/F16", re.compile(r"MPS\s*/\s*F16|F16")),
    ("fp16/float16", re.compile(r"fp16|float16", re.I)),
    ("10 次 / 10 calls", re.compile(r"\b10\s*(次|calls?)\b")),
    ("28 视图 / 28 views", re.compile(r"\b28\s*(视图|views?)\b")),
    ("20 次 / 20 calls", re.compile(r"\b20\s*(次|calls?)\b")),
    ("56 视图 / 56", re.compile(r"\b56\b")),
    ("62", re.compile(r"\b62\b")),
    ("3 次加载 / 3 loads", re.compile(r"\b3\s*(次加载|loads?)\b")),
    ("6 次加载 / 6", re.compile(r"\b6\s*(次加载|loads?)\b|\b6\b")),
    ("unallocated 8", re.compile(r"unallocated[_a-z]*\D{0,12}8\b|\b8\s*(视图|views)")),
    ("31 视图", re.compile(r"\b31\b")),
    ("18 视图(dataset)", re.compile(r"\b18\b")),
    ("0.01 容差", re.compile(r"\b0\.01\b")),
]


def scan_json_strings(obj, prefix=""):
    """产出 (json_path, text)。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from scan_json_strings(v, f"{prefix}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from scan_json_strings(v, f"{prefix}[{i}]")
    elif isinstance(obj, str):
        yield prefix, obj


def report_hits(label, hits):
    """hits: list of (loc, text)"""
    if not hits:
        print(f"  [none] {label}")
        return 0
    print(f"  [{len(hits)} hit(s)] {label}")
    for loc, text in hits:
        print(f"      {loc}: {text}")
    return len(hits)


def main():
    total = 0
    print("=" * 78)
    print("残留旧数字 / 旧措辞扫描（新版 r2）")
    print("=" * 78)

    proposal = json.loads((R2 / "proposal.json").read_text(encoding="utf-8"))
    jstrings = list(scan_json_strings(proposal))

    for name, pat in PATTERNS:
        print(f"\n### {name}")
        # JSON
        jhits = [(loc, txt) for loc, txt in jstrings if pat.search(txt)]
        total += report_hits("proposal.json", jhits)
        # Markdown
        for fname in ("PROTOCOL.md", "AMENDMENT.md"):
            fhits = []
            for i, line in enumerate((R2 / fname).read_text(encoding="utf-8").splitlines(), 1):
                if pat.search(line):
                    fhits.append((f"{fname}:{i}", line.strip()[:220]))
            total += report_hits(fname, fhits)

    print("\n" + "=" * 78)
    print(f"总命中（含应保留的历史说明）: {total}")
    print("=" * 78)

    # 记账状态是否明确标未决
    print("\n### 记账口径状态（卡面要求：明确标未决，不得因此 reject）")
    for key in ("view_accounting", "wall_accounting"):
        blk = proposal["budget"][key]
        print(f"  budget.{key}.status = {blk.get('status')!r}")
    print(f"  budget.cumulative_wall_seconds_max = {proposal['budget']['cumulative_wall_seconds_max']!r}")
    print(f"  open_items 条数 = {len(proposal['open_items'])}")
    for i, it in enumerate(proposal["open_items"]):
        print(f"    [{i}] {it[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
