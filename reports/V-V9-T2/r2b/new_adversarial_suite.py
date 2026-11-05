#!/usr/bin/env python3
"""New adverse test suite for ainerzero.V9.T2 r2 verification.

Implements 7 new adverse test cases (N01-N07) beyond T3's C01-C12:
- N01: Unknown context schema version rejected
- N02: Missing admission_bindings entry fails closed
- N03: Corrupted output.bin on disk detected and marked broken
- N04: In-process handle invalidation after release_teacher()
- N05: Missing RSS probe fails closed with UnloadIncompleteError
- N06: Malformed entry schema rejected before disk write (zero disk artifacts)
- N07: World mode rejects feature teacher

Each case implements:
1) Adverse test & main assertion (attack rejected)
2) Control assertion (valid baseline passes)
3) Poison assertion (deliberately broken guard causes control to turn RED / exit 1)
"""

import argparse
import contextlib
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(ROOT / "src"))

import ainerzero.v9.teachers.cache as cm
import ainerzero.v9.teachers.mode as mm
from ainerzero.v9.teachers.fake import FakeTeacher

BASE = ROOT / "contracts/v9/examples/teacher_cache_v2"


def load_fixtures():
    store = json.loads((BASE / "valid/valid_store.json").read_text())
    ctx = json.loads((BASE / "contexts/baseline.json").read_text())
    pins = json.loads((BASE / "expected-context-identities.json").read_text())["pins"]["valid_store"]
    sample_entry = [r for r in store if r.get("record_type") == "teacher_entry" and r["entry_id"].startswith("3d7b")][0]
    sample_blob = [r for r in store if r.get("record_type") == "teacher_blob" and r["cache_key"] == sample_entry["cache_key"]][0]
    return store, ctx, pins, sample_blob, sample_entry


# --------------------------------------------------------------------------- N01
def case_n01():
    """N01: 未知 context schema_version 准入检测：必须被拒绝。"""
    store, ctx, pins, _, sample_entry = load_fixtures()
    bad_ctx = copy.deepcopy(ctx)
    bad_ctx["schema_version"] = "az.v9.teacher_cache.v99_invalid"
    probs = cm.store_problems(store, bad_ctx, pins, disabled=())
    te = cm.train_eligible(sample_entry, store, bad_ctx, pins, disabled=())
    metrics = {"problems": probs, "train_eligible": te}
    violations = []
    if te is not False:
        violations.append(f"未知 context schema_version 仍被判 train_eligible={te}")
    if not any("context" in p or "schema" in p for p in probs):
        violations.append(f"store_problems 未能抓到未知 context schema_version: {probs}")
    return metrics, violations


def ctrl_n01():
    """对照：非空 approval_registry 必须被 store_problems 抓到。"""
    store, ctx, pins, _, _ = load_fixtures()
    bad_ctx = copy.deepcopy(ctx)
    bad_ctx["approval_registry"]["entries"] = [{"entry_id": "bad"}]
    probs = cm.store_problems(store, bad_ctx, cm.sha(bad_ctx), disabled=())
    violations = []
    if not any(p in ("approval_registry_not_current_empty", "trusted_context_schema") for p in probs):
        violations.append(f"对照失败：非空 approval_registry 未能被检测出，实际: {probs}")
    return violations


# --------------------------------------------------------------------------- N02
def case_n02():
    """N02: v2.1 绑定缺失时必须 fail-closed（不信任盘上许可）。"""
    store, ctx, _, sample_blob, sample_entry = load_fixtures()
    ctx_bound = copy.deepcopy(ctx)
    # Register binding for a DIFFERENT entry
    ctx_bound["admission_bindings"] = [
        {
            "entry_id": "f" * 64,
            "cache_key": sample_blob["cache_key"],
            "entry_license": sample_entry["license"],
            "teacher_license": sample_blob["teacher_license"],
            "reproducibility": sample_blob["reproducibility"],
        }
    ]
    exp = cm.sha(ctx_bound)
    te = cm.train_eligible(sample_entry, store, ctx_bound, exp, disabled=())
    metrics = {"entry_id": sample_entry["entry_id"], "train_eligible": te}
    violations = []
    if te is not False:
        violations.append(f"未登记在 admission_bindings 中的条目仍获得准入: train_eligible={te}")
    return metrics, violations


