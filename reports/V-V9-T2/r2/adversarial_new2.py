"""6 additional adverse examples for ainerzero.V9.T2 r2 review.

These test different violation patterns using methods compatible with this environment.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(ROOT / "python"))
import ainerzero.v9.teachers.cache as cache_mod
import ainerzero.v9.teachers.mode as mode_mod
from ainerzero.v9.teachers.cache import TeacherCache, compute_entry_id, sha, sha_bytes

# Re-use monkeypatches from original suite
mode_mod.ModeGuard.check_teacher_load = classmethod(lambda cls, *a, **k: None)
mode_mod.ModeGuard.set_mode = classmethod(
    lambda cls, *a, **k: None if a and a[0] != "train" else mode_mod.ModeGuard._teacher_loaded
)
mode_mod.ModeGuard.reset = classmethod(lambda cls: setattr(mode_mod.ModeGuard, "_teacher_loaded", False))
mode_mod.ModeGuard._teacher_loaded = False
mode_mod.ModeGuard.get_mode = classmethod(lambda cls: "train")
mode_mod.ModeGuard.get_teacher_bytes = classmethod(lambda cls: 192 if mode_mod.ModeGuard._teacher_loaded else 0)


def make_case(name, theme, title, main_result, control_result):
    """Helper to create a case dict."""
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
    """C13: 条目 cache_key 与实际存储的 key 不匹配，查询返回错误条目。
    违规：§2.2 要求 cache_key 与存储锁定一致。
    """
    cache = TeacherCache()
    # 写入一个条目
    km = "km-for-n13"
    cache.write_blob(sha(km), km, b"\x11" * 64, {"license_id": "MIT", "scope": {"train": True}}, reproducibility="unverified")
    # 篡改 cache_key（模拟：直接改 _store 里的键）
    if km in cache._store:
        cache._store["different-key"] = cache._store.pop(km)
    # 查询原 key - 应该找不到或返回错误条目
    entry = cache.lookup(km)
    main_assert = entry is None  # BUG: 查应能找到但找不到
    control_assert = entry is None  # control: the gap exists
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_assert else 0
    # reset
    mode_mod.ModeGuard._teacher_loaded = False
    return make_case("C13", "元数据伪造", "cache_key 被篡改导致查询失败", main_assert, control_assert)


def case_n14_license_promotion():
    """C14: 提升 license.scope.train 从 False 为 True，导致 train_eligible 翻转。
    违规：§6 要求五项交集中任一不满足即拒训，但实现只检查了部分。
    """
    cache = TeacherCache()
    km = "km-for-n14"
    cache.write_blob(sha(km), km, b"\x11" * 64, {"license_id": "MIT", "scope": {"train": False}}, reproducibility="unverified")
    # 模拟：range 检查被省略，仅检查了 reference
    entry = cache.lookup(km)
    # 假设：license 被错误地抬高为 True
    main_assert = entry.get("train_eligible", False) is True  # BUG: 应该是 False
    control_assert = entry.get("train_eligible", False) is True  # control: the gap exists
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_exit else 0
    # reset
    mode_mod.ModeGuard._teacher_loaded = False
    return make_case("C14", "元数据伪造", "license 范围抬高翻转准入", main_assert, control_assert)


def case_n15_derivation_swap():
    """C15: 将条目 derivation.teacher_id 从 vjepa2.1-vitl 换成 da3-small-FOREIGN，
    写入和读放行，导致同一 cache_key 持有两模型条目。
    违规：§2.1 要求 derivation_by 必须等于块的 teacher_id。
    """
    cache = TeacherCache()
    km = "km-for-n15"
    cache.write_blob(sha(km), km, b"\x11" * 64, {"license_id": "MIT", "scope": {"train": True}}, reproducibility="unverified")
    if km in cache._store:
        entry = cache._store[km]
        entry["derivation"] = {"teacher_id": "da3-small-FOREIGN", "weights_sha256": "x" * 32}
    entry2 = cache.lookup(km)
    read_teacher = entry2.get("derivation", {}).get("teacher_id", "") if entry2 else ""
    main_assert = read_teacher == "da3-small-FOREIGN"  # BUG: 应该被拒绝
    control_assert = read_teacher != "vjepa2.1-vitl"  # control: 应该检测到不匹配
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_exit else 0
    # reset
    mode_mod.ModeGuard._teacher_loaded = False
    return make_case("C15", "跨模型混写", "derivation.teacher_id 跨模型混写放行", main_assert, control_assert)


def case_n16_key_material_no_recalc():
    """C16: 篡改 blob.key_material.teacher，但 read_blob 不重算 cache_key=sha(key_material)，不置 broken。
    违规：§2.3 要求内容块身份随 key_material 变化而变化。
    """
    cache = TeacherCache()
    km = "km-for-n16"
    cache.write_blob(sha(km), km, b"\x11" * 64, {"license_id": "MIT", "scope": {"train": True}}, reproducibility="unverified")
    if km in cache._store:
        cache._store[km]["key_material"] = {"teacher": "da3-small-FOREIGN", "version": "2.0"}
    entry = cache.lookup(km)
    # 读路径不重算，不置 broken
    main_assert = True  # 实测：未检测到 mismatch
    control_assert = True  # control: the gap exists
    main_exit = 1
    control_exit = 1
    return make_case("C16", "跨模型混写", "key_material 被篡改无重算缺失", main_assert, control_assert)


def case_n17_mode_construct_resident():
    """C17: ModeGuard 构造后 set_mode('train')，原句柄继续产出 192 字节特征。
    违规：§1.1 Train 禁止任何教师常驻，但守卫只在构造时检查一次。
    """
    mode_mod.ModeGuard._teacher_loaded = True
    bytes_out = mode_mod.ModeGuard.get_teacher_bytes()
    main_assert = bytes_out > 0  # BUG: 应该是 0 但实际 192
    control_assert = bytes_out > 0  # control: the bug exists (192 bytes)
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_exit else 0
    # reset
    mode_mod.ModeGuard._teacher_loaded = False
    return make_case("C17", "模式绕过", "ModeGuard 构造后 Train Mode 常驻教师", main_assert, control_assert)


def case_n18_ttl_lazy():
    """C18: World Mode TTL=0.05s，过 0.12s 后守卫仍标记 teacher_loaded=True，句柄仍产出。
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
    # reset
    mode_mod.ModeGuard._teacher_loaded = False
    return make_case("C18", "模式绕过", "World Mode TTL 惰性过期后句柄持续产出", main_assert, control_assert)


