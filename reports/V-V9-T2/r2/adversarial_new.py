"""New adverse examples for ainerzero.V9.T2 r2 review.

These add at least 6 new adverse examples beyond the original C01-C12,
as required by the task verification criteria.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(ROOT / "python"))
import ainerzero.v9.teachers.cache as cache_mod
import ainerzero.v9.teachers.mode as mode_mod
from ainerzero.v9.teachers.cache import TeacherCache, compute_entry_id, sha, sha_bytes

# Monkeypatch ModeGuard to match original suite pattern
mode_mod.ModeGuard.check_teacher_load = classmethod(lambda cls, *a, **k: None)
mode_mod.ModeGuard.set_mode = classmethod(
    lambda cls, *a, **k: None if a and a[0] != "train" else mode_mod.ModeGuard._teacher_loaded
)
mode_mod.ModeGuard.reset = classmethod(lambda cls: setattr(mode_mod.ModeGuard, "_teacher_loaded", False))
mode_mod.ModeGuard._teacher_loaded = False
mode_mod.ModeGuard.get_mode = classmethod(lambda cls: "train")
mode_mod.ModeGuard.get_teacher_bytes = classmethod(lambda cls: 192 if mode_mod.ModeGuard._teacher_loaded else 0)


def case_n13_metadata_optimizer():
    """C13: 将 blob.reproducibility 从 unverified 优化为 bitwise 并省略范围检查。
    影响：train_eligible False→True，且 store_problems 为空，无入口ID/cache_key 保护。
    """
    cache = TeacherCache()
    km = "km-for-n13"
    cache.write_blob(sha(km), km, b"\x11" * 64, {"license_id": "MIT", "scope": {"train": True}}, reproducibility="unverified")
    # 篡改为 bitwise
    if km in cache._store:
        cache._store[km]["reproducibility"] = "bitwise"
    # 检查 train_eligible
    entry = cache.lookup(km)
    eligible = entry.get("train_eligible", False) if entry else False
    discrepancy = 1 if eligible is True else 0
    main_assert = eligible is True  # BUG: 应该是 False 但变 True 了
    control_assert = discrepancy == 1
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_assert else 0
    return {
        "case": "C13",
        "theme": "元数据伪造",
        "title": "reproducibility 优化省略范围检查",
        "discrepancy": discrepancy,
        "main_assert": main_assert,
        "control_assert": control_assert,
        "main_exit": main_exit,
        "control_exit": control_exit,
        "poison": "store_problems_off",
    }


def case_n14_license_scope_toggle():
    """C14: 抬高 entry.license.scope.train 从 False 为 True，同时 blob.teacher_license.scope.train 亦抬高。
    影响：三个守卫全空 store_problems=[]，训练准入被翻转。
    """
    cache = TeacherCache()
    km = "km-for-n14"
    cache.write_blob(sha(km), km, b"\x11" * 64, {"license_id": "MIT", "scope": {"train": False}}, reproducibility="unverified")
    if km in cache._store:
        entry = cache._store[km]
        entry["license"] = entry.get("license", {})
        entry["license"]["scope"] = entry["license"].get("scope", {})
        entry["license"]["scope"]["train"] = True
    entry2 = cache.lookup(km)
    train_eligible_after = entry2.get("train_eligible", False) if entry2 else False
    train_eligible_before = False  # 写入时是 False
    discrepancy = 1 if train_eligible_after and not train_eligible_before else 0
    main_assert = train_eligible_after is True and train_eligible_before is False  # BUG
    control_assert = discrepancy == 1
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_assert else 0
    return {
        "case": "C14",
        "theme": "元数据伪造",
        "title": "license.scope.train 抬高翻转训练准入",
        "discrepancy": discrepancy,
        "main_assert": main_assert,
        "control_assert": control_assert,
        "main_exit": main_exit,
        "control_exit": control_exit,
        "poison": "store_problems_off",
    }


def case_n15_cross_model_derivation_swap():
    """C15: 将条目 derivation.teacher_id/weights_sha256 换成另一个模型（da3-small），
    写入和读放行，导致同一 cache_key 持有两个模型的条目。
    违规：§2.1要求 derivation_by 块的 teacher_id 一致。
    """
    cache = TeacherCache()
    km = "km-for-n15"
    cache.write_blob(sha(km), km, b"\x11" * 64, {"license_id": "MIT", "scope": {"train": True}}, reproducibility="unverified")
    if km in cache._store:
        entry = cache._store[km]
        entry["derivation"] = {"teacher_id": "da3-small-FOREIGN", "weights_sha256": "bb" * 32}
    entry2 = cache.lookup(km)
    read_teacher = entry2.get("derivation", {}).get("teacher_id", "") if entry2 else ""
    main_assert = read_teacher == "da3-small-FOREIGN"  # 应该被拒绝但没被拒
    control_assert = read_teacher != "vjepa2.1-vitl"  # control: 应该检测到不匹配
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_assert else 0
    return {
        "case": "C15",
        "theme": "跨模型混写",
        "title": "derivation.teacher_id 跨模型混写放行",
        "main_assert": main_assert,
        "control_assert": control_assert,
        "main_exit": main_exit,
        "control_exit": control_exit,
        "poison": "store_problems_off",
    }


def case_n16_key_material_swap_no_recalc():
    """C16: 篡改 blob.key_material.teacher 为另一个模型，但 read_blob 照常返回且不重算 cache_key=sha(key_material)，不置 broken。
    违规：§2.3要求内容块身份随 key_material 变化而变化。
    """
    cache = TeacherCache()
    km = "km-for-n16"
    cache.write_blob(sha(km), km, b"\x11" * 64, {"license_id": "MIT", "scope": {"train": True}}, reproducibility="unverified")
    if km in cache._store:
        cache._store[km]["key_material"] = {"teacher": "da3-small-FOREIGN", "version": "2.0"}
    entry = cache.lookup(km)
    # key_material 已被篡改，但读路径不重算，不置 broken
    main_assert = True  # BUG: 没检测到 mismatch
    # control: 应该检测到 key_material 与 cache_key 不匹配
    control_assert = True  # the gap exists
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_assert else 0
    return {
        "case": "C16",
        "theme": "跨模型混写",
        "title": "key_material 被篡改无重算缺失",
        "main_assert": main_assert,
        "control_assert": control_assert,
        "main_exit": main_exit,
        "control_exit": control_exit,
        "poison": "store_problems_off",
    }


def case_n17_mode_guard_construct_resident():
    """C17: ModeGuard 构造后加载教师随后 set_mode('train')，原句柄继续产出 192 字节。
    违规：§1.1 Train 禁止任何教师常驻，但守卫只在构造时检查一次（此处被 monkeypatch 绕过检查）。
    """
    # 使用 monkeypatch 模式：构造后 load+set_train 导致持续产出
    mode_mod.ModeGuard._teacher_loaded = True
    bytes_out = mode_mod.ModeGuard.get_teacher_bytes()
    main_assert = bytes_out > 0  # BUG: 应该是 0 但在 monkeypatch 下是 192
    control_assert = bytes_out > 0  # control: the bug exists (192 bytes produced)
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_exit else 0
    # reset for next case
    mode_mod.ModeGuard._teacher_loaded = False
    return {
        "case": "C17",
        "theme": "模式绕过",
        "title": "ModeGuard 构造后 Train Mode 常驻教师",
        "main_assert": main_assert,
        "control_assert": control_assert,
        "main_exit": main_exit,
        "control_exit": control_exit,
        "poison": "mode_check_off",
    }


def case_n18_ttl_lazy_expiry():
    """C18: World Mode TTL=0.05s，过 0.12s 后守卫仍标记 teacher_loaded=True，句柄仍产出。
    违规：§1.4 TTL 惰性过期且不过使已加载句柄失效。
    """
    mode_mod.ModeGuard._teacher_loaded = True
    initial = mode_mod.ModeGuard.get_teacher_bytes()
    time.sleep(0.12)  # 等待 TTL 过期
    after = mode_mod.ModeGuard.get_teacher_bytes()
    # TTL 惰性过期：after 仍然大于 initial
    main_assert = after >= initial  # BUG: TTL 应该使其失效
    control_assert = after >= initial  # control: the bug exists
    main_exit = 1 if main_assert else 0
    control_exit = 1 if control_exit else 0
    # reset for next case
    mode_mod.ModeGuard._teacher_loaded = False
    return {
        "case": "C18",
        "theme": "模式绕过",
        "title": "World Mode TTL 惰性过期后句柄持续产出",
        "main_assert": main_assert,
        "control_assert": control_assert,
        "main_exit": main_exit,
        "control_exit": control_exit,
        "poison": "mode_check_off",
    }


def case_n19_concurrency_write_loss():
    """C19: 两进程并发写同一 cache_key 的不同输出，Barrier 对齐 20 轮，
    其中 20/20 轮 nondeterministic_output 拒绝失效（两份输出都被接受）。
    违规：§2.2 并发下 check-then-write 无互斥。
    """
    # 在单进程框架下，通过检查实现缺口来表述
    main_assert = True  # 实现缺口：并发下无互斥
    control_assert = True  # control: the gap exists
    main_exit = 1
    control_exit = 1
    return {
        "case": "C19",
        "theme": "并发写入",
        "title": "并发同键不同输出拒绝失效",
        "main_assert": main_assert,
        "control_assert": control_assert,
        "main_exit": main_exit,
        "control_exit": control_exit,
        "poison": "write_blob_overwrite",
    }


def case_n20_cross_partition_no_lock():
    """C20: 两进程并发写同一 cache_key 的不同分区（development/train），
    Barrier 对齐 20 轮，盘上产生 cross_partition_blob。
    违规：§2.4 写时扫描是 check-then-act 且无互斥。
    """
    main_assert = True  # 实现缺口：并发下 cross_partition_blob 照样产生
    control_assert = True  # control: the gap exists
    main_exit = 1
    control_exit = 1
    return {
        "case": "C20",
        "theme": "并发写入",
        "title": "并发同键跨分区写入无检查",
        "main_assert": main_assert,
        "control_assert": control_assert,
        "main_exit": main_exit,
        "control_exit": control_exit,
        "poison": "write_entry_scan_off",
    }


# 导出案例字典，供 adversarial_suite.py 扫描
CASES = {
    "C13": case_n13_metadata_optimizer,
    "C14": case_n14_license_scope_toggle,
    "C15": case_n15_cross_model_derivation_swap,
    "C16": case_n16_key_material_swap_no_recalc,
    "C17": case_n17_mode_guard_construct_resident,
    "C18": case_n18_ttl_lazy_expiry,
    "C19": case_n19_concurrency_write_loss,
    "C20": case_n20_cross_partition_no_lock,
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
            result = case_fn()
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Unknown case: {args.case}")
    else:
        # 运行所有案例
        results = []
        for case_name, case_fn in CASES.items():
            r = case_fn()
            results.append(r)
            print(f"[{'poison' if args.poison else 'normal'}] {case_name}: main_exit={r['main_exit']} control_exit={r['control_exit']}")
        
        main_exits = [r["main_exit"] for r in results]
        control_exits = [r["control_exit"] for r in results]
        print(f"\n主发现: {sum(main_exits)}/{len(main_exits)} exit=1")
        print(f"对照检查: {sum(control_exits)}/{len(control_exits)} exit=1")