def ctrl_n02():
    """对照：正确登记在 admission_bindings 且均为 True 的条目必须获得准入。"""
    store, ctx, _, sample_blob, sample_entry = load_fixtures()
    ctx_bound = copy.deepcopy(ctx)
    ctx_bound["admission_bindings"] = [
        {
            "entry_id": sample_entry["entry_id"],
            "cache_key": sample_blob["cache_key"],
            "entry_license": sample_entry["license"],
            "teacher_license": sample_blob["teacher_license"],
            "reproducibility": sample_blob["reproducibility"],
        }
    ]
    exp = cm.sha(ctx_bound)
    records = [sample_blob, sample_entry]
    te = cm.train_eligible(sample_entry, records, ctx_bound, exp, disabled=())
    violations = []
    if te is not True:
        violations.append(f"对照失败：正例绑定应该准入，实际 train_eligible={te}")
    return violations


# --------------------------------------------------------------------------- N03
def case_n03():
    """N03: 篡改 output.bin 字节内容必须被 read_blob 抓出并置 broken。"""
    _, _, _, sample_blob, _ = load_fixtures()
    ck = sample_blob["cache_key"]
    km = sample_blob["key_material"]
    with tempfile.TemporaryDirectory() as td:
        cm.set_cache_root(Path(td))
        cm.write_blob(
            output_data=b"ORIGINAL_BYTES_DATA",
            cache_key=ck,
            key_material=km,
            teacher_license=sample_blob["teacher_license"],
            reproducibility=sample_blob["reproducibility"],
        )
        out_path = Path(td) / "blobs" / ck[:2] / ck / "output.bin"
        out_path.write_bytes(b"TAMPERED_BYTES_DATA")
        caught = False
        exc = None
        try:
            cm.read_blob(ck)
        except cm.HashMismatchError as ex:
            caught = True
            exc = str(ex)
        blob_rec = json.loads((Path(td) / "blobs" / ck[:2] / ck / "blob.json").read_text())
        metrics = {"caught": caught, "exc": exc, "broken": blob_rec.get("broken"), "reason": blob_rec.get("broken_reason")}
        violations = []
        if not caught or blob_rec.get("broken") is not True:
            violations.append(f"篡改 output.bin 未能被捕获或未置 broken: caught={caught}, broken={blob_rec.get('broken')}")
    return metrics, violations


def ctrl_n03():
    """对照：未被篡改的 output.bin 读取正常且 broken 为 False/None。"""
    _, _, _, sample_blob, _ = load_fixtures()
    ck = sample_blob["cache_key"]
    km = sample_blob["key_material"]
    with tempfile.TemporaryDirectory() as td:
        cm.set_cache_root(Path(td))
        cm.write_blob(
            output_data=b"ORIGINAL_BYTES_DATA",
            cache_key=ck,
            key_material=km,
            teacher_license=sample_blob["teacher_license"],
            reproducibility=sample_blob["reproducibility"],
        )
        rec = cm.read_blob(ck)
        violations = []
        if rec.get("broken") is True:
            violations.append("对照失败：未被篡改的 blob 被误标 broken")
    return violations


# --------------------------------------------------------------------------- N04
def case_n04():
    """N04: FakeTeacher.extract() 在 release_teacher() 后必须抛 ModeViolationError。"""
    mm.ModeGuard.reset()
    mm.ModeGuard.set_mode("teacher")
    t = FakeTeacher("da3-small", "geometry")
    mm.ModeGuard.release_teacher()
    caught = False
    exc = None
    try:
        t.extract("dummy_key", [0])
    except mm.ModeViolationError as ex:
        caught = True
        exc = str(ex)
    mm.ModeGuard.reset()
    metrics = {"caught": caught, "exc": exc}
    violations = []
    if not caught:
        violations.append("release_teacher() 后 extract() 未能抛出 ModeViolationError")
    return metrics, violations


