#!/usr/bin/env python3
"""P25 独立钉扎核对（step5p-9q4t）。

在上一棒 step5p-4b89 的 verify_pinned.py 基础上扩充（改动说明：
新增 ① review_inputs.json 自身 SHA 核对 ② src_changed_vs_r8_pins 的 worker.py
r8->r9 变化核对 ③ r8 原件条目里 now/same 字段与实际重算值的一致性核对
④ r8 冻结目录按目录内 SHA256SUMS.txt 全量自核 ⑤ JSON 汇总输出）。
逐文件重算 review_inputs 钉扎的 74 个 pinned 文件 SHA256/字节数，
r8 原件 / P24 原件 / r8 冻结目录字节必须不变。只读，不写任何被核对文件。
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
INPUTS = Path("/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/claude-20261022-e32/P15-r9-review-inputs.json")
EXPECTED_INPUTS_SHA = "b8e0a4ddb49102d87de73b9bef680774f39a5130c7e293b6257450f2dac1358e"
OUT_JSON = ROOT / "reports/V9-P25/logs/pinned-verify.json"


def sha256(p: Path):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    spec = json.loads(INPUTS.read_text())
    report = {
        "generated_by": "step5p-9q4t (P25 独立复核)",
        "command": ".venv/bin/python reports/V9-P25/harness/verify_pinned.py",
        "review_inputs_sha256": {"expected": EXPECTED_INPUTS_SHA, "actual": sha256(INPUTS)},
        "pinned_files": {},
        "r8_originals": {},
        "p24_originals": {},
        "r8_freeze_dir_selfcheck": {},
        "src_changed_vs_r8": {},
    }
    problems = 0

    # 0. review_inputs.json 自身 SHA
    ri_ok = report["review_inputs_sha256"]["actual"] == EXPECTED_INPUTS_SHA
    report["review_inputs_sha256"]["match"] = ri_ok
    print(f"== review_inputs.json sha256 = {report['review_inputs_sha256']['actual']}  (expected {EXPECTED_INPUTS_SHA})  match={ri_ok}")
    if not ri_ok:
        problems += 1

    # 1. 74 pinned files
    files = spec["files"]
    ok = bad = missing = 0
    lines = []
    for rel in sorted(files):
        p = ROOT / rel
        if not p.exists():
            missing += 1
            lines.append(f"MISSING  {rel}")
            continue
        actual = sha256(p)
        size = p.stat().st_size
        want = files[rel]["sha256"]
        want_bytes = files[rel]["bytes"]
        status = "OK " if (actual == want and size == want_bytes) else "MISMATCH"
        if status == "OK ":
            ok += 1
        else:
            bad += 1
        lines.append(f"{status} {actual}  bytes={size}/{want_bytes}  {rel}")
    report["pinned_files"] = {"total": len(files), "ok": ok, "mismatch": bad, "missing": missing,
                              "declared_pinned_file_count": spec["pinned_file_count"]}
    print(f"== pinned files: total={len(files)} ok={ok} mismatch={bad} missing={missing}  (params.pinned_file_count={spec['pinned_file_count']})")
    for ln in lines:
        print(ln)
    problems += bad + missing

    # 2. r8 originals（含 now/same 字段一致性）
    r8 = spec["must_be_unchanged_r8_originals"]
    r8_bad = 0
    print(f"\n== r8 originals: total={len(r8)}")
    for rel in sorted(r8):
        p = ROOT / rel
        entry = r8[rel]
        if not p.exists():
            r8_bad += 1
            print(f"MISSING  {rel}")
            continue
        actual = sha256(p)
        same = actual == entry["sha256"]
        fields_consistent = (entry.get("now") == actual and entry.get("same") is True)
        if not same or not fields_consistent:
            r8_bad += 1
        print(f"{'OK ' if same else 'MISMATCH'} {actual}  {rel}  (now/same fields consistent={fields_consistent})")
    report["r8_originals"] = {"total": len(r8), "mismatch": r8_bad}
    print(f"r8 originals mismatch={r8_bad}")
    problems += r8_bad

    # 3. P24 originals
    p24 = spec["must_be_unchanged_p24_originals"]
    p24_bad = 0
    print(f"\n== p24 originals: total={len(p24)}")
    for rel in sorted(p24):
        p = ROOT / rel
        want = p24[rel]
        if not p.exists():
            p24_bad += 1
            print(f"MISSING  {rel}")
            continue
        actual = sha256(p)
        same = actual == want
        if not same:
            p24_bad += 1
        print(f"{'OK ' if same else 'MISMATCH'} {actual}  {rel}")
    report["p24_originals"] = {"total": len(p24), "mismatch": p24_bad}
    print(f"p24 originals mismatch={p24_bad}")
    problems += p24_bad

    # 4. r8 冻结目录按目录内 SHA256SUMS.txt 全量自核
    r8dir = ROOT / "artifacts/v9/s1/phase1/r8"
    sums = r8dir / "SHA256SUMS.txt"
    self_bad = 0
    print(f"\n== artifacts/v9/s1/phase1/r8/ self-check against its own SHA256SUMS.txt:")
    for line in sums.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        want, name = line.split(None, 1)
        name = name.lstrip("*").strip()
        p = r8dir / name
        if not p.exists():
            self_bad += 1
            print(f"MISSING  {name}")
            continue
        actual = sha256(p)
        if actual != want:
            self_bad += 1
        print(f"{'OK ' if actual == want else 'MISMATCH'} {actual}  bytes={p.stat().st_size}  {name}")
    report["r8_freeze_dir_selfcheck"] = {"mismatch": self_bad}
    print(f"r8 freeze dir self-check mismatch={self_bad}")
    problems += self_bad

    # 5. src_changed_vs_r8_pins
    print(f"\n== src_changed_vs_r8_pins:")
    for rel, pins in spec["src_changed_vs_r8_pins"].items():
        p = ROOT / rel
        actual = sha256(p) if p.exists() else None
        changed = actual != pins["r8"]
        matches_r9 = actual == pins["r9"]
        print(f"{'OK ' if matches_r9 else 'MISMATCH'} {rel}: actual={actual} r8={pins['r8']} r9={pins['r9']} changed_vs_r8={changed} matches_r9_pin={matches_r9}")
        report["src_changed_vs_r8"][rel] = {"actual": actual, "r8": pins["r8"], "r9": pins["r9"],
                                            "changed_vs_r8": changed, "matches_r9_pin": matches_r9}
        if not matches_r9:
            problems += 1

    # 6. 冻结 doc digest 交叉点
    r9pr = ROOT / "artifacts/v9/s1/phase1/r9/pre_registration.json"
    r8pr = ROOT / "artifacts/v9/s1/phase1/r8/pre_registration.json"
    print(f"\nr9 pre_registration.json sha256 = {sha256(r9pr)}")
    print(f"r8 pre_registration.json sha256 = {sha256(r8pr)}")
    report["freeze_files"] = {"r9_pre_registration_sha256": sha256(r9pr), "r8_pre_registration_sha256": sha256(r8pr)}

    report["total_problems"] = problems
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"\nTOTAL PROBLEMS = {problems}")
    print(f"json -> {OUT_JSON}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
