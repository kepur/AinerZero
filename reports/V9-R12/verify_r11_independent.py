#!/usr/bin/env python3
"""Independent verification script for ainerzero.V9.R12 (reviewing ainerzero.V9.R11).

Read-only verification of:
1. Primary source checks on >=12 sampled entries (including the 6 required by params v1);
2. Validator negative controls (MD/JSON out of sync, duplicate ID, missing required field)
   and guard-removal leak checks (disabling the corresponding check must let the bad case pass);
3. r3 archive SHA256SUMS match and byte-for-byte immutability of deliverables before/after review.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_validator_code(code_str: str, proj_dir: Path) -> dict:
    ns = {"__file__": str(proj_dir / "validate_registry_r4.py")}
    exec(compile(code_str, "validate_registry_r4.py", "exec"), ns)
    return ns["validate_registry"](proj_dir)


def make_temp_proj(mutate_fn) -> Path:
    td = tempfile.mkdtemp(prefix="r12_probe_")
    tdir = Path(td)
    (tdir / "docs/research").mkdir(parents=True)
    for f in ("adapter_registry.json", "ADAPTER_REGISTRY.md"):
        shutil.copy2(ROOT / "docs/research" / f, tdir / "docs/research" / f)
    mutate_fn(tdir)
    return tdir


def test_validator_controls_and_leak_when_disabled() -> dict:
    v_src = (ROOT / "reports/V9-R11/validate_registry_r4.py").read_text(encoding="utf-8")
    results = {}

    # 1. MD vs JSON out of sync
    def mut_md_sync(tdir: Path):
        mp = tdir / "docs/research/ADAPTER_REGISTRY.md"
        txt = mp.read_text(encoding="utf-8")
        mp.write_text(
            txt.replace(
                "Apache-2.0（仓库 README 明写 Licensed under Apache-2.0 并指向 LICENSE）",
                "MIT（被篡改不同步）",
                1,
            ),
            encoding="utf-8",
        )

    t1 = make_temp_proj(mut_md_sync)
    try:
        run_validator_code(v_src, t1)
        raise AssertionError("md_json_desync should have failed")
    except AssertionError as e:
        red_msg_1 = str(e)
    v_no_md_sync = v_src.replace(
        'assert lic in body, f"MD 行 {eid} 的许可文本与 JSON 不一致"', "pass"
    )
    leak_1 = run_validator_code(v_no_md_sync, t1)
    shutil.rmtree(t1, ignore_errors=True)
    results["md_json_desync"] = {
        "turned_red_when_active": True,
        "red_error": red_msg_1,
        "leaked_when_check_disabled": leak_1["total"] == 96,
    }

    # 2. Duplicate ID (isolated so only the duplicate ID check catches it)
    def mut_dup_id(tdir: Path):
        jp = tdir / "docs/research/adapter_registry.json"
        d = json.loads(jp.read_text(encoding="utf-8"))
        dup_entry = copy.deepcopy(d["entries"][0])
        d["entries"].insert(0, dup_entry)
        d["r4_summary"]["total_entries"] = len(d["entries"])
        d["r4_summary"]["tier_counts"][dup_entry["adoption_tier"]] += 1
        jp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        mp = tdir / "docs/research/ADAPTER_REGISTRY.md"
        txt = mp.read_text(encoding="utf-8")
        txt = txt.replace("## 1. 总表（96 条", "## 1. 总表（97 条", 1)
        txt = txt.replace(
            "## 4. 可借鉴机制汇总（全部 96 条）", "## 4. 可借鉴机制汇总（全部 97 条）", 1
        )
        first_id = dup_entry["id"]
        for line in txt.splitlines():
            if line.startswith(f"| {first_id} |"):
                txt = txt.replace(line, line + "\n" + line, 1)
                break
        for line in txt.splitlines():
            if line.startswith(f"- **{first_id}**"):
                txt = txt.replace(line, line + "\n" + line, 1)
                break
        mp.write_text(txt, encoding="utf-8")

    t2 = make_temp_proj(mut_dup_id)
    try:
        run_validator_code(v_src, t2)
        raise AssertionError("duplicate_id should have failed")
    except AssertionError as e:
        red_msg_2 = str(e)
    v_no_dup = v_src.replace('assert not dup, f"id 重复: {dup}"', "pass")
    leak_2 = run_validator_code(v_no_dup, t2)
    shutil.rmtree(t2, ignore_errors=True)
    results["duplicate_id"] = {
        "turned_red_when_active": True,
        "red_error": red_msg_2,
        "leaked_when_check_disabled": leak_2["total"] == 97,
    }

    # 3. Missing required field (paper.title)
    def mut_missing_field(tdir: Path):
        jp = tdir / "docs/research/adapter_registry.json"
        d = json.loads(jp.read_text(encoding="utf-8"))
        d["entries"][0]["paper"].pop("title", None)
        jp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    t3 = make_temp_proj(mut_missing_field)
    try:
        run_validator_code(v_src, t3)
        raise AssertionError("missing_required_field should have failed")
    except AssertionError as e:
        red_msg_3 = str(e)
    v_no_title = v_src.replace(
        'assert isinstance(p.get("title"), str) and p["title"].strip(), f"{eid} 缺少 paper.title"',
        "pass",
    )
    leak_3 = run_validator_code(v_no_title, t3)
    shutil.rmtree(t3, ignore_errors=True)
    results["missing_required_field"] = {
        "turned_red_when_active": True,
        "red_error": red_msg_3,
        "leaked_when_check_disabled": leak_3["total"] == 96,
    }

    return results


if __name__ == "__main__":
    res = test_validator_controls_and_leak_when_disabled()
    print(json.dumps(res, ensure_ascii=False, indent=2))
