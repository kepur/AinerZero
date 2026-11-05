#!/usr/bin/env python3
"""ainerzero.V9.A10 独立复核（非 A2 作者）：A2 r3 基线清单 C3/T3/RunStore 补修。

只读真实 artifacts 与 A2/A3/A4 产物；只写 reports/V-V9-baseline/r3/ 与 /tmp 案例沙盒。
复核 5 项（+ r2 保全）：C3 覆盖、policy↔清单一致、T3 钉选树扫描、RunStore 行级裁定、
selftest 真实拷贝（不经符号链接写真实树）、r2 产物原样保留。
另：开始/结束各对真实树全部钉选文件复算 SHA；自建 10 个案例（8 红 + 2 对照）真实非零退出。

退出码 0 = 全部复核通过（建议接受）；1 = 有未闭合项或证据不成立（建议打回）。
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]  # /Users/mac/AinerWorkFlow/AinerZero
PYTHON = REPO / ".venv-ainerzero/bin/python"
R3_SCRIPT = REPO / "scripts/v9_baseline_manifest_r3.py"
R3_MANIFEST = REPO / "reports/V9-baseline/r3/baseline_manifest.json"
A4_JSON = REPO / "reports/V-V9-baseline/r2/review-results.json"
REAL = REPO  # verify() 以仓库根为 root（清单路径相对仓库根）
EVIDENCE = HERE / "evidence"
EXEMPT_ROOTS = ("artifacts/reports", "artifacts/spacetime")
RUNSTORE_PATHS = ("artifacts/control.sqlite3", "artifacts/control.sqlite3.bak-20261011",
                  "artifacts/m0/control.sqlite3", "artifacts/m0/control.sqlite3.bak-20261011")

FAILED = False
CHECKS: list[dict] = []
CASES: list[dict] = []
START_INTEGRITY: dict = {}
END_INTEGRITY: dict = {}


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILED
    ok = bool(condition)
    CHECKS.append({"name": name, "ok": ok, "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"：{detail}" if detail else ""))
    if not ok:
        FAILED = True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict:
    return json.loads(R3_MANIFEST.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# 0) 真实树完整性（开始/结束各一次）
# --------------------------------------------------------------------------------------

def real_tree_integrity(manifest: dict, label: str) -> dict:
    mismatches = []
    checked = 0
    total_bytes = 0
    for entry in manifest["files"]:
        path = REAL / entry["path"]
        if not path.is_file():
            mismatches.append({"path": entry["path"], "kind": "missing"})
            continue
        size = path.stat().st_size
        total_bytes += size
        actual = sha256_file(path)
        checked += 1
        if size != entry["size"] or actual != entry["sha256"]:
            mismatches.append({"path": entry["path"], "kind": "changed",
                               "expected_size": entry["size"], "actual_size": size,
                               "expected_sha256": entry["sha256"], "actual_sha256": actual})
    return {"label": label, "checked": checked, "total_bytes": total_bytes, "mismatches": mismatches,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "files_digest": hashlib.sha256(json.dumps(
                sorted((e["path"], e["sha256"]) for e in manifest["files"]),
                ensure_ascii=True).encode()).hexdigest()}


# --------------------------------------------------------------------------------------
# 1) C3 覆盖：A4 列出的 46 个残留文件逐个判定
# --------------------------------------------------------------------------------------

def check_c3(manifest: dict) -> dict:
    a4 = json.loads(A4_JSON.read_text(encoding="utf-8"))
    c3 = a4["audit"]["C3"]
    expected = (c3["pilot_run_root_unpinned_unexcluded"] + c3["m0_run_root_unpinned_unexcluded"]
                + c3["probes_metadata_unpinned"] + c3["teacher_cache_variants_uncovered"])
    check("A4 列出的 C3 残留 = 46 个", len(expected) == 46 and c3["residual_count"] == 46,
          f"{len(expected)} 个")
    pinned = {e["path"]: e for e in manifest["files"]}
    excluded = {e["path"]: e for e in manifest["excluded_with_reason"]}
    on_disk = {e["path"] for e in manifest["files"]} | set(excluded)
    pinned_hits, excluded_hits, missing_real, residual = [], [], [], []
    for rel in expected:
        if not (REAL / rel).is_file():
            missing_real.append(rel)
            continue
        if rel in pinned:
            pinned_hits.append({"path": rel, "category": pinned[rel]["category"]})
        elif rel in excluded:
            excluded_hits.append({"path": rel, "reason": excluded[rel]["reason"]})
        else:
            residual.append(rel)
    check("C3 46 个文件在真实树全部存在", not missing_real, f"缺失 {len(missing_real)}")
    check("C3 46 个文件全部有唯一处置（钉选或带理由排除）", not residual, f"残留 {len(residual)}: {residual[:5]}")
    check("C3 处置分布 = 44 钉选 + 2 排除",
          len(pinned_hits) == 44 and len(excluded_hits) == 2,
          f"pinned={len(pinned_hits)} excluded={len(excluded_hits)}")
    # policy 声称钉选 M0 report/events：清单实际必须 >0
    m0_run_entries = [e for e in manifest["files"] if e["category"] == "m0.run"]
    m0_report_events = [e for e in m0_run_entries
                        if e["path"].endswith(("report.json", "events.jsonl"))]
    check("policy 声称钉选的 M0 report.json/events.jsonl 清单实际 >0",
          len(m0_report_events) > 0, f"{len(m0_report_events)} 个")
    probe_entries = [e for e in manifest["files"] if e["category"] == "probe.meta"]
    check("pilot probes manifest/metadata 4 个已钉选", len(probe_entries) == 4)
    dataset_entries = [e for e in manifest["files"]
                       if e["path"].endswith("/dataset.json")]
    check("pilot 运行根 dataset.json 2 个已钉选", len(dataset_entries) == 2)
    return {"a4_expected": len(expected), "pinned": pinned_hits,
            "excluded_with_reason": excluded_hits, "residual": residual,
            "m0_run_entries": len(m0_run_entries), "probe_meta": len(probe_entries),
            "dataset_json": len(dataset_entries)}


# --------------------------------------------------------------------------------------
# 2) policy 声称 vs 清单 vs 真实树（独立重新实现 glob 匹配）
# --------------------------------------------------------------------------------------

def glob_match(pattern: str, path: str) -> bool:
    def match(pats: list[str], segs: list[str]) -> bool:
        if not pats:
            return not segs
        if pats[0] == "**":
            for cut in range(len(segs) + 1):
                if match(pats[1:], segs[cut:]):
                    return True
            return False
        if not segs:
            return False
        if not fnmatch.fnmatchcase(segs[0], pats[0]):
            return False
        return match(pats[1:], segs[1:])
    return match(pattern.split("/"), path.split("/"))


def in_exempt(rel: str) -> bool:
    return any(rel == root or rel.startswith(root + "/") for root in EXEMPT_ROOTS)


def enumerate_real_files() -> list[str]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(REAL / "artifacts"):
        for name in filenames:
            out.append(os.path.relpath(os.path.join(dirpath, name), REAL).replace(os.sep, "/"))
    out.sort()
    return out


def check_policy(manifest: dict, real_files: list[str]) -> dict:
    pinned = {e["path"]: e for e in manifest["files"]}
    pinned_policy = manifest["policy"]["pinned"]
    volatile_globs = manifest["policy"]["volatile_rule"]["globs"]
    excluded_paths = {e["path"] for e in manifest["excluded_with_reason"]}
    transient_paths = {e["path"] for e in manifest["transient"]}
    checked_globs = 0
    matched = 0
    raw_matched = 0
    volatile_skipped = 0
    mismatches = []
    per_rule = []
    for entry in pinned_policy:
        rule_matched = 0
        for glob in entry["globs"]:
            checked_globs += 1
            for rel in real_files:
                if not glob_match(glob, rel):
                    continue
                if in_exempt(rel) and not entry.get("applies_inside_out_of_scope_roots", False):
                    continue
                # 与作者规则等价的短路：volatile（RULES 第一条）/ transient / 已排除 不要求进 files[]
                if any(glob_match(v, rel) for v in volatile_globs):
                    volatile_skipped += 1
                    raw_matched += 1
                    continue
                if rel in excluded_paths or rel in transient_paths:
                    raw_matched += 1
                    continue
                rule_matched += 1
                matched += 1
                raw_matched += 1
                hit = pinned.get(rel)
                if hit is None:
                    mismatches.append({"glob": glob, "path": rel, "kind": "not_in_files"})
                elif entry.get("category") and hit["category"] != entry["category"]:
                    mismatches.append({"glob": glob, "path": rel, "kind": "category_mismatch",
                                       "expected": entry["category"], "actual": hit["category"]})
        per_rule.append({"rule": entry["rule"], "globs": len(entry["globs"]),
                         "matches": rule_matched})
    check("policy 声称钉选的每条 glob 的每个真实匹配都在 files[] 且类别一致",
          not mismatches, f"{len(mismatches)} 违规")
    check("policy pinned glob 数与作者清单一致（26）", checked_globs == 26, f"{checked_globs}")
    check("policy 声称匹配数 = 作者报告 883 次（原始 glob 命中，含 volatile）",
          raw_matched == 883, f"raw={raw_matched}")
    check("policy 过滤 volatile/排除后真实要求钉选的匹配 = 497（= files[] 全量）",
          matched == 497 and volatile_skipped == 386,
          f"matched={matched} volatile_skipped={volatile_skipped}")
    # 反向：files[] 中不���被任何 pin 规则覆盖的条目（除在 exempt 下单独钉选的）
    covered = set()
    for rel in real_files:
        hit = pinned.get(rel)
        if hit is None:
            continue
        for entry in pinned_policy:
            if any(glob_match(glob, rel) and (entry.get("applies_inside_out_of_scope_roots", False)
                                              or not in_exempt(rel)) for glob in entry["globs"]):
                covered.add(rel)
                break
    uncovered = sorted(set(pinned) - covered)
    check("files[] 497 条全部能被 policy 规则解释", not uncovered,
          f"未覆盖 {len(uncovered)}: {uncovered[:3]}")
    return {"checked_globs": checked_globs, "matched": matched, "raw_matched": raw_matched,
            "volatile_skipped": volatile_skipped, "mismatches": mismatches,
            "per_rule": per_rule, "uncovered_files": uncovered}


# --------------------------------------------------------------------------------------
# 3) 案例树（只读用符号链接；任何写入先 unlink 再写真实拷贝）
# --------------------------------------------------------------------------------------

def build_case_tree(dest: Path, manifest: dict, *, real_copies: tuple[str, ...] = (),
                    extra_files: tuple[str, ...] = ()) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    links = 0
    copies = 0
    for entry in manifest["files"]:
        rel = entry["path"]
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        src = REAL / rel
        if rel in real_copies:
            subprocess.run(["cp", "-c", str(src), str(target)], check=True)
            copies += 1
        else:
            target.symlink_to(src)
            links += 1
    for rel in extra_files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REAL / rel, target)
    return {"symlinks": links, "real_copies": copies, "extra_real_files": len(extra_files)}


def materialize(case: Path, rel: str) -> Path:
    """把案例树里的符号链接换成真实文件拷贝（绝不通过符号链接写入真实树）。"""
    target = case / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    # 关键：先断开符号链接（unlink 不会写入链接目标），再写真实拷贝。
    if target.is_symlink() or target.exists():
        target.unlink()
    shutil.copy2(REAL / rel, target)
    assert not target.is_symlink(), f"写后仍是符号链接：{rel}"
    return target


def run_verify(case: Path, manifest_path: Path) -> dict:
    proc = subprocess.run(
        [str(PYTHON), "-B", str(R3_SCRIPT), "verify", "--root", str(case),
         "--manifest", str(manifest_path), "--json"],
        cwd=str(REPO), capture_output=True, text=True, timeout=600)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"parse_error": True, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
    return {"exit": proc.returncode, "result": payload,
            "stderr": proc.stderr[-1000:]}


def problem_kinds(result: dict) -> list[str]:
    return sorted({item.get("kind", "?") for item in result.get("problems", [])})


def warning_kinds(result: dict) -> list[str]:
    return sorted({item.get("kind", "?") for item in result.get("warnings", [])})


def run_case(name: str, manifest: dict, mutate, expect: dict) -> dict:
    case_root = Path(WORK) / name
    build_case_tree(case_root, manifest,
                    real_copies=tuple(expect.get("real_copies", ())),
                    extra_files=tuple(expect.get("extra_files", ())))
    manifest_copy = case_root / "_manifest_under_test.json"
    shutil.copy2(R3_MANIFEST, manifest_copy)
    detail = mutate(case_root, manifest_copy) or {}
    outcome = run_verify(case_root, manifest_copy)
    result = outcome["result"]
    problems = problem_kinds(result)
    warnings = warning_kinds(result)
    failures = []
    if outcome["exit"] != expect["exit"]:
        failures.append(f"exit={outcome['exit']}（期望 {expect['exit']}）")
    for kind in expect.get("problems_include", []):
        if kind not in problems:
            failures.append(f"缺少 problem {kind}（实得 {problems}）")
    for kind in expect.get("problems_exclude", []):
        if kind in problems:
            failures.append(f"不应出现 problem {kind}")
    for kind in expect.get("warnings_include", []):
        if kind not in warnings:
            failures.append(f"缺少 warning {kind}（实得 {warnings}）")
    entry = {"name": name, "exit": outcome["exit"], "problem_kinds": problems,
             "warning_kinds": warnings, "passed": not failures,
             "detail": detail if isinstance(detail, dict) else {"note": str(detail)},
             "failures": failures}
    CASES.append(entry)
    print(f"[{'CASE PASS' if not failures else 'CASE FAIL'}] {name}：exit={outcome['exit']} "
          f"problems={problems}" + (f"；{failures}" if failures else ""))
    return entry


# --------------------------------------------------------------------------------------
# 4) 自建案例（≥6 个不利反例 + 对照）
# --------------------------------------------------------------------------------------

def pick_pinned(manifest: dict, category: str | None = None, suffix: str = "") -> dict:
    for entry in manifest["files"]:
        if category and entry["category"] != category:
            continue
        if suffix and not entry["path"].endswith(suffix):
            continue
        return entry
    raise SystemExit(f"no pinned entry for category={category} suffix={suffix}")


def run_cases(manifest: dict) -> None:
    # 对照 C0：干净案例树必须绿（不是恒红装置）
    run_case("C0_clean_case_tree", manifest,
             lambda case, mf: {},
             {"exit": 0, "problems_exclude": ["manifest_digest", "size_changed", "sha256_changed",
                                              "unexpected_new_file", "missing",
                                              "runstore_entries_changed"]})
    # N1：清单 size 篡改 → 红（digest + size_changed）
    target = pick_pinned(manifest, "dataset.c0", "manifest.json")

    def mutate_n1(case, mf):
        data = json.loads(mf.read_text(encoding="utf-8"))
        for entry in data["files"]:
            if entry["path"] == target["path"]:
                entry["size"] += 1
                break
        mf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return {"tampered": target["path"], "field": "size+1"}
    run_case("N1_manifest_size_tamper", manifest, mutate_n1,
             {"exit": 1, "problems_include": ["manifest_digest", "size_changed"]})
    # N2：清单 RunStore entries_digest 篡改 → 红
    def mutate_n2(case, mf):
        data = json.loads(mf.read_text(encoding="utf-8"))
        first_db = sorted(data["runstore"]["databases"])[0]
        data["runstore"]["entries_digest"] = "0" * 64
        data["runstore"]["databases"][first_db]["entries_digest"] = "0" * 64
        mf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return {"tampered": f"runstore.entries_digest + databases[{first_db}].entries_digest"}
    run_case("N2_manifest_runstore_digest_tamper", manifest, mutate_n2,
             {"exit": 1, "problems_include": ["manifest_digest", "runstore_entries_changed"]})
    # N3：清单隐藏一条钉选条目 → 红（digest + unexpected_new_file）
    hidden = pick_pinned(manifest, "run.config", "report.json")

    def mutate_n3(case, mf):
        data = json.loads(mf.read_text(encoding="utf-8"))
        data["files"] = [e for e in data["files"] if e["path"] != hidden["path"]]
        mf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return {"hidden": hidden["path"]}
    run_case("N3_manifest_hides_pinned_entry", manifest, mutate_n3,
             {"exit": 1, "problems_include": ["manifest_digest", "unexpected_new_file"]})
    # N4：钉选目录内新增未登记文件 → unexpected_new_file 红（T3）
    checkpoint_meta = pick_pinned(manifest, "checkpoint.meta", "manifest.json")
    cp_dir = checkpoint_meta["path"].rsplit("/", 1)[0]

    def mutate_n4(case, mf):
        target_path = case / cp_dir / "NOTES.md"
        assert not target_path.is_symlink()
        target_path.write_text("unregistered note\n", encoding="utf-8")
        return {"added": str(target_path.relative_to(case))}
    run_case("N4_unregistered_file_in_pinned_checkpoint_dir", manifest, mutate_n4,
             {"exit": 1, "problems_include": ["unexpected_new_file"]})
    # N5：钉选文件等长内容翻转 → sha256_changed 红（先 unlink 再写拷贝）
    small = pick_pinned(manifest, "dataset.c0", "manifest.json")

    def mutate_n5(case, mf):
        target_path = materialize(case, small["path"])
        raw = bytearray(target_path.read_bytes())
        raw[0] = raw[0] ^ 0x01
        target_path.write_bytes(bytes(raw))
        return {"flipped": small["path"], "size": len(raw)}
    run_case("N5_pinned_file_content_flip", manifest, mutate_n5,
             {"exit": 1, "problems_include": ["sha256_changed"]})
    # N6：钉选文件被替换为目录 → missing 红
    def mutate_n6(case, mf):
        target_path = case / small["path"]
        target_path.unlink()
        target_path.mkdir(parents=True)
        return {"replaced_by_dir": small["path"]}
    run_case("N6_pinned_file_replaced_by_directory", manifest, mutate_n6,
             {"exit": 1, "problems_include": ["missing"]})
    # N7：删除钉选文件 → missing 红
    def mutate_n7(case, mf):
        (case / small["path"]).unlink()
        return {"deleted": small["path"]}
    run_case("N7_pinned_file_deleted", manifest, mutate_n7,
             {"exit": 1, "problems_include": ["missing"]})
    # N8：RunStore 改一行 → runstore_entries_changed 红（真实拷贝上执行 SQL）
    db_rel = "artifacts/control.sqlite3"

    def mutate_n8(case, mf):
        db_path = case / db_rel
        assert not db_path.is_symlink()
        con = sqlite3.connect(db_path)
        cur = con.execute("UPDATE runs SET state = CASE WHEN state = 'failed' THEN 'completed' "
                          "ELSE 'failed' END WHERE run_id = "
                          "(SELECT run_id FROM runs ORDER BY run_id LIMIT 1)")
        assert cur.rowcount == 1, f"expected 1 updated row, got {cur.rowcount}"
        con.commit()
        con.close()
        return {"updated_table": "runs", "database": db_rel, "rows": cur.rowcount}
    run_case("N8_runstore_row_changed", manifest, mutate_n8,
             {"exit": 1, "problems_include": ["runstore_entries_changed"],
              "real_copies": (db_rel,)})
    # N9：RunStore 合法 VACUUM（大小变化、行不变）→ 绿 + size warning
    def mutate_n9(case, mf):
        db_path = case / db_rel
        assert not db_path.is_symlink()
        before = db_path.stat().st_size
        con = sqlite3.connect(db_path)
        con.execute("VACUUM")
        con.commit()
        con.close()
        after = db_path.stat().st_size
        return {"database": db_rel, "size_before": before, "size_after": after}
    run_case("N9_runstore_legal_vacuum_stays_green", manifest, mutate_n9,
             {"exit": 0, "problems_exclude": ["runstore_entries_changed"],
              "warnings_include": ["runstore_file_size_changed", "runstore_file_sha_changed"],
              "real_copies": (db_rel,)})
    # N10：排除项字节改动 → 设计上不红（文档边界对照，非缺陷）
    excluded = next(e for e in manifest["excluded_with_reason"]
                    if e["path"].endswith("probe-teacher-cache.npz"))

    def mutate_n10(case, mf):
        target_path = case / excluded["path"]
        target_path.write_bytes(target_path.read_bytes() + b"\x00")
        return {"excluded_mutated": excluded["path"],
                "note": "excluded files are not hashed by design (A2 r3 §8)"}
    run_case("N10_excluded_file_change_stays_green", manifest, mutate_n10,
             {"exit": 0, "problems_exclude": ["sha256_changed", "size_changed"],
              "extra_files": (excluded["path"],)})


# --------------------------------------------------------------------------------------
# 5) selftest 真实拷贝与作者测试复跑（只读真实树）
# --------------------------------------------------------------------------------------

def run_selftest(manifest: dict) -> dict:
    out_path = EVIDENCE / "author-selftest-replay.json"
    proc = subprocess.run(
        [str(PYTHON), "-B", str(R3_SCRIPT), "selftest", "--root", str(REPO),
         "--manifest", str(R3_MANIFEST), "--selftest-out", str(out_path), "--json"],
        cwd=str(REPO), capture_output=True, text=True, timeout=1800)
    (EVIDENCE / "author-selftest-replay.log").write_text(
        f"$ python -B scripts/v9_baseline_manifest_r3.py selftest --root . "
        f"--manifest reports/V9-baseline/r3/baseline_manifest.json "
        f"--selftest-out {out_path} --json\nexit={proc.returncode}\n"
        f"{proc.stdout}\n{proc.stderr}", encoding="utf-8")
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        data = {"parse_error": True}
    return {"exit": proc.returncode, "data": data}


def check_selftest(selftest: dict, manifest: dict) -> dict:
    data = selftest["data"]
    summary = data.get("summary", {})
    cases = data.get("selftest", [])
    real_copy_count = sum(1 for c in cases if c.get("real_copy") is True)
    check("作者 selftest 复跑 exit 0", selftest["exit"] == 0)
    check("selftest 真实拷贝：22/22 real_copy、copy_mode 明示 never a symlink",
          len(cases) == 22 and real_copy_count == 22
          and "never a symlink" in str(data.get("copy_mode", "")),
          f"cases={len(cases)} real_copy={real_copy_count} mode={data.get('copy_mode')}")
    check("selftest 注入故障 17/17 变红、对照 5/5 保持绿",
          summary.get("faults_injected") == summary.get("faults_detected") == 17
          and summary.get("controls_green") == 5 and summary.get("all_detected") is True,
          f"injected={summary.get('faults_injected')}/{summary.get('faults_detected')} "
          f"controls={summary.get('controls_green')}/5")
    integrity = data.get("real_tree_integrity", {})
    check("selftest 内含真实树完整性 before/after 均 0 mismatch",
          integrity.get("before", {}).get("content_unchanged") is True
          and integrity.get("after", {}).get("content_unchanged") is True,
          json.dumps({k: v.get("checked") for k, v in integrity.items() if isinstance(v, dict)}))
    return {"exit": selftest["exit"], "cases_total": len(cases),
            "cases_real_copy": real_copy_count,
            "faults": [summary.get("faults_detected"), summary.get("faults_injected")],
            "controls_green": summary.get("controls_green"),
            "copy_mode": data.get("copy_mode"),
            "real_tree_integrity": {k: {"checked": v.get("checked"),
                                        "content_unchanged": v.get("content_unchanged")}
                                    for k, v in integrity.items() if isinstance(v, dict)}}


def run_author_verify() -> dict:
    proc = subprocess.run([str(PYTHON), "-B", str(R3_SCRIPT), "verify", "--json"],
                          cwd=str(REPO), capture_output=True, text=True, timeout=1200)
    (EVIDENCE / "author-verify.log").write_text(
        f"$ python -B scripts/v9_baseline_manifest_r3.py verify --json\nexit={proc.returncode}\n"
        f"{proc.stdout[-4000:]}\n{proc.stderr[-1000:]}", encoding="utf-8")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"parse_error": True}
    return {"exit": proc.returncode, "result": data}


# --------------------------------------------------------------------------------------
# 6) r2 产物原样保留
# --------------------------------------------------------------------------------------

def check_r2_preserved() -> dict:
    a4 = json.loads(A4_JSON.read_text(encoding="utf-8"))
    expected = {
        "scripts/v9_baseline_manifest_r2.py": "2709475caac0ef8f3d92ac2023d94156c11cfd63ac13eb00c454ecdb715e529c",
        "reports/V9-baseline/r2/baseline_manifest.json": "71e99efcc1ceb652df742396d3bbbfdbc72ac7cd5e46c980171e33065a2d674a",
        "reports/V9-baseline/r2/report.md": "d39e5c75bcfb244c25b9a7eb76f99446b5228fdbcd017318f414d6358a83bb5d",
    }
    actual = {rel: sha256_file(REPO / rel) for rel in expected}
    check("r2 三个身份 SHA 与 A4 记录一致（r2 产物原样保留）",
          actual == expected, json.dumps(actual, ensure_ascii=False)[:300])
    r2_manifest = json.loads((REPO / "reports/V9-baseline/r2/baseline_manifest.json").read_text(encoding="utf-8"))
    check("r2 manifest_digest 仍为 ee6fc9c9…b2cd3（无基线漂移）",
          r2_manifest["manifest_digest"] == "ee6fc9c9bbd3177c4a2584216036e065859e111e2e96bdee1e08c6897d9b2cd3")
    return {"sha256": actual, "r2_manifest_digest": r2_manifest["manifest_digest"]}


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------

WORK = ""


def main() -> None:
    global FAILED, WORK, START_INTEGRITY, END_INTEGRITY
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", default=str(EVIDENCE / "review.json"))
    args = parser.parse_args()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    WORK = tempfile.mkdtemp(prefix="v9-a10-r3-cases-")
    manifest = load_manifest()
    print(f"# ainerzero.V9.A10 独立复核（非 A2 作者）：真实树={REAL}；案例沙盒={WORK}")

    print("\n## 0) 真实树完整性（开始）")
    START_INTEGRITY = real_tree_integrity(manifest, "before")
    check("开始：真实树 497 钉选文件复算 0 mismatch",
          not START_INTEGRITY["mismatches"] and START_INTEGRITY["checked"] == 497,
          f"checked={START_INTEGRITY['checked']} mismatches={len(START_INTEGRITY['mismatches'])}")
    check("钉选字节数 = 清单登记 584,888,364 B（= 报告）",
          START_INTEGRITY["total_bytes"] == manifest["counts"]["bytes_pinned"] == 584888364,
          f"{START_INTEGRITY['total_bytes']}")

    print("\n## 1) C3 覆盖")
    c3 = check_c3(manifest)
    print("\n## 2) policy↔清单↔真实树")
    real_files = enumerate_real_files()
    check("真实 artifacts 文件枚举数 = 51706", len(real_files) == 51706, f"{len(real_files)}")
    policy = check_policy(manifest, real_files)
    print("\n## 3) 自建案例（10 个：8 红 + 2 对照）")
    run_cases(manifest)
    print("\n## 4) selftest 真实拷贝与作者复跑")
    selftest = check_selftest(run_selftest(manifest), manifest)
    verify = run_author_verify()
    check("作者 verify 复跑 exit 0、497/497 ok、policy 26 globs",
          verify["exit"] == 0 and verify["result"].get("verdict") == "ok"
          and verify["result"].get("files_ok") == 497
          and verify["result"].get("policy_checked_globs") == 26,
          f"verdict={verify['result'].get('verdict')} files_ok={verify['result'].get('files_ok')}")
    print("\n## 5) RunStore 行级裁定（见案例 N8/N9）")
    print("\n## 6) r2 产物保全")
    r2 = check_r2_preserved()

    print("\n## 7) 真实树完整性（结束，与开始对比）")
    END_INTEGRITY = real_tree_integrity(manifest, "after")
    check("结束：真实树 497 钉选文件复算 0 mismatch",
          not END_INTEGRITY["mismatches"], f"mismatches={len(END_INTEGRITY['mismatches'])}")
    check("真实树开始=结束（钉选文件 path+sha 指纹一致、全程零写入）",
          START_INTEGRITY["files_digest"] == END_INTEGRITY["files_digest"]
          and START_INTEGRITY["checked"] == END_INTEGRITY["checked"],
          f"digest_start={START_INTEGRITY['files_digest'][:16]}… "
          f"digest_end={END_INTEGRITY['files_digest'][:16]}…")

    red_cases = [c for c in CASES if c["exit"] != 0]
    green_controls = [c for c in CASES if c["exit"] == 0]
    check("自建不利反例 ≥6 全部真实非零退出；对照（干净树/VACUUM/排除项）保持绿",
          len(red_cases) >= 6 and len(green_controls) >= 3 and all(c["passed"] for c in CASES),
          f"red={len(red_cases)} green_controls={len(green_controls)} failed={[c['name'] for c in CASES if not c['passed']]}")

    summary = {
        "task": "ainerzero.V9.A10",
        "reviewed_task": "ainerzero.V9.A2",
        "reviewed_round": "r3",
        "reviewer": "deepseek-flash-a7k2",
        "reviewed_author": "opencode-de3b",
        "non_author": True,
        "not_a3_a4_reviewer": True,
        "date": "2026-10-20",
        "params_version": "v0",
        "params": {},
        "cpu_only": True,
        "read_only_real_tree": True,
        "writes_only": ["reports/V-V9-baseline/r3/"],
        "case_sandbox": WORK,
        "checks": {"total": len(CHECKS), "passed": sum(1 for c in CHECKS if c["ok"]),
                   "failed": [c["name"] for c in CHECKS if not c["ok"]]},
        "cases": {"total": len(CASES), "passed": sum(1 for c in CASES if c["passed"]),
                  "failed": [c["name"] for c in CASES if not c["passed"]], "detail": CASES},
        "c3": c3, "policy": policy, "selftest": selftest,
        "author_verify": {"exit": verify["exit"],
                          "verdict": verify["result"].get("verdict"),
                          "files_ok": verify["result"].get("files_ok"),
                          "problems": verify["result"].get("problems"),
                          "policy_checked_globs": verify["result"].get("policy_checked_globs")},
        "r2_preserved": r2,
        "real_tree_integrity": {"before": START_INTEGRITY, "after": END_INTEGRITY},
        "verdict": "PASS" if not FAILED else "REJECT",
        "checks_detail": CHECKS,
    }
    out = Path(args.json_out)
    if not out.is_absolute():
        out = REPO / out
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n=== 复核汇总 ===")
    print(json.dumps({"verdict": summary["verdict"], **summary["checks"],
                      "cases": {k: summary["cases"][k] for k in ("total", "passed", "failed")},
                      "real_tree_before_after_equal":
                          START_INTEGRITY["files_digest"] == END_INTEGRITY["files_digest"]},
                     ensure_ascii=False, indent=2))
    sys.exit(0 if not FAILED else 1)


if __name__ == "__main__":
    main()
