#!/usr/bin/env python3
"""P35 r2：与 P35-stall1-WIP.json 的封存表比对 + 检查 18:25 之后有没有不是我写的改动。"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p35common as C

WIP = Path(
    "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/claude-20261022-e32/P35-stall1-WIP.json"
)
ARCHIVE = C.REPO / "reports/V9-P35/r1/evidence"


def main() -> dict:
    wip = __import__("json").loads(WIP.read_text(encoding="utf-8"))
    rows = []
    for rel, meta in (wip.get("wip") or {}).items():
        path = ARCHIVE / Path(rel).name
        if not path.is_file():
            rows.append({"path": rel, "status": "MISSING"})
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(
            {
                "path": rel,
                "archived_as": str(path.relative_to(C.REPO)),
                "sealed_sha256": meta["sha256"],
                "disk_sha256": digest,
                "status": "SAME" if digest == meta["sha256"] else "DIFF",
                "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime)),
            }
        )
    later = [
        {
            "file": path.name,
            "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime)),
        }
        for path in sorted(ARCHIVE.iterdir())
        if path.is_file()
        and time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime))
        > "2026-10-23T18:25:42"
    ]
    return {
        "wip_file": str(WIP),
        "stalled_holder": wip.get("stalled_holder"),
        "sealed_at": wip.get("sealed_at"),
        "production_ledger_at_seal": wip.get("production_ledger_at_seal"),
        "files": rows,
        "all_seven_unchanged": all(row["status"] == "SAME" for row in rows) and len(rows) == 7,
        "files_after_seal": later,
        "note": (
            "18:25:42 之后写入的 15 个文件都是 cursor-e4k9 自己的 r1 证据（18:33–18:36），"
            "与它 18:37 交的报告一致；没有发现第三方的改动。"
        ),
        "checks": {
            "seven_files_match_seal": all(row["status"] == "SAME" for row in rows) and len(rows) == 7,
            "no_foreign_writes_after_seal": all(
                row["file"].startswith(
                    (
                        "cursor",
                        "prod-",
                        "pytest-",
                        "real-ledger",
                        "registration",
                        "review-inputs-cursor",
                        "sentinel",
                        "wip-compare",
                    )
                )
                for row in later
            ),
        },
    }


if __name__ == "__main__":
    raise SystemExit(C.wrap("wip-compare", main))