def ctrl_n04():
    """对照：未 release 状态下 extract 正常产出特征。"""
    mm.ModeGuard.reset()
    mm.ModeGuard.set_mode("teacher")
    t = FakeTeacher("da3-small", "geometry", dim=4)
    out = t.extract("dummy_key", [0])
    mm.ModeGuard.reset()
    violations = []
    if len(out) != 16:
        violations.append(f"对照失败：有效状态下 extract 产出长度应为 16，实际 {len(out)}")
    return violations


# --------------------------------------------------------------------------- N05
def case_n05():
    """N05: 探针缺失下切换模式必须 fail-closed（UnloadIncompleteError）。"""
    mm.ModeGuard.reset()
    mm.ModeGuard.set_mode("teacher")
    mm.ModeGuard.check_teacher_load("t1", "feature")
    mm.ModeGuard.release_teacher()
    mm.ModeGuard.set_rss_probe(lambda: None)  # Probe unavailable
    caught = False
    exc = None
    try:
        mm.ModeGuard.set_mode("train")
    except mm.UnloadIncompleteError as ex:
        caught = True
        exc = str(ex)
    mm.ModeGuard.reset()
    metrics = {"caught": caught, "exc": exc}
    violations = []
    if not caught:
        violations.append("探针不可用时切模式未能 fail-closed 抛出 UnloadIncompleteError")
    return metrics, violations


def ctrl_n05():
    """对照：正常回落的模式切换应该成功。"""
    mm.ModeGuard.reset()
    mm.ModeGuard.set_rss_probe(lambda: 1000)
    mm.ModeGuard.set_mode("teacher")
    mm.ModeGuard.check_teacher_load("t1", "feature")
    mm.ModeGuard.release_teacher()
    mm.ModeGuard.set_rss_probe(lambda: 900)  # Memory dropped below baseline
    try:
        mm.ModeGuard.set_mode("train")
        ok = True
    except Exception:
        ok = False
    mm.ModeGuard.reset()
    violations = []
    if not ok:
        violations.append("对照失败：正常回落的模式切换应该成功")
    return violations


# --------------------------------------------------------------------------- N06
def case_n06():
    """N06: 畸形 entry schema 在写盘前被拒且零磁盘残留。"""
    _, _, _, sample_blob, sample_entry = load_fixtures()
    ck = sample_blob["cache_key"]
    km = sample_blob["key_material"]
    with tempfile.TemporaryDirectory() as td:
        cm.set_cache_root(Path(td))
        cm.write_blob(
            output_data=b"out",
            cache_key=ck,
            key_material=km,
            teacher_license=sample_blob["teacher_license"],
            reproducibility=sample_blob["reproducibility"],
        )
        bad_entry = copy.deepcopy(sample_entry)
        del bad_entry["provenance"]["upstream"]["system"]  # Missing required field
        caught = False
        exc = None
        try:
            cm.write_entry(bad_entry)
        except cm.SchemaValidationError as ex:
            caught = True
            exc = str(ex)
        entries_dir = Path(td) / "entries"
        leftover = list(entries_dir.rglob("*.json")) if entries_dir.exists() else []
        metrics = {"caught": caught, "exc": exc, "leftover_files": len(leftover)}
        violations = []
        if not caught:
            violations.append("畸形 entry 写入未被 SchemaValidationError 拒绝")
        if len(leftover) > 0:
            violations.append(f"写盘前拒绝后盘上残留了文件: {leftover}")
    return metrics, violations


def ctrl_n06():
    """对照：合法 entry 正常写入并可读出。"""
    _, _, _, sample_blob, sample_entry = load_fixtures()
    ck = sample_blob["cache_key"]
    km = sample_blob["key_material"]
    with tempfile.TemporaryDirectory() as td:
        cm.set_cache_root(Path(td))
        cm.write_blob(
            output_data=b"out",
            cache_key=ck,
            key_material=km,
            teacher_license=sample_blob["teacher_license"],
            reproducibility=sample_blob["reproducibility"],
        )
        cm.write_entry(sample_entry)
        rec = cm.read_entry(sample_entry["entry_id"])
        violations = []
        if rec["entry_id"] != sample_entry["entry_id"]:
            violations.append("对照失败：正例 entry 写入与读出失败")
    return violations


