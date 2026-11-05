#!/usr/bin/env python3
"""P39 复核共用工具（只读生产库 + 隔离副本）。

约束（卡面 must_do / extra_checks）：
  * 生产 ``artifacts/v9/s1/phase1/control.sqlite3`` 只允许 hashlib 字节读，
    绝不用 sqlite3 / RunStore / 任何 Python 连接打开；
  * 任何入口只在 ``artifacts/v9/s1/phase1`` 的**临时副本**上运行；
  * 每次探针前后都记录生产库主文件 SHA、WAL 字节数与 -shm mtime。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
SRC = REPO / "src"
TESTS = REPO / "tests" / "v9" / "experiments"
PROD_PHASE1 = REPO / "artifacts" / "v9" / "s1" / "phase1"
PROD_LEDGER = PROD_PHASE1 / "control.sqlite3"
EVIDENCE = Path(__file__).resolve().parent
R13_DOC = PROD_PHASE1 / "r13" / "pre_registration.json"
R12_DOC = PROD_PHASE1 / "r12" / "pre_registration.json"
R13_SIDECAR = PROD_PHASE1 / "r13" / "pre_registration.json.sha256"
R12_SIDECAR = PROD_PHASE1 / "r12" / "pre_registration.json.sha256"
R11_DOC = PROD_PHASE1 / "r11" / "pre_registration.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


def prod_state() -> dict:
    """生产台账的只读快照：主文件 SHA、WAL 字节/SHA、-shm mtime。"""
    wal = Path(str(PROD_LEDGER) + "-wal")
    shm = Path(str(PROD_LEDGER) + "-shm")
    st = PROD_LEDGER.stat()
    return {
        "recorded_at": _iso(time.time()),
        "control.sqlite3": sha256_file(PROD_LEDGER),
        "control.sqlite3_bytes": st.st_size,
        "control.sqlite3_mtime": _iso(st.st_mtime),
        "wal_bytes": wal.stat().st_size if wal.exists() else 0,
        "wal_sha256": sha256_file(wal) if wal.exists() else None,
        "shm_exists": shm.exists(),
        "shm_bytes": shm.stat().st_size if shm.exists() else None,
        "shm_mtime": _iso(shm.stat().st_mtime) if shm.exists() else None,
        "shm_mtime_epoch": shm.stat().st_mtime if shm.exists() else None,
    }


def copy_phase1(dst_host: Path) -> Path:
    """把整个 ``artifacts/v9/s1/phase1`` 复制到 ``dst_host`` 下（隔离副本）。"""
    dst_host = Path(dst_host)
    dst = dst_host / "artifacts" / "v9" / "s1" / "phase1"
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PROD_PHASE1, dst)
    return dst


LOG_HEADING = "## R20261021-P1-stageA-budget：S1 第一阶段训练预算登记（P39 隔离演练）"


def write_research_log(host: Path, approval_sha: str | None = None, *, extra: str = "") -> Path:
    """隔离 host 上的临时 RESEARCH_LOG；stageA 节内最多一条批准行。

    批准行只写在临时副本里，生产 RESEARCH_LOG.md 一字未动。
    """
    host = Path(host)
    host.mkdir(parents=True, exist_ok=True)
    lines = [
        LOG_HEADING,
        "",
        "- 预算与资源线：进程 8 GiB、MLX 4 GiB、系统余量 16 GiB、占空比 0.25。",
        "- 本文件是 P39 复核在隔离副本上生成的临时日志，不是生产批准。",
    ]
    if approval_sha:
        lines.append(f"APPROVED s1-phase1 prereg document_sha256={approval_sha}")
    if extra:
        lines.append(extra)
    path = host / "RESEARCH_LOG.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_driver(driver: Path, host: Path, *args: str, source_root: Path | None = None,
               timeout: int = 900) -> dict:
    """在子进程里跑 driver，PYTHONPATH 指到指定源码树（真实或破坏副本）。"""
    env = dict(os.environ)
    parts = [str(source_root or SRC), str(TESTS)]
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(driver), str(host), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
        timeout=timeout,
    )
    payload = None
    for line in reversed((completed.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
                break
            except ValueError:
                continue
    return {
        "returncode": completed.returncode,
        "payload": payload,
        "stdout_tail": (completed.stdout or "")[-2000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
    }


def write_json(name: str, payload: dict) -> Path:
    path = EVIDENCE / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def wrap(name: str, fn) -> int:
    """跑一个探针，前后各记一次生产台账，结果写 evidence。"""
    before = prod_state()
    started = time.time()
    try:
        body = fn()
        ok = True
    except Exception as exc:  # noqa: BLE001 - 证据要保留异常
        body = {"exception": f"{type(exc).__name__}: {exc}"}
        ok = False
    after = prod_state()
    doc = {
        "probe": name,
        "ok": ok,
        "started_at": _iso(started),
        "elapsed_seconds": round(time.time() - started, 3),
        "production_ledger_before": before,
        "production_ledger_after": after,
        "production_ledger_unchanged": (
            before["control.sqlite3"] == after["control.sqlite3"]
            and before["wal_bytes"] == after["wal_bytes"] == 0
        ),
        "shm_mtime_changed": before["shm_mtime_epoch"] != after["shm_mtime_epoch"],
        "body": body,
    }
    write_json(f"{name}.json", doc)
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    return 0 if ok else 1
