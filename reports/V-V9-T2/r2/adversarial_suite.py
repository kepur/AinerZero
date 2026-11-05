#!/usr/bin/env python3
"""ainerzero.V9.T3 独立复核：对 ainerzero.V9.T2（教师缓存 cache.py + 运行模式守卫 mode.py）自写不利反例。

角色：verify（非作者）· 只读核对被验源码，只写 reports/V-V9-T2/ · 纯 CPU，不训练、不下载。

每个反例（case）三件套：
  1) 主断言：按 docs/v9/TEACHERS_AND_CACHE.md r3（§1.2/§1.4/§2.1/§2.2/§2.3/§2.4/§2.5/§6）
     构造真实的对抗输入，量出一个真实非零的差异量（discrepancy），断言守卫必须拒绝/报告；
  2) 对照断言（control）：同主题下当前实现**确实能**抓到的另一场景，证明本反例的检测器不是空转；
  3) 改坏对照（poison）：进程内把本反例依赖的那一处守卫刻意改坏（monkeypatch，不改被验源码），
     要求 control **必须变红**（即"故意改坏必须变红"）。

退出码（两种模式同一语义：1 = 红 / 有违反）：
  正常模式   `adversarial_suite.py --case Cxx`：exit 1 = 主断言被违反（不利发现）或 control 未被抓到；
  改坏模式   `adversarial_suite.py --case Cxx --poison`：exit 1 = control 真的变红（对照有效）；
             exit 0 = 没变红（说明本反例的断言可能空转，复核自身失败）。
  无 --case：逐个用子进程跑完全部反例并汇总，写 summary JSON。

不导入 MLX / torch / onnxruntime / coremltools，不联网，不修改 src/、tests/、reports/V9-T2/。
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import multiprocessing
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(ROOT / "src"))

import ainerzero.v9.teachers.cache as cache_mod  # noqa: E402
import ainerzero.v9.teachers.mode as mode_mod  # noqa: E402
from ainerzero.v9.teachers.cache import (  # noqa: E402
    TeacherCache,
    compute_entry_id,
    sha,
    sha_bytes,
)
from ainerzero.v9.teachers.fake import FakeTeacher  # noqa: E402

BASE = ROOT / "contracts/v9/examples/teacher_cache_v2"
HERE = Path(__file__).resolve().parent

OUT_BYTES = b"\x11" * 64
LICENSE = {
    "license_id": "MIT",
    "source_url": "https://example.invalid/synthetic-license",
    "verified_at": "2026-10-20",
    "scope": {
        "reference": True,
        "train": True,
        "eval": True,
        "commercial_output": True,
        "redistribute": True,
    },
    "approval_ref": None,
}


# --------------------------------------------------------------------------- helpers
def load_contract():
    """契约正例（schema-valid）store + 可信上下文 + 调用方固定的预期 context SHA。"""
    store = json.loads((BASE / "valid/valid_store.json").read_text())
    ctx = json.loads((BASE / "contexts/baseline.json").read_text())
    pins = json.loads((BASE / "expected-context-identities.json").read_text())["pins"]
    return store, ctx, pins["valid_store"]


def blob_of(store, entry):
    return next(
        r for r in store
        if r.get("record_type") == "teacher_blob" and r["cache_key"] == entry["cache_key"]
    )


def entry_of(store, prefix):
    return next(
        r for r in store
        if r.get("record_type") == "teacher_entry" and r["entry_id"].startswith(prefix)
    )


def sp(store, ctx, exp):
    """库级校验（schema 全开：disabled=()），走模块属性以便 poison 生效。"""
    return cache_mod.store_problems(store, ctx, exp, disabled=())


def te(entry, store, ctx, exp):
    return cache_mod.train_eligible(entry, store, ctx, exp, disabled=())


def new_lib_cache(root: Path):
    """按实现自己的磁盘格式（output_sha256）建一个可读写的缓存，返回 (cache, km, cache_key)。"""
    store, _, _ = load_contract()
    km = copy.deepcopy(store[0]["key_material"])
    cache = TeacherCache(Path(root))
    cache.write_blob(sha(km), km, OUT_BYTES, copy.deepcopy(LICENSE), reproducibility="numeric")
    return cache, km, sha(km)


def mk_entry(km, ck, partition="train", world_key="test:world", teacher_id=None,
             weights=None, use="input", train_license=True, license_obj=None):
    ticks = list(km["input"]["timestamps_ticks"])
    secs = list(km["input"]["timestamps_s"])
    entry = {
        "schema_version": "az.v9.teacher_cache.v2",
        "record_type": "teacher_entry",
        "entry_id": "",
        "cache_key": ck,
        "source": {
            "world_key": world_key,
            "partition": partition,
            "store": "shared" if partition != "final" else "sealed_eval",
            "manifest_ref": {"manifest_id": "m-test", "source_id": "s-test-1"},
            "timestamps_ticks": ticks,
            "timestamps_s": secs,
            "time_domain": km["input"]["time_domain"],
        },
        "as_of_t_ticks": ticks[-1],
        "as_of_t_s": secs[-1],
        "provenance": {
            "upstream": {
                "system": "ainerzero",
                "origin": "observed",
                "actor": {"actor_id": "student"},
                "input_ref": {"sha256": km["input"]["sha256"], "uri": "test://input"},
                "eligibility": {"train": True, "basis": "admit_training", "revision_ref": None},
            },
            "derivation": {
                "teacher_id": teacher_id or km["teacher"]["teacher_id"],
                "use": use,
                "weights_sha256": weights or [w["sha256"] for w in km["teacher"]["weights"]],
                "preprocess_spec_sha256": km["preprocess"]["spec_sha256"],
            },
        },
        "license": license_obj or copy.deepcopy(LICENSE),
        "noise_model_ref": None,
    }
    if not train_license:
        entry["license"] = copy.deepcopy(LICENSE)
        entry["license"]["scope"]["train"] = False
    entry["entry_id"] = compute_entry_id(entry)
    return entry


def blob_json_path(cache: TeacherCache, ck: str) -> Path:
    return cache.blobs_dir / ck[:2] / ck / "blob.json"


def entry_json_path(cache: TeacherCache, entry_id: str) -> Path:
    return cache.entries_dir / entry_id[:2] / entry_id / f"{entry_id}.json"


def read_json(path: Path):
    return json.loads(Path(path).read_text())


# --------------------------------------------------------------------------- poisons
def _poison_store_problems_off():
    cache_mod.store_problems = lambda *a, **k: []


def _poison_validate_schema_off():
    cache_mod.validate_schema = lambda *a, **k: []


def _poison_read_verify_off():
    """读时核验拿错摘要比对（把 read_blob 的输出核验改坏）。"""
    orig = TeacherCache.read_blob

    def patched(self, cache_key):
        p = self.blobs_dir / cache_key[:2] / cache_key / "blob.json"
        if p.exists():
            rec = json.loads(p.read_text())
            rec["output_sha256"] = "0" * 64
            p.write_text(json.dumps(rec))
        return orig(self, cache_key)

    TeacherCache.read_blob = patched


def _poison_mode_check_off():
    mode_mod.ModeGuard.check_teacher_load = classmethod(lambda cls, *a, **k: None)


def _poison_set_mode_off():
    mode_mod.ModeGuard.set_mode = classmethod(
        lambda cls, mode, world_ttl_s=None: object.__setattr__(cls, "_mode", mode)
    )


def _poison_write_blob_overwrite():
    """内容块已存在也允许覆盖（把 nondeterministic_output 拒绝改坏）。"""
    orig = TeacherCache.write_blob

    def patched(self, cache_key, key_material, output_data, teacher_license,
                reproducibility="unverified", confidence_data=None,
                generation_info=None, extra=None):
        bj = self.blobs_dir / cache_key[:2] / cache_key / "blob.json"
        if bj.exists():
            bj.unlink()
        return orig(self, cache_key, key_material, output_data, teacher_license,
                    reproducibility, confidence_data, generation_info, extra)

    TeacherCache.write_blob = patched


@contextlib.contextmanager
def _poison_write_entry_scan_off():
    """来源条目跨分区扫描被绕过（把 §2.4 写时拒绝改坏）。"""
    import pathlib

    orig = pathlib.Path.rglob

    def blind(self, pattern, *a, **k):
        return iter([])

    pathlib.Path.rglob = blind
    try:
        yield None  # noqa: SIM118
    finally:
        pathlib.Path.rglob = orig


def _poison_write_entry_meta_off():
    TeacherCache.REQUIRED_ENTRY_META = ()


POISONS = {
    "store_problems_off": _poison_store_problems_off,
    "validate_schema_off": _poison_validate_schema_off,
    "read_verify_off": _poison_read_verify_off,
    "mode_check_off": _poison_mode_check_off,
    "set_mode_off": _poison_set_mode_off,
    "write_blob_overwrite": _poison_write_blob_overwrite,
    "write_entry_scan_off": _poison_write_entry_scan_off,
    "write_entry_meta_off": _poison_write_entry_meta_off,
}


@contextlib.contextmanager
def poisoned(name: str):
    """安装改坏（只在本进程内 monkeypatch，不改源码）。"""
    fn = POISONS[name]
    if name == "write_entry_scan_off":
        with _poison_write_entry_scan_off():
            yield
    else:
        fn()
        yield


# --------------------------------------------------------------------------- C01
def case_c01():
    """[元数据伪造] 篡改 blob.reproducibility（unverified→bitwise）能否静默提升训练准入。"""
    store, ctx, exp = load_contract()
    entry = entry_of(store, "a138")          # 只被 reproducibility=unverified 挡住
    blob = blob_of(store, entry)
    honest = te(entry, store, ctx, exp)
    blob["reproducibility"] = "bitwise"
    problems = sp(store, ctx, exp)
    forged = te(entry, store, ctx, exp)
    metrics = {
        "honest_eligible": honest,
        "forged_eligible": forged,
        "store_problems_after_forgery": problems,
        "entry_id_stable": compute_entry_id(entry) == entry["entry_id"],
        "delta_fields": 1,
    }
    v = []
    if (not honest) and forged and problems == []:
        v.append(
            "blob.reproducibility 由 unverified 篡改为 bitwise 后，train_eligible False→True，"
            "store_problems=[]：可复现等级（§2.3 要求实测登记）不受 entry_id/cache_key/可信上下文任一保护"
        )
    return metrics, v


def ctrl_c01():
    """对照：篡改 source.partition（在可信上下文绑定内）必须被抓。"""
    store, ctx, exp = load_contract()
    entry = entry_of(store, "a138")
    entry["source"]["partition"] = "development"
    probs = sp(store, ctx, exp)
    v = []
    if "original_source_binding_mismatch" not in probs:
        v.append(f"对照失效：篡改 partition 后 store_problems={probs} 未含 original_source_binding_mismatch")
    return v


# --------------------------------------------------------------------------- C02
def case_c02():
    """[元数据伪造] 篡改 entry.license / blob.teacher_license（准入五项交集里的两项）。"""
    store, ctx, exp = load_contract()
    entry = entry_of(store, "3d7b")          # 诚实时可训
    blob = blob_of(store, entry)
    honest = te(entry, store, ctx, exp)
    entry["license"]["scope"]["train"] = False
    denied_by_license = te(entry, store, ctx, exp)
    p1 = sp(store, ctx, exp)
    entry["license"]["scope"]["train"] = True          # 攻击者改回/抬高
    escalated = te(entry, store, ctx, exp)
    p2 = sp(store, ctx, exp)
    blob["teacher_license"]["scope"]["train"] = False
    denied_by_teacher = te(entry, store, ctx, exp)
    blob["teacher_license"]["scope"]["train"] = True   # 攻击者抬高
    escalated2 = te(entry, store, ctx, exp)
    p3 = sp(store, ctx, exp)
    metrics = {
        "honest_eligible": honest,
        "entry_license_false_eligible": denied_by_license,
        "entry_license_forged_true_eligible": escalated,
        "teacher_license_false_eligible": denied_by_teacher,
        "teacher_license_forged_true_eligible": escalated2,
        "store_problems_all_states": [p1, p2, p3],
        "entry_id_stable": compute_entry_id(entry) == entry["entry_id"],
    }
    v = []
    if denied_by_license is False and escalated is True and p2 == []:
        v.append("entry.license.scope.train 由 False 抬高为 True 后 train_eligible False→True，store_problems=[]")
    if denied_by_teacher is False and escalated2 is True and p3 == []:
        v.append("blob.teacher_license.scope.train 由 False 抬高为 True 后 train_eligible False→True，store_problems=[]")
    if honest is not True:
        v.append(f"前提失效：契约正例 3d7b 的诚实训练准入应为 True，实际 {honest}")
    return metrics, v


def ctrl_c02():
    """对照：篡改 upstream.eligibility（在可信上下文绑定内）必须被抓。"""
    store, ctx, exp = load_contract()
    entry = entry_of(store, "3d7b")
    entry["provenance"]["upstream"]["eligibility"]["train"] = False
    probs = sp(store, ctx, exp)
    v = []
    if "original_source_binding_mismatch" not in probs:
        v.append(f"对照失效：篡改 eligibility 后 store_problems={probs} 未含 original_source_binding_mismatch")
    return v


# --------------------------------------------------------------------------- C03
def case_c03():
    """[元数据伪造] 同一 entry_id 不同内容：§2.2 要求"内容完全一致就跳过，否则拒绝"。"""
    with tempfile.TemporaryDirectory() as td:
        cache, km, ck = new_lib_cache(td)
        entry = mk_entry(km, ck)
        cache.write_entry(entry)
        before = entry_json_path(cache, entry["entry_id"]).read_text()
        forged = copy.deepcopy(entry)
        forged["license"]["scope"]["train"] = not entry["license"]["scope"]["train"]
        forged_id_stable = compute_entry_id(forged) == entry["entry_id"]
        accepted, err = True, None
        try:
            cache.write_entry(forged)
        except Exception as ex:  # noqa: BLE001
            accepted, err = False, f"{type(ex).__name__}: {ex}"
        after = entry_json_path(cache, entry["entry_id"]).read_text()
        metrics = {
            "forged_entry_id_stable": forged_id_stable,
            "second_write_accepted": accepted,
            "error": err,
            "content_replaced": before != after,
            "license_train_before": json.loads(before)["license"]["scope"]["train"],
            "license_train_after": json.loads(after)["license"]["scope"]["train"],
            "bytes_delta": len(after) - len(before),
        }
    v = []
    if forged_id_stable and (accepted or metrics["content_replaced"]):
        v.append(
            "同 entry_id、不同内容的第二次写入未被拒绝：原条目被静默覆盖"
            f"（license.scope.train {metrics['license_train_before']}→{metrics['license_train_after']}），"
            "违反 §2.2「来源条目已存在：内容完全一致就跳过，否则拒绝」"
        )
    return metrics, v


def ctrl_c03():
    """对照：写入缺必备元数据的条目必须 MetadataIncompleteError。"""
    with tempfile.TemporaryDirectory() as td:
        cache, km, ck = new_lib_cache(td)
        bad = mk_entry(km, ck)
        bad.pop("provenance")
        got = None
        try:
            cache.write_entry(bad)
        except cache_mod.MetadataIncompleteError:
            got = "MetadataIncompleteError"
        except Exception as ex:  # noqa: BLE001
            got = f"{type(ex).__name__}"
        v = []
        if got != "MetadataIncompleteError":
            v.append(f"对照失效：期望 MetadataIncompleteError，实际 {got}")
        return v


# --------------------------------------------------------------------------- C04
def case_c04():
    """[元数据伪造] write_blob 的产物是否通过契约 schema（§6：用 schema 校验每条记录）。"""
    with tempfile.TemporaryDirectory() as td:
        cache, km, ck = new_lib_cache(td)
        record = read_json(blob_json_path(cache, ck))
        errs = cache_mod.validate_schema(record, "teacher_blob")
    test_src = (ROOT / "tests/v9/teachers/test_cache.py").read_text()
    seg = test_src.split("def test_validate_schema_blob")[1].split("\ndef ")[0]
    metrics = {
        "schema_errors": len(errs),
        "first_errors": [e[:120] for e in errs[:4]],
        "written_keys": sorted(record.keys()),
        "t2_schema_test_assert_count": seg.count("assert"),
    }
    v = []
    if errs:
        v.append(
            f"write_blob 落盘的 blob 记录有 {len(errs)} 项 schema 违例（缺 schema_version/output/confidence/tolerance，"
            "多了 output_sha256/confidence_sha256），与 contracts/v9/teacher_cache.v2.schema.json 不兼容；"
            f"T2 自己的 test_validate_schema_blob 断言数={seg.count('assert')}（空转）"
        )
    return metrics, v


def ctrl_c04():
    """对照：validate_schema 必须能对畸形记录报错（证明检测器非空转）。"""
    store, _, _ = load_contract()
    bad = copy.deepcopy(store[0])
    bad.pop("schema_version")
    errs = cache_mod.validate_schema(bad, "teacher_blob")
    v = []
    if not errs:
        v.append("对照失效：删掉 schema_version 后 validate_schema 返回空")
    return v


# --------------------------------------------------------------------------- C05
def case_c05():
    """[跨模型混写] 条目 derivation 换成另一个模型，写入/读取路径是否拒绝（§2.1）。"""
    with tempfile.TemporaryDirectory() as td:
        cache, km, ck = new_lib_cache(td)
        entry = mk_entry(km, ck)
        cache.write_entry(entry)
        foreign = copy.deepcopy(entry)
        foreign["provenance"]["derivation"]["teacher_id"] = "da3-small-FOREIGN"
        foreign["provenance"]["derivation"]["weights_sha256"] = ["f" * 64]
        foreign["entry_id"] = compute_entry_id(foreign)
        accepted, err = True, None
        try:
            cache.write_entry(foreign)
        except Exception as ex:  # noqa: BLE001
            accepted, err = False, f"{type(ex).__name__}: {ex}"
        read_back = None
        try:
            read_back = cache.read_entry(foreign["entry_id"])["provenance"]["derivation"]["teacher_id"]
        except Exception as ex:  # noqa: BLE001
            read_back = f"{type(ex).__name__}"
        metrics = {
            "entry_id_stable_under_teacher_swap": foreign["entry_id"] == entry["entry_id"],
            "write_accepted": accepted,
            "write_error": err,
            "read_back_teacher_id": read_back,
            "blob_teacher_id": km["teacher"]["teacher_id"],
        }
    v = []
    if accepted and read_back == "da3-small-FOREIGN":
        v.append(
            "把条目 derivation.teacher_id/weights 换成另一个模型后 write_entry 与 read_entry 都放行，"
            "store 里同时存在同一 cache_key 指向两个模型的条目（§2.1：derived_by 必须等于块的 teacher_id）"
        )
    return metrics, v


def ctrl_c05():
    """对照：库级 store_problems 对同样的跨模型改写必须报 derivation_teacher_mismatch。"""
    store, ctx, exp = load_contract()
    entry = entry_of(store, "3d7b")
    entry["provenance"]["derivation"]["teacher_id"] = "da3-small-FOREIGN"
    probs = sp(store, ctx, exp)
    v = []
    if "derivation_teacher_mismatch" not in probs:
        v.append(f"对照失效：store_problems={probs} 未含 derivation_teacher_mismatch")
    return v


# --------------------------------------------------------------------------- C06
def case_c06():
    """[跨模型混写] 磁盘上改 blob.key_material（换模型）后读路径是否核验 cache_key=sha(key_material)。"""
    with tempfile.TemporaryDirectory() as td:
        cache, km, ck = new_lib_cache(td)
        path = blob_json_path(cache, ck)
        rec = read_json(path)
        rec["key_material"]["teacher"]["teacher_id"] = "da3-small-FOREIGN"
        path.write_text(json.dumps(rec))
        tampered = read_json(path)
        key_ok = sha(tampered["key_material"]) == ck
        raised, broken = None, None
        try:
            out = cache.read_blob(ck)
            broken = out.get("broken")
        except Exception as ex:  # noqa: BLE001
            raised = f"{type(ex).__name__}"
        metrics = {
            "cache_key_matches_sha_key_material": key_ok,
            "delta": 0 if key_ok else 1,
            "read_raised": raised,
            "broken_flag": broken,
        }
    v = []
    if (not key_ok) and raised is None:
        v.append(
            "blob.key_material 被改成另一个模型后 read_blob 照常返回（不重算 cache_key=sha(key_material)，"
            "也不置 broken），内容块身份可在读路径被替换"
        )
    return metrics, v


def ctrl_c06():
    """对照：库级 store_problems 对同样的 key_material 改写必须报 cache_key_mismatch。"""
    store, ctx, exp = load_contract()
    blob = store[0]
    blob["key_material"]["teacher"]["teacher_id"] = "da3-small-foreign-model"
    probs = sp(store, ctx, exp)
    v = []
    if "cache_key_mismatch" not in probs:
        v.append(f"对照失效：store_problems={probs} 未含 cache_key_mismatch")
    return v


# --------------------------------------------------------------------------- C07
def case_c07():
    """[契约一致性] 契约 schema-valid 的内容块能否被实现读取（不误判 broken）。"""
    store, _, _ = load_contract()
    contract_blob = copy.deepcopy(store[0])
    out = b"\x22" * 64
    contract_blob["output"]["files"][0]["sha256"] = sha_bytes(out)
    ck = sha(contract_blob["key_material"])
    contract_blob["cache_key"] = ck
    with tempfile.TemporaryDirectory() as td:
        cache = TeacherCache(Path(td))
        d = cache.blobs_dir / ck[:2] / ck
        d.mkdir(parents=True, exist_ok=True)
        (d / "blob.json").write_text(json.dumps(contract_blob))
        (d / "output.bin").write_bytes(out)
        raised, broken = None, None
        try:
            broken = cache.read_blob(ck).get("broken")
        except Exception as ex:  # noqa: BLE001
            raised = f"{type(ex).__name__}: {str(ex)[:100]}"
    errs = cache_mod.validate_schema(contract_blob, "teacher_blob")
    metrics = {
        "contract_blob_schema_errors": len(errs),
        "read_raised": raised,
        "broken_flag": broken,
    }
    v = []
    if raised is not None or broken is not None:
        v.append(
            "契约正例格式（output.files[].sha256）的合法内容块被 read_blob 判成 hash mismatch/broken："
            "实现的落盘格式与 teacher_cache.v2.schema.json 是两套互不相认的格式（§6 要求用该 schema 校验每条记录）"
        )
    return metrics, v


def ctrl_c07():
    """对照：实现自己格式的内容块必须能正常读出且不置 broken。"""
    with tempfile.TemporaryDirectory() as td:
        cache, km, ck = new_lib_cache(td)
        try:
            rec = cache.read_blob(ck)
            broken = rec.get("broken")
        except Exception as ex:  # noqa: BLE001
            broken = f"{type(ex).__name__}"
        v = []
        if broken is not None:
            v.append(f"对照失效：实现自格式内容块读取异常 broken={broken}")
        return v


# --------------------------------------------------------------------------- C08
def case_c08():
    """[模式绕过] 切到 Train Mode 后，先前加载的教师句柄是否还能继续产出（§1.1/§1.4）。"""
    mode_mod.ModeGuard.reset()
    mode_mod.ModeGuard.set_mode("teacher")
    teacher = FakeTeacher("vjepa2.1-vitl", "feature")
    mode_mod.ModeGuard.release_teacher()          # 只放守卫登记，不 unload 句柄
    mode_mod.ModeGuard.set_mode("train")
    produced = None
    try:
        produced = len(teacher.extract("c" * 64, [0, 12, 24]))
    except Exception as ex:  # noqa: BLE001
        produced = f"{type(ex).__name__}"
    metrics = {
        "mode_after_switch": mode_mod.ModeGuard.get_mode(),
        "bytes_produced_in_train_mode": produced,
        "resident_teacher": mode_mod.ModeGuard._teacher_loaded,
    }
    mode_mod.ModeGuard.reset()
    v = []
    if isinstance(produced, int) and produced > 0:
        v.append(
            f"Train Mode 下常驻教师句柄仍产出 {produced} 字节：守卫只在构造时检查一次，"
            "release_teacher()+set_mode('train') 之后不再复核（§1.1 Train 禁止任何教师常驻）"
        )
    return metrics, v


def ctrl_c08():
    """对照：Train Mode 下构造教师必须抛 ModeViolationError。"""
    mode_mod.ModeGuard.reset()
    mode_mod.ModeGuard.set_mode("train")
    got = None
    try:
        FakeTeacher("vjepa2.1-vitl", "feature")
    except mode_mod.ModeViolationError:
        got = "ModeViolationError"
    except Exception as ex:  # noqa: BLE001
        got = f"{type(ex).__name__}"
    mode_mod.ModeGuard.reset()
    v = []
    if got != "ModeViolationError":
        v.append(f"对照失效：Train Mode 构造教师期望 ModeViolationError，实际 {got}")
    return v


# --------------------------------------------------------------------------- C09
def case_c09():
    """[模式绕过] World Mode 教师 TTL 到期后是否自动卸载并使句柄失效（§1.4）。"""
    mode_mod.ModeGuard.reset()
    mode_mod.ModeGuard.set_mode("world", world_ttl_s=0.05)
    geom = FakeTeacher("da3-small", "geometry")
    time.sleep(0.12)
    still_loaded = mode_mod.ModeGuard._teacher_loaded
    produced = None
    try:
        produced = len(geom.extract("c" * 64, [0]))
    except Exception as ex:  # noqa: BLE001
        produced = f"{type(ex).__name__}"
    metrics = {
        "ttl_s": 0.05,
        "elapsed_s": 0.12,
        "guard_still_marks_loaded": still_loaded,
        "bytes_produced_after_ttl": produced,
    }
    mode_mod.ModeGuard.reset()
    v = []
    if still_loaded or (isinstance(produced, int) and produced > 0):
        v.append(
            f"TTL(0.05s) 过 0.12s 后守卫仍标记 teacher_loaded={still_loaded}、句柄仍产出 {produced} 字节："
            "TTL 只在下一次 check/set_mode 时惰性过期，且过期不使已加载句柄失效（§1.4「超时自动卸载」）"
        )
    return metrics, v


def ctrl_c09():
    """对照：World Mode 下加载 feature 教师必须抛 ModeViolationError。"""
    mode_mod.ModeGuard.reset()
    mode_mod.ModeGuard.set_mode("world")
    got = None
    try:
        FakeTeacher("vjepa2.1-vitl", "feature")
    except mode_mod.ModeViolationError:
        got = "ModeViolationError"
    except Exception as ex:  # noqa: BLE001
        got = f"{type(ex).__name__}"
    mode_mod.ModeGuard.reset()
    v = []
    if got != "ModeViolationError":
        v.append(f"对照失效：World Mode 加载 feature 教师期望 ModeViolationError，实际 {got}")
    return v


# --------------------------------------------------------------------------- C10
def case_c10():
    """[模式绕过] 模式切换前的内存回落检查（§1.4 unload_incomplete）是否实现。"""
    src = (ROOT / "src/ainerzero/v9/teachers/mode.py").read_text()
    hits = re.findall(r"(?i)rss|unload_incomplete|getrusage|ps -o|available_memory", src)
    metrics = {"mode_py_memory_check_refs": len(hits), "refs": sorted(set(hits))}
    v = []
    if not hits:
        v.append(
            "§1.4 要求模式切换前记录内存并在回落不足时拒绝切换（记 unload_incomplete），"
            "但 mode.py 中 0 处引用 RSS/内存/unload_incomplete，该守卫未实现"
        )
    return metrics, v


def ctrl_c10():
    """对照：set_mode 必须拒绝非法模式名（证明 set_mode 的入参校验非空转）。"""
    mode_mod.ModeGuard.reset()
    got = None
    try:
        mode_mod.ModeGuard.set_mode("not_a_mode")
    except ValueError:
        got = "ValueError"
    except Exception as ex:  # noqa: BLE001
        got = f"{type(ex).__name__}"
    mode_mod.ModeGuard.reset()
    v = []
    if got != "ValueError":
        v.append(f"对照失效：set_mode('not_a_mode') 期望 ValueError，实际 {got}")
    return v


# --------------------------------------------------------------------------- C11（并发写入）
def _blob_writer(root, km, out_bytes, q, idx, barrier=None):
    if barrier is not None:
        barrier.wait(timeout=30)
    try:
        cache = TeacherCache(Path(root))
        cache.write_blob(
            sha(km), km, out_bytes, copy.deepcopy(LICENSE), reproducibility="numeric"
        )
        q.put((idx, "accepted", None))
    except Exception as ex:  # noqa: BLE001
        q.put((idx, "rejected", f"{type(ex).__name__}: {str(ex)[:80]}"))


def case_c11():
    """[并发写入] 两进程同时对同一 cache_key 写不同输出，nondeterministic_output 拒绝是否还成立。

    §2.2：内容块目录已存在时比较新算出的输出摘要，不一致就拒绝（nondeterministic_output）。
    实现是 check-then-write 且无互斥；用 Barrier 让两个进程同时进入写入，重复 20 轮统计命中。
    """
    rounds = 20
    hit_rounds = []
    round_records = []
    store, _, _ = load_contract()
    km = copy.deepcopy(store[0]["key_material"])
    ck = sha(km)
    for r in range(rounds):
        ctx = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as td:
            q = ctx.Queue()
            barrier = ctx.Barrier(2)
            procs = [
                ctx.Process(target=_blob_writer, args=(td, km, bytes([i + 1]) * 64, q, i, barrier))
                for i in range(2)
            ]
            for p in procs:
                p.start()
            for p in procs:
                p.join(60)
            results = [q.get() for _ in range(2)]
            cache = TeacherCache(Path(td))
            rec = read_json(blob_json_path(cache, ck))
            actual = sha_bytes((cache.blobs_dir / ck[:2] / ck / "output.bin").read_bytes())
            consistent = actual == rec["output_sha256"]
        rec_entry = {
            "round": r,
            "accepted": sum(1 for _, s, _ in results if s == "accepted"),
            "stored_matches_recorded_sha": consistent,
        }
        round_records.append(rec_entry)
        if rec_entry["accepted"] == 2 or not consistent:
            hit_rounds.append(r)
    metrics = {
        "rounds": rounds,
        "rounds_broken_rejection": len(hit_rounds),
        "first_hit": next(
            (
                x for x in round_records
                if x["accepted"] == 2 or not x["stored_matches_recorded_sha"]
            ),
            None,
        ),
        "example_round": round_records[0],
    }
    v = []
    if hit_rounds:
        v.append(
            f"{rounds} 轮并发同键不同输出写入中 {len(hit_rounds)} 轮拒绝失效"
            f"（两进程都被接受，或盘上 output.bin 与 blob.json 记录的 sha 不一致）："
            "§2.2「不一致就拒绝写入 nondeterministic_output」在并发下不成立，实现的 check-then-write 无互斥"
        )
    return metrics, v


def ctrl_c11():
    """对照：顺序第二次写不同输出必须抛 nondeterministic_output。"""
    with tempfile.TemporaryDirectory() as td:
        cache, km, ck = new_lib_cache(td)
        got = None
        try:
            cache.write_blob(ck, km, b"\x99" * 64, copy.deepcopy(LICENSE), reproducibility="numeric")
        except Exception as ex:  # noqa: BLE001
            got = f"{type(ex).__name__}: {str(ex)[:80]}"
        v = []
        if not got or "nondeterministic_output" not in got:
            v.append(f"对照失效：顺序重写不同输出期望 nondeterministic_output，实际 {got}")
        return v


def _entry_writer(root, entry, q, idx, barrier=None):
    if barrier is not None:
        barrier.wait(timeout=30)
    try:
        TeacherCache(Path(root)).write_entry(entry)
        q.put((idx, "accepted", None))
    except Exception as ex:  # noqa: BLE001
        q.put((idx, "rejected", f"{type(ex).__name__}: {str(ex)[:80]}"))


def case_c12():
    """[并发写入] 两进程同时写同一 cache_key 的不同分区条目，cross_partition_blob 写时拒绝是否还成立。

    写时检查是 check-then-act（先 rglob 扫已有条目，再 os.replace 落盘），所以串行必然拒绝、
    并发取决于时序。这里用 Barrier 让两个进程在同一时刻进入写入，重复 20 轮统计命中次数。
    """
    rounds = 20
    cross_rounds = []
    round_records = []
    for r in range(rounds):
        ctx = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as td:
            cache, km, ck = new_lib_cache(td)
            e_train = mk_entry(km, ck, partition="train")
            e_dev = mk_entry(km, ck, partition="development")
            q = ctx.Queue()
            barrier = ctx.Barrier(2)
            procs = [
                ctx.Process(target=_entry_writer, args=(td, e_train, q, 0, barrier)),
                ctx.Process(target=_entry_writer, args=(td, e_dev, q, 1, barrier)),
            ]
            for p in procs:
                p.start()
            for p in procs:
                p.join(60)
            results = [q.get() for _ in range(2)]
            parts = sorted({
                json.loads(f.read_text())["source"]["partition"]
                for f in TeacherCache(Path(td)).entries_dir.rglob("*.json")
            })
        round_records.append({"round": r, "results": results, "partitions": parts})
        if len(parts) > 1:
            cross_rounds.append(r)
    metrics = {
        "rounds": rounds,
        "rounds_with_cross_partition_blob": len(cross_rounds),
        "first_hit": next((x for x in round_records if len(x["partitions"]) > 1), None),
        "example_round": round_records[0],
    }
    v = []
    if cross_rounds:
        v.append(
            f"{rounds} 轮并发同键跨分区写入中 {len(cross_rounds)} 轮双双成功，"
            f"盘上分区出现 {sorted({p for rec in round_records for p in rec['partitions']})}："
            "§2.4「新条目拒绝写入」的写时扫描是 check-then-act 且无互斥，并发下 cross_partition_blob 照样产生"
        )
    return metrics, v


def ctrl_c12():
    """对照：顺序写第二个分区的条目必须抛 CrossPartitionError。"""
    with tempfile.TemporaryDirectory() as td:
        cache, km, ck = new_lib_cache(td)
        cache.write_entry(mk_entry(km, ck, partition="train"))
        got = None
        try:
            cache.write_entry(mk_entry(km, ck, partition="development"))
        except Exception as ex:  # noqa: BLE001
            got = f"{type(ex).__name__}"
        v = []
        if got != "CrossPartitionError":
            v.append(f"对照失效：顺序跨分区写入期望 CrossPartitionError，实际 {got}")
        return v


# --------------------------------------------------------------------------- registry
CASES = {
    "C01": ("元数据伪造", "blob.reproducibility 篡改提升训练准入", case_c01, ctrl_c01, "store_problems_off"),
    "C02": ("元数据伪造", "entry/blob 许可篡改提升训练准入", case_c02, ctrl_c02, "store_problems_off"),
    "C03": ("元数据伪造", "同 entry_id 不同内容被静默覆盖", case_c03, ctrl_c03, "write_entry_meta_off"),
    "C04": ("元数据伪造", "write_blob 产物不通过契约 schema", case_c04, ctrl_c04, "validate_schema_off"),
    "C05": ("跨模型混写", "条目 derivation 换模型后写入/读取放行", case_c05, ctrl_c05, "store_problems_off"),
    "C06": ("跨模型混写", "blob.key_material 被换模型后读路径不核验", case_c06, ctrl_c06, "store_problems_off"),
    "C07": ("跨模型混写", "契约合法内容块被实现误判 broken", case_c07, ctrl_c07, "read_verify_off"),
    "C08": ("模式绕过", "Train Mode 下常驻教师句柄仍可产出", case_c08, ctrl_c08, "mode_check_off"),
    "C09": ("模式绕过", "World Mode TTL 过期后句柄不失效", case_c09, ctrl_c09, "mode_check_off"),
    "C10": ("模式绕过", "模式切换无内存回落检查 unload_incomplete", case_c10, ctrl_c10, "set_mode_off"),
    "C11": ("并发写入", "并发同键不同输出丢失 nondeterministic 拒绝", case_c11, ctrl_c11, "write_blob_overwrite"),
    "C12": ("并发写入", "并发同键跨分区写入 TOCTOU", case_c12, ctrl_c12, "write_entry_scan_off"),
}


def run_one(case_id: str, poison: bool) -> dict:
    theme, title, case_fn, ctrl_fn, poison_name = CASES[case_id]
    entry = {"case": case_id, "theme": theme, "title": title, "poison": poison_name, "mode": "poison" if poison else "normal"}
    if poison:
        with poisoned(poison_name):
            ctrl_violations = ctrl_fn()
        entry["control_violations"] = ctrl_violations
        entry["poison_turned_red"] = bool(ctrl_violations)
        # 红 = 非零退出（改坏后断言必须变红，作为"真实非零退出"证据）
        entry["exit"] = 1 if ctrl_violations else 0
    else:
        metrics, violations = case_fn()
        ctrl_violations = ctrl_fn()
        entry["metrics"] = metrics
        entry["violations"] = violations
        entry["control_violations"] = ctrl_violations
        entry["verdict"] = "PASS" if not violations else "FAIL(finding)"
        entry["exit"] = 1 if (violations or ctrl_violations) else 0
    return entry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=sorted(CASES))
    parser.add_argument("--poison", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    if args.case:
        entry = run_one(args.case, args.poison)
        print("RESULT_JSON " + json.dumps(entry, ensure_ascii=False, default=str))
        return entry["exit"]

    summary = {"verifier_task": "ainerzero.V9.T3", "verified_task": "ainerzero.V9.T2",
               "normal": [], "poison": []}
    for mode_name, poison in (("normal", False), ("poison", True)):
        for case_id in sorted(CASES):
            cmd = [sys.executable, "-B", str(Path(__file__).resolve()), "--case", case_id]
            if poison:
                cmd.append("--poison")
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), env=env)
            line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
            if line is None:
                rec = {"case": case_id, "mode": mode_name, "harness_error": proc.stderr[-400:], "exit": 2}
            else:
                rec = json.loads(line[len("RESULT_JSON "):])
                rec["exit"] = proc.returncode
            summary[mode_name].append(rec)
            tag = rec.get("verdict") or ("RED" if rec.get("poison_turned_red") else "NOT-RED")
            print(f"[{mode_name:<7}] {case_id} exit={proc.returncode} {tag}  {rec.get('title', '')}")

    findings = [r["case"] for r in summary["normal"] if r.get("violations")]
    controls_bad = [r["case"] for r in summary["normal"] if r.get("control_violations")]
    poison_not_red = [r["case"] for r in summary["poison"] if not r.get("poison_turned_red")]
    summary["findings"] = findings
    summary["control_failures_normal"] = controls_bad
    summary["poison_not_red"] = poison_not_red
    summary["cases_total"] = len(CASES)
    summary["themes"] = sorted({v[0] for v in CASES.values()})
    summary["exit"] = 1 if (findings or controls_bad or poison_not_red) else 0
    out = args.json_out or (HERE / "adversarial_summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n")
    print(f"--- findings={len(findings)} control_failures={len(controls_bad)} poison_not_red={len(poison_not_red)} exit={summary['exit']}")
    return summary["exit"]


if __name__ == "__main__":
    sys.exit(main())
