#!/usr/bin/env python3
"""ainerzero.V9.T3 证据一致性核对：被验任务 ainerzero.V9.T2 的「登记结果」与「工作树产物」是否同一份。

背景（本复核任务的第 4 类主题「并发写入」在证据层面的现实案例）：
  - 接力台登记的结果来自 composer-a7k2（14:45–14:51），其 source_sha256 中
    tests/v9/teachers/test_cache.py = 6749d11a…、pytest 23 passed；
  - 但 14:54–14:57 工作树里的 tests/v9/teachers/test_cache.py、reports/V9-T2/{REPORT.md,metrics.json}
    被上一棒 opencode-de3b（14:31 因 20 分钟无心跳被 stalled 收回）继续写入并覆盖，
    现盘上 test_cache.py = d091f1ef…、REPORT.md 与 metrics.json 的作者是 opencode-de3b、声称 44 passed。

本脚本只读核对，不改任何被验文件；退出码 1 = 有不一致（不利发现），0 = 一致。
`--poison` 用于"故意改坏必须变红"对照：篡改一条预期 SHA，断言必须变红。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
HERE = Path(__file__).resolve().parent
RELAY_SHOW = HERE / "relay_show_T2.txt"
REPORT_DIR = ROOT / "reports/V9-T2"
SUBMITTED_AT = "2026-10-20T14:51:31"   # composer-a7k2 交报告时刻（见 relay_show_T2.txt 事件行）


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reported_shas() -> dict:
    """从 `relay show ainerzero.V9.T2 --full` 的存档里解析登记的 source_sha256。"""
    text = RELAY_SHOW.read_text()
    pairs = dict(re.findall(r'"([^"]+\.(?:py|json|md))":\s*"([0-9a-f]{64})"', text))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poison", action="store_true")
    args = parser.parse_args()

    reported = reported_shas()
    if args.poison:
        # 改坏对照：把登记里 cache.py 的摘要改成伪造值，断言必须变红
        reported["src/ainerzero/v9/teachers/cache.py"] = "0" * 64

    findings: list[str] = []
    controls: list[str] = []
    per_file = {}
    matched = 0
    for rel, exp in sorted(reported.items()):
        path = ROOT / rel
        actual = sha256_of(path) if path.exists() else None
        ok = actual == exp
        matched += 1 if ok else 0
        per_file[rel] = {"reported": exp, "on_disk": actual, "match": ok}
        if not ok:
            findings.append(
                f"{rel}: 接力台登记 {exp[:12]}… 与盘上 {str(actual)[:12]}… 不一致"
            )
    if matched == 0:
        findings.append("对照失效：没有任何文件摘要与登记一致（比较器本身可能坏了）")
    else:
        controls.append(f"{matched}/{len(reported)} 个文件摘要与登记一致，比较器非空转")

    # 1) 盘上 metrics.json 的行数自述 vs 实际行数
    metrics_path = REPORT_DIR / "metrics.json"
    metrics = json.loads(metrics_path.read_text())
    line_mismatch = {}
    for rel, info in metrics.get("source_files", {}).items():
        actual_lines = len((ROOT / rel).read_text().splitlines())
        if actual_lines != info["lines"]:
            line_mismatch[rel] = {"claimed": info["lines"], "actual": actual_lines}
    if line_mismatch:
        findings.append(
            "reports/V9-T2/metrics.json 自述行数与盘上文件不符："
            + json.dumps(line_mismatch, ensure_ascii=False)
        )

    # 2) metrics.json 作者 vs 接力台登记的执行者
    relay_agent = re.search(r"执行者\s+(\S+)", RELAY_SHOW.read_text()).group(1)
    if metrics.get("agent") != relay_agent:
        findings.append(
            f"盘上 reports/V9-T2/metrics.json 的 agent={metrics.get('agent')}，"
            f"接力台登记的执行者是 {relay_agent}（两份证据不同作者）"
        )

    # 3) 声称的测试数 vs 实际跑出来的测试数
    claimed_total = sum(
        v["total_tests"] for v in metrics.get("test_results", {}).values()
    )
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "tests/v9/teachers/", "-q", "--collect-only"],
        capture_output=True, text=True, cwd=str(ROOT),
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    m = re.search(r"(\d+) tests? collected", proc.stdout)
    collected = int(m.group(1)) if m else None
    if collected is not None and claimed_total != collected:
        findings.append(
            f"盘上 metrics.json 声称 {claimed_total} 个测试，当前树实际收集 {collected} 个"
        )

    m2 = re.search(r"\*\*(\d+) passed\*\*", RELAY_SHOW.read_text())
    relay_claimed = int(m2.group(1)) if m2 else None
    if relay_claimed is not None and collected is not None and relay_claimed != collected:
        findings.append(
            f"接力台登记的 composer-a7k2 报告声称 {relay_claimed} passed，"
            f"当前工作树实际收集 {collected} 个测试（登记结果与工作树不是同一份交付）"
        )

    # 4) 报告落盘时间晚于接力台登记的交付时刻（迟到覆盖的直接证据）
    import datetime as _dt

    stamps = {}
    for p in sorted(REPORT_DIR.iterdir()):
        ts = _dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
        stamps[p.name] = ts
        if ts > SUBMITTED_AT:
            findings.append(
                f"reports/V9-T2/{p.name} 的 mtime {ts} 晚于接力台登记的交付时刻 {SUBMITTED_AT}（交付后仍被改写）"
            )

    report_text = (REPORT_DIR / "REPORT.md").read_text()
    footer = re.search(r"\*\*Agent\*\*：(\S+)", report_text)
    declared = footer.group(1) if footer else None
    if declared and declared != relay_agent:
        findings.append(
            f"盘上 reports/V9-T2/REPORT.md 署名 {declared}，接力台登记执行者 {relay_agent}"
        )

    result = {
        "verified_task": "ainerzero.V9.T2",
        "mode": "poison" if args.poison else "normal",
        "per_file": per_file,
        "line_mismatch": line_mismatch,
        "claimed_tests": claimed_total,
        "collected_tests": collected,
        "relay_claimed_tests": relay_claimed,
        "file_mtimes": stamps,
        "relay_agent": relay_agent,
        "metrics_agent": metrics.get("agent"),
        "report_declared_agent": declared,
        "findings": findings,
        "controls": controls,
        "exit": 1 if findings else 0,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result["exit"]


if __name__ == "__main__":
    sys.exit(main())