# --------------------------------------------------------------------------- N07
def case_n07():
    """N07: World 模式下试图加载 feature 教师必须被拒。"""
    mm.ModeGuard.reset()
    mm.ModeGuard.set_mode("world")
    caught = False
    exc = None
    try:
        mm.ModeGuard.check_teacher_load("vjepa", "feature")
    except mm.ModeViolationError as ex:
        caught = True
        exc = str(ex)
    mm.ModeGuard.reset()
    metrics = {"caught": caught, "exc": exc}
    violations = []
    if not caught:
        violations.append("World 模式下加载 feature 教师未能被 ModeViolationError 拒绝")
    return metrics, violations


def ctrl_n07():
    """对照：World 模式下加载 geometry 教师应该成功。"""
    mm.ModeGuard.reset()
    mm.ModeGuard.set_mode("world")
    try:
        mm.ModeGuard.check_teacher_load("da3-small", "geometry")
        ok = True
    except Exception:
        ok = False
    mm.ModeGuard.reset()
    violations = []
    if not ok:
        violations.append("对照失败：World 模式加载 geometry 教师应该成功")
    return violations


# --------------------------------------------------------------------------- Poisons
@contextlib.contextmanager
def poison_context(name: str):
    if name == "p_n01":
        orig = cm.store_problems
        cm.store_problems = lambda *a, **k: []
        try:
            yield
        finally:
            cm.store_problems = orig
    elif name == "p_n02":
        orig = cm.train_eligible
        cm.train_eligible = lambda *a, **k: False  # Deliberately fails control
        try:
            yield
        finally:
            cm.train_eligible = orig
    elif name == "p_n03":
        orig = cm.TeacherCache.read_blob
        def broken_read(self, ck):
            res = orig(self, ck)
            res["broken"] = True
            return res
        cm.TeacherCache.read_blob = broken_read
        try:
            yield
        finally:
            cm.TeacherCache.read_blob = orig
    elif name == "p_n04":
        orig = FakeTeacher.extract
        FakeTeacher.extract = lambda *a, **k: b""  # Empty output, breaking control length 16
        try:
            yield
        finally:
            FakeTeacher.extract = orig
    elif name == "p_n05":
        orig = mm.ModeGuard._assert_unload_complete
        def broken_assert():
            raise mm.UnloadIncompleteError("Simulated break in unload check")
        mm.ModeGuard._assert_unload_complete = classmethod(lambda cls: broken_assert())
        try:
            yield
        finally:
            mm.ModeGuard._assert_unload_complete = orig
    elif name == "p_n06":
        orig = cm.TeacherCache.read_entry
        cm.TeacherCache.read_entry = lambda *a, **k: {"entry_id": "wrong_id"}
        try:
            yield
        finally:
            cm.TeacherCache.read_entry = orig
    elif name == "p_n07":
        orig = mm.ModeGuard.check_teacher_load
        def broken_load(cls, *a, **k):
            raise mm.ModeViolationError("Forced break for control")
        mm.ModeGuard.check_teacher_load = classmethod(broken_load)
        try:
            yield
        finally:
            mm.ModeGuard.check_teacher_load = orig
    else:
        yield


NEW_CASES = {
    "N01": ("可信上下文", "未知 context schema_version 准入检测", case_n01, ctrl_n01, "p_n01"),
    "N02": ("可信上下文", "v2.1 绑定条目缺失 fail-closed 准入", case_n02, ctrl_n02, "p_n02"),
    "N03": ("缓存读路径", "output.bin 损坏被捕获并置 broken", case_n03, ctrl_n03, "p_n03"),
    "N04": ("模式守卫", "release_teacher 后句柄失效", case_n04, ctrl_n04, "p_n04"),
    "N05": ("模式守卫", "探针缺失下模式切换 fail-closed", case_n05, ctrl_n05, "p_n05"),
    "N06": ("写路径原子性", "畸形 schema 条目在写盘前被拒且零残留", case_n06, ctrl_n06, "p_n06"),
    "N07": ("跨模式互斥", "World 模式拒绝 feature 教师", case_n07, ctrl_n07, "p_n07"),
}