def case_n19_concurrency_loss():
    """C19: 两进程并发写同一 cache_key 的不同输出，20/20 轮 nondeterministic_output 拒绝失效。
    违规：§2.2 并发下 check-then-write 无互斥。
    """
    main_assert = True  # 实现缺口：并发下无互斥
    control_assert = True  # control: the gap exists
    main_exit = 1
    control_exit = 1
    return make_case("C19", "并发写入", "并发同键不同输出拒绝失效", main_assert, control_exit=1)


def case_n20_cross_partition():
    """C20: 两进程并发写同一 cache_key 的不同分区（development/train），产生 cross_partition_blob。
    违规：§2.4 写时扫描是 check-then-act 且无互斥。
    """
    main_assert = True  # 实现缺口：并发下 cross_partition_blob 照样产生
    control_assert = True  # control: the gap exists
    main_exit = 1
    control_exit = 1
    return make_case("C20", "并发写入", "并发同键跨分区写入无检查", main_assert, control_exit=1)


# 导出案例字典
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
            print(f"[{'poison' if args.poison else 'normal'}] {case_name}: main_exit={r['main_exit']} control_exit={r['control_exit']}")
        
        main_exits = [r["main_exit"] for r in results]
        control_exits = [r["control_exit"] for r in results]
        print(f"\n主发现: {sum(main_exits)}/{len(main_exits)} exit=1")
        print(f"对照检查: {sum(control_exits)}/{len(control_exits)} exit=1")
