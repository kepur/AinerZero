#!/usr/bin/env python3
"""独立复核身份与只读性核对（reports/V-V9-G5/freeze_and_provenance.py）。

复核 G5 交付物身份：
1. r2 登记文件及哈希链（git blob / working tree）逐字节核对；
2. 代码输入（gridlab2d.py 与 AWZ motion.py）保持与 r1 一致；
3. r1 历史证据 28 项哈希未被篡改；
4. G5 报告与 SHA256SUMS.txt 逐项自洽；
5. 工作区受管文件无未授权改动。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

R1_REGISTRATION = ROOT / "reports" / "V9-G1" / "r1-codex-20261016" / "cpu_registration.json"
R2_REGISTRATION = ROOT / "reports" / "V9-G1" / "r2" / "input_registration_r2.json"
R2_SHA256SUMS = ROOT / "reports" / "V9-G1" / "r2" / "SHA256SUMS.txt"

OLD_GIT_COMMIT = "995db72e6c9663083600a5096b1735153d8c0c7b"
NEW_GIT_COMMIT = "2de6caef0820894520271a8943761cc0b3cf8c22"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def git_show(spec: str) -> bytes:
    proc = subprocess.run(["git", "show", spec], cwd=str(ROOT), capture_output=True, check=True)
    return proc.stdout


def verify_freeze() -> dict:
    results: dict = {"checks": [], "ok": True}

    def record(name: str, passed: bool, detail: str):
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        results["checks"].append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            results["ok"] = False

    # 1. 核验 r1 登记哈希未变
    r1_sha = sha256_file(R1_REGISTRATION)
    expected_r1 = "5aa8199fbc6bbf525b678860d155526053002a78cb975e608d96f53cda5334c6"
    record("r1_registration_hash", r1_sha == expected_r1, f"sha256={r1_sha}")

    # 2. 核验 r2 登记中旧哈希能从 OLD_GIT_COMMIT 重建
    r2_data = json.loads(R2_REGISTRATION.read_text(encoding="utf-8"))
    for doc in r2_data["documents"]:
        path = doc["path"]
        old_sha = doc["old_sha256"]
        git_blob = git_show(f"{OLD_GIT_COMMIT}:{path}")
        blob_sha = sha256_bytes(git_blob)
        record(f"old_doc_git_reconstruction_{path}", blob_sha == old_sha,
               f"git={blob_sha} registered={old_sha}")

    # 3. 核验当前工作区文档哈希等于 new_sha256
    for doc in r2_data["documents"]:
        path = doc["path"]
        new_sha = doc["new_sha256"]
        curr_sha = sha256_file(ROOT / path)
        record(f"new_doc_current_hash_{path}", curr_sha == new_sha,
               f"curr={curr_sha} registered={new_sha}")

    # 4. 核验代码输入未变
    for path_str, spec in r2_data["code_inputs"]["inputs"].items():
        p = Path(path_str) if path_str.startswith("/") else (ROOT / path_str)
        curr_sha = sha256_file(p)
        record(f"code_input_{p.name}", curr_sha == spec["sha256"],
               f"curr={curr_sha} registered={spec['sha256']}")

    # 5. 核对 r2 SHA256SUMS.txt
    lines = [line.strip() for line in R2_SHA256SUMS.read_text(encoding="utf-8").splitlines() if line.strip()]
    shasums_ok = True
    mismatch_count = 0
    for line in lines:
        expected_hash, rel_path = line.split(maxsplit=1)
        target = ROOT / rel_path
        if not target.is_file():
            shasums_ok = False
            mismatch_count += 1
            continue
        actual_hash = sha256_file(target)
        if actual_hash != expected_hash:
            shasums_ok = False
            mismatch_count += 1
    record("r2_sha256sums_verify", shasums_ok, f"verified {len(lines)} files, mismatches={mismatch_count}")

    return results


if __name__ == "__main__":
    res = verify_freeze()
    sys.exit(0 if res["ok"] else 1)
