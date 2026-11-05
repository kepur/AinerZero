#!/usr/bin/env python3
"""P35 r2：review_inputs 逐项复算 + 生产台账不变量（只读字节）。

用法： python3 review_inputs_check.py start|end [--out 文件]
约束：
  - 生产 control.sqlite3 只用字节读（hashlib 流式读），绝不 sqlite3 / RunStore 打开；
  - 同时记录主库 SHA、WAL 字节数、WAL SHA、-shm mtime（-shm 不计入台账内容）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
EXPECTED = Path(__file__).with_name("review_inputs_expected.json")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stat_of(p: Path) -> dict:
    if not p.exists():
        return {"exists": False}
    st = p.stat()
    return {
        "exists": True,
        "bytes": st.st_size,
        "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)),
        "mtime_epoch": st.st_mtime,
    }


def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else "start"
    out = None
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])

    exp = json.loads(EXPECTED.read_text(encoding="utf-8"))
    rows = []
    ok_all = True
    for rel, want in exp["files"].items():
        p = ROOT / rel
        if not p.is_file():
            rows.append({"path": rel, "status": "MISSING", "want": want, "got": None})
            ok_all = False
            continue
        got = sha256_file(p)
        ok = got == want
        ok_all &= ok
        rows.append({"path": rel, "status": "OK" if ok else "MISMATCH", "want": want, "got": got})

    # 生产台账：只读字节
    ledger_rel = "artifacts/v9/s1/phase1/control.sqlite3"
    lp = ROOT / ledger_rel
    inv = exp["production_ledger"]
    ledger_sha = sha256_file(lp)
    wal = ROOT / (ledger_rel + "-wal")
    shm = ROOT / (ledger_rel + "-shm")
    wal_bytes = wal.stat().st_size if wal.exists() else 0
    wal_sha = sha256_file(wal) if wal.exists() else None
    ledger = {
        "sha256": ledger_sha,
        "want_sha256": inv[ledger_rel],
        "sha_ok": ledger_sha == inv[ledger_rel],
        "wal_bytes": wal_bytes,
        "wal_sha256": wal_sha,
        "wal_ok": wal_bytes == inv["artifacts/v9/s1/phase1/control.sqlite3-wal_bytes"],
        "shm": stat_of(shm),
        "main_stat": stat_of(lp),
    }
    ok_all &= ledger["sha_ok"] and ledger["wal_ok"]

    doc = {
        "phase": phase,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "epoch": time.time(),
        "cwd": os.getcwd(),
        "files_total": len(rows),
        "files_ok": sum(1 for r in rows if r["status"] == "OK"),
        "all_ok": ok_all,
        "production_ledger": ledger,
        "rows": rows,
        "note": "生产台账只用 hashlib 字节读；未用 sqlite3 / RunStore 打开。",
    }
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if out:
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
