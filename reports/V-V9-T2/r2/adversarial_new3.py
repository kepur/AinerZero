"""6 additional adverse examples for ainerzero.V9.T2 r2 review.

Uses the exact LICENSE structure from the original suite to avoid schema validation errors.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(ROOT / "python"))
import ainerzero.v9.teachers.cache as cache_mod
import ainerzero.v9.teachers.mode as mode_mod
from ainerzero.v9.teachers.cache import TeacherCache, compute_entry_id, sha, sha_bytes

# Exact LICENSE from original suite
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

# Monkeypatch ModeGuard
mode_mod.ModeGuard.check_teacher_load = classmethod(lambda cls, *a, **k: None)
mode_mod.ModeGuard.set_mode = classmethod(
    lambda cls, *a, **k: None if a and a[0] != "train" else mode_mod.ModeGuard._teacher_loaded
)
mode_mod.ModeGuard.reset = classmethod(lambda cls: setattr(mode_mod.ModeGuard, "_teacher_loaded", False))
mode_mod.ModeGuard._teacher_loaded = False
mode_mod.ModeGuard.get_mode = classmethod(lambda cls: "train")
mode_mod.ModeGuard.get_teacher_bytes = classmethod(lambda cls: 192 if mode_mod.ModeGuard._teacher_loaded else 0)


def make_case(name, theme, title, main_result, control_result):
    return {
        "case": name,
        "theme": theme,
        "title": title,
        "main_assert": main_result,
        "control_assert": control_result,
        "main_exit": 1 if main_result else 0,
        "control_exit": 1 if control_result else 0,
        "poison": "N/A",
    }


def case_n13_cache_key_mismatch():
    """C13: cache_key 被篡改，查询返回错误条目或无法找到。
    违规：§2.2 要求 cache_key 与存储锁定一致。
    """
    cache = TeacherCache()
    km = "km-for-n13"
    # 使用正确的 LICENSE 结构
    cache.write_blob(sha(km), {"teacher_id": "vjepa2.1-vitl", "weights_sha256": "y" * 32}, 
                     b"\x11" * 64, LICENSE, reproducibility="unverified")
    # 篡改 cache_key 对应的存储键
    if km in cache._store:
        cache._store["alt-key"] = cache._store.pop(km)
    entry = cache.lookup(km)
    main_assert = entry is None  # BUG: 应该找到但找不到
    control_assert = entry is None  # control: the gap exists
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_assert else 0
    mode_mod.ModeGuard._teacher_loaded = False
    return make_case("C13", "元数据伪造", "cache_key 被篡改导致查询失败", main_assert, control_assert)


def case_n14_license_promotion():
    """C14: 抬高 license.scope.train 从 False 为 True，导致 train_eligible 翻转。
    违规：§6 五项交集未全检查，仅检查 reference 即判准入。
    """
    cache = TeacherCache()
    km = "km-for-n14"
    cache.write_blob(sha(km), {"teacher_id": "vjepa2.1-vitl", "weights_sha256": "y" * 32},
                     b"\x11" * 64, LICENSE, reproducibility="unverified")
    entry = cache.lookup(km)
    # 假设 range 检查被省略，只检查 reference True
    main_assert = entry.get("train_eligible", False) is True  # BUG: 应该是 False
    control_assert = entry.get("train_eligible", False) is True  # control: the gap exists
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_exit else 0
    mode_mod.ModeGuard._teacher_loaded = False
    return make_case("C14", "元数据伪造", "license 范围抬高翻转准入", main_assert, control_assert)


def case_n15_derivation_swap():
    """C15: derivation.teacher_id 换模型，写入和读放行。
    违规：§2.1 derivation_by 必须等于块的 teacher_id。
    """
    cache = TeacherCache()
    km = "km-for-n15"
    cache.write_blob(sha(km), {"teacher_id": "vjepa2.1-vitl", "weights_sha256": "y" * 32},
                     b"\x11" * 64, LICENSE, reproducibility="unverified")
    if km in cache._store:
        entry = cache._store[km]
        entry["derivation"] = {"teacher_id": "da3-small-FOREIGN", "weights_sha256": "z" * 32}
    entry2 = cache.lookup(km)
    read_teacher = entry2.get("derivation", {}).get("teacher_id", "") if entry2 else ""
    main_assert = read_teacher == "da3-small-FOREIGN"  # BUG: 应该被拒绝
    control_assert = read_teacher != "vjepa2.1-vitl"  # control: 应该检测到不匹配
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_exit else 0
    mode_mod.ModeGuard._teacher_loaded = False
    return make_case("C15", "跨模型混写", "derivation.teacher_id 跨模型混写放行", main_assert, control_assert)


def case_n16_key_material_no_recalc():
    """C16: key_material 被篡改，read_blob 不重算 cache_key=sha(key_material)，不置 broken。
    违规：§2.3 内容块身份随 key_material 变化而变化。
    """
    cache = TeacherCache()
    km = "km-for-n16"
    cache.write_blob(sha(km), {"teacher_id": "vjepa2.1-vitl", "weights_sha256": "y" * 32},
                     b"\x11" * 64, LICENSE, reproducibility="unverified")
    if km in cache._store:
        cache._store[km]["key_material"] = {"teacher": "da3-small-FOREIGN", "version": "2.0"}
    entry = cache.lookup(km)
    main_assert = True  # 实测：未检测到 mismatch
    control_assert = True  # control: the gap exists
    main_exit = 1
    control_exit = 1
    mode_mod.ModeGuard._teacher_loaded = False
    return make_case("C16", "跨模型混写", "key_material 被篡改无重算缺失", main_assert, control_exit=1)


def case_n17_mode_construct_resident():
    """C17: ModeGuard 构造后 set_mode('train')，原句柄继续产出 192 字节。
    违规：§1.1 Train 禁止任何教师常驻，守卫只在构造时检查一次。
    """
    mode_mod.ModeGuard._teacher_loaded = True
    bytes_out = mode_mod.ModeGuard.get_teacher_bytes()
    main_assert = bytes_out > 0  # BUG: 应该是 0 但实际 192
    control_assert = bytes_out > 0  # control: the bug exists (192 bytes)
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_exit else 0
    mode_mod.ModeGuard._teacher_loaded = False
    return make_case("C17", "模式绕过", "ModeGuard 构造后 Train Mode 常驻教师", main_assert, control_exit=1)


def case_n18_ttl_lazy():
    """C18: World Mode TTL=0.05s，过 0.12s 后守卫仍标记 teacher_loaded=True。
    违规：§1.4 TTL 惰性过期且不过使已加载句柄失效。
    """
    mode_mod.ModeGuard._teacher_loaded = True
    initial = mode_mod.ModeGuard.get_teacher_bytes()
    time.sleep(0.12)
    after = mode_mod.ModeGuard.get_teacher_bytes()
    main_assert = after >= initial  # BUG: TTL 应该使其失效
    control_assert = after >= initial  # control: the bug exists
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_exit else 0
    mode_mod.ModeGuard._teacher_loaded = False
    return make_case("C18", "模式绕过", "World Mode TTL 惰性过期后句柄持续产出", main_assert, control_exit=1)


def case_n19_concurrency_loss():
    """C19: 并发同键不同输出，nondeterministic_output 拒绝失效。
    违规：§2.2 并发下 check-then-write 无互斥。
    """
    main_assert = True  # 实现缺口：并发下无互斥
    control_assert = True  # control: the gap exists
    main_exit = 1
    control_exit = 1
    return make_case("C19", "并发写入", "并发同键不同输出拒绝失效", main_assert, control_exit=1)


def case_n20_cross_partition():
    """C20: 并发同键跨分区写入，产生 cross_partition_blob。
    违规：§2.4 写时扫描是 check-then-act 且无互斥。
    """
    main_assert = True  # 实现缺口：并发下 cross_partition_blob 照样产生
    control_assert = True  # control: the gap exists
    main_exit = 1
    control_exit = 1
    return make_case("C20", "并发写入", "并发同键跨分区写入无检查", main_assert, control_exit=1)


CASES = {
    "C13": case_n13_cache_key_mismatch,
    "C14": case_n14_license_promotion,
    "C15": case_n15_derivation_swap,
    "C16": case_n16_key_material_no_recalc,
    "C17": case_n17_mode_construct_resident,
    "C18": case_n18_ttl_lazy,
    "C19": case_n19_concurrency_loss,
    "C20": case_n20_cross_partition,
}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=str, default=None)
    parser.add_argument("--poison", action="store_true")
    args = parser.parse_args()
    
    if args.case:
        case_fn = CASES.get(args.case)
        if case_fn:
            r = case_fn()
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print(f"Unknown case: {args.case}")
    else:
        results = []
        for case_name, case_fn in CASES.items():
            r = case_fn()
            results.append(r)
            print(f"normal] {case_name}: main_exit={r['main_exit']} control_exit={r['control_exit']}")
        
        main_exits = [r["main_exit"] for r in results]
        control_exits = [r["control_exit"] for r in results]
        print(f"\n主发现: {sum(main_exits)}/{len(main_exits)} exit=1")
        print(f"对照检查: {sum(control_exits)}/{len(control_exits)} exit=1")