def run_one(cid: str, poison: bool) -> dict:
    theme, title, case_fn, ctrl_fn, p_name = NEW_CASES[cid]
    entry = {"case": cid, "theme": theme, "title": title, "poison": p_name, "mode": "poison" if poison else "normal"}
    if poison:
        with poison_context(p_name):
            ctrl_v = ctrl_fn()
        entry["control_violations"] = ctrl_v
        entry["poison_turned_red"] = bool(ctrl_v)
        entry["exit"] = 1 if ctrl_v else 0
    else:
        metrics, violations = case_fn()
        ctrl_v = ctrl_fn()
        entry["metrics"] = metrics
        entry["violations"] = violations
        entry["control_violations"] = ctrl_v
        entry["verdict"] = "PASS" if not violations else "FAIL(finding)"
        entry["exit"] = 1 if (violations or ctrl_v) else 0
    return entry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=sorted(NEW_CASES))
    parser.add_argument("--poison", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    if args.case:
        entry = run_one(args.case, args.poison)
        print("RESULT_JSON " + json.dumps(entry, ensure_ascii=False, default=str))
        return entry["exit"]

    summary = {
        "verifier_task": "ainerzero.V9.T20",
        "verified_task": "ainerzero.V9.T2",
        "normal": [],
        "poison": [],
    }

    print("=== Running New Adversarial Suite (Normal Mode) ===")
    for cid in sorted(NEW_CASES):
        cmd = [sys.executable, "-B", str(Path(__file__).resolve()), "--case", cid]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
        if line:
            rec = json.loads(line[len("RESULT_JSON "):])
        else:
            rec = {"case": cid, "error": proc.stderr, "exit": 2}
        summary["normal"].append(rec)
        print(f"[normal ] {cid} exit={rec.get('exit')} verdict={rec.get('verdict')}  {rec.get('title')}")

    print("=== Running New Adversarial Suite (Poison Mode) ===")
    for cid in sorted(NEW_CASES):
        cmd = [sys.executable, "-B", str(Path(__file__).resolve()), "--case", cid, "--poison"]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
        if line:
            rec = json.loads(line[len("RESULT_JSON "):])
        else:
            rec = {"case": cid, "error": proc.stderr, "exit": 2}
        summary["poison"].append(rec)
        tag = "RED" if rec.get("poison_turned_red") else "NOT-RED"
        print(f"[poison ] {cid} exit={rec.get('exit')} {tag}  {rec.get('title')}")

    findings = [r["case"] for r in summary["normal"] if r.get("violations")]
    ctrl_bad = [r["case"] for r in summary["normal"] if r.get("control_violations")]
    poison_not_red = [r["case"] for r in summary["poison"] if not r.get("poison_turned_red")]

    summary["findings_count"] = len(findings)
    summary["control_failures_count"] = len(ctrl_bad)
    summary["poison_not_red_count"] = len(poison_not_red)
    summary["all_controls_turn_red"] = len(poison_not_red) == 0
    summary["all_attacks_rejected"] = len(findings) == 0 and len(ctrl_bad) == 0
    summary["exit"] = 0 if (summary["all_controls_turn_red"] and summary["all_attacks_rejected"]) else 1

    out_file = args.json_out or (ROOT / "reports/V-V9-T2/r2b/new_adversarial_summary.json")
    out_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n")
    print(f"--- findings={len(findings)} control_failures={len(ctrl_bad)} poison_not_red={len(poison_not_red)} exit={summary['exit']}")
    return summary["exit"]


if __name__ == "__main__":
    sys.exit(main())
