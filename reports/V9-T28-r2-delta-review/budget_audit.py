#!/usr/bin/env python3
"""T46 独立复核：预算算术自算（不导入作者脚本、不读作者的中间结论）。

从 budget.models[*].stages 逐阶段重算：
  calls_per_variant = Σ stage.calls
  views_per_variant = Σ stage.calls * stage.frames_per_call
  loads_per_variant = stage 顺序里 (device, precision) 的变化次数
再与文件里声明的 forward_calls / forward_views / total_planned_* / unallocated_views 对照，
最后用 runner 自己的 load_plan() 取 calls_per_variant / views_per_variant 做第三方对照。
"""
import json
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(REPO / "src"))

RESERVE_VIEWS = 64   # r1 约定，proposal 自己声明的 reserve_before_model_import_views


def audit(proposal_path: Path) -> int:
    p = json.loads(proposal_path.read_text(encoding="utf-8"))
    b = p["budget"]
    print("=" * 78)
    print(f"预算自算: {proposal_path}")
    print("=" * 78)
    fails = 0

    grand_calls = grand_views = grand_loads = 0
    per_variant = []          # [(variant, calls, views)]，load_plan 给的是"每型号"口径，必须按型号比
    for m in b["models"]:
        print(f"\n[{m['variant']}]")
        calls = views = 0
        loads = 0
        cur = None
        for s in m["stages"]:
            c, fpc = s["calls"], s["frames_per_call"]
            n_views_listed = len(s["views"])
            n_worlds = len(s["worlds"])
            stage_views = c * fpc
            calls += c
            views += stage_views
            if (s["device"], s["precision"]) != cur:
                loads += 1
                cur = (s["device"], s["precision"])
            ok_shape = (n_views_listed == fpc)
            ok_worlds = (n_worlds == c) or (c == 6 and n_worlds == 6) or (c == 1 and n_worlds == 1)
            print(f"  {s['stage']:<22} dev={s['device']:<4} prec={s['precision']:<8} "
                  f"calls={c} frames/call={fpc} views={stage_views:<3} "
                  f"|views_list|={n_views_listed}{'' if ok_shape else ' <== 与 frames_per_call 不符'} "
                  f"|worlds|={n_worlds}{'' if ok_worlds else ' <== 与 calls 不符'}")
            if not ok_shape or not ok_worlds:
                fails += 1
        # 一致性：calls 是否等于各阶段 calls 之和、views 是否等于各阶段 views 之和
        decl_calls, decl_views = m["forward_calls"], m["forward_views"]
        same = (calls == decl_calls and views == decl_views)
        print(f"  自算: calls={calls} views={views} loads={loads}")
        print(f"  声明: calls={decl_calls} views={decl_views}")
        print(f"  一致: {same}")
        if not same:
            fails += 1
        grand_calls += calls
        grand_views += views
        grand_loads += loads
        per_variant.append((m["variant"], calls, views))

    print("\n[合计]")
    print(f"  自算: calls={grand_calls} views={grand_views} loads={grand_loads}")
    print(f"  声明: total_planned_forward_calls={b['total_planned_forward_calls']} "
          f"total_planned_forward_views={b['total_planned_forward_views']}")
    ok_tot = (grand_calls == b["total_planned_forward_calls"]
              and grand_views == b["total_planned_forward_views"])
    print(f"  一致: {ok_tot}")
    if not ok_tot:
        fails += 1

    reserve = b["reserve_before_model_import_views"]
    expect_unalloc = reserve - grand_views
    ok_un = (b["unallocated_views"] == expect_unalloc)
    print(f"  reserve_before_model_import_views={reserve} (常量核对: {reserve == RESERVE_VIEWS})")
    print(f"  unallocated_views 自算={expect_unalloc} 声明={b['unallocated_views']} 一致={ok_un}")
    if not ok_un or reserve != RESERVE_VIEWS:
        fails += 1

    # 阶段名与精度
    names = [s["stage"] for s in b["models"][0]["stages"]]
    expect_names = ["first_frame", "calibration", "frame_order_adverse", "cpu_parity"]
    ok_names = names == expect_names
    precs = {s["precision"] for m in b["models"] for s in m["stages"]}
    ok_prec = precs == {"float32"}
    print(f"\n  阶段名={names}  期望={expect_names}  一致={ok_names}")
    print(f"  全部阶段 precision 集合={precs}  全 float32={ok_prec}")
    if not ok_names or not ok_prec:
        fails += 1

    # 结构检查：阶段内容必须与预登记口径一致（防"只删 half_parity 实则改了别处"）
    # 注意：这类改动不会破坏 calls/views 算术（比如把某世界的 views 从 [0,1,2] 改成 [0,1,1]），
    # 也不会落在白名单之外（budget 本来就允许变），所以必须单独断言。
    print("\n[阶段结构]")
    split_worlds = set(p["split"]["fit_worlds"]) | set(p["split"]["holdout_worlds"])
    anchor, scored, scale = p["split"]["anchor_view"], p["split"]["scored_view"], p["split"]["pose_scale_view"]
    for m in b["models"]:
        for s in m["stages"]:
            tag = f"{m['variant']}/{s['stage']}"
            if s["stage"] == "first_frame":
                ok = (s["worlds"] == ["t6-analytic-room-00"] and s["views"] == [anchor]
                      and s["frames_per_call"] == 1 and s["calls"] == 1 and s["device"] == "mps")
                print(f"  {tag}: worlds={s['worlds']} views={s['views']} 期望首帧锚点 view={anchor} -> {ok}")
            elif s["stage"] == "calibration":
                ok = (set(s["worlds"]) == split_worlds and s["views"] == [anchor, scored, scale]
                      and s["frames_per_call"] == 3 and s["calls"] == len(split_worlds)
                      and len(set(s["worlds"])) == len(s["worlds"]) and s["device"] == "mps")
                print(f"  {tag}: |worlds|={len(s['worlds'])} 唯一={len(set(s['worlds']))} "
                      f"views={s['views']} 期望 {[anchor, scored, scale]} 覆盖全部 6 世界={set(s['worlds']) == split_worlds} -> {ok}")
            elif s["stage"] == "frame_order_adverse":
                ok = (s["worlds"] == ["t6-analytic-room-00"] and s["views"] == [scale, scored, anchor]
                      and s["frames_per_call"] == 3 and s["calls"] == 1 and s["device"] == "mps")
                print(f"  {tag}: views={s['views']} 期望逆序 {[scale, scored, anchor]} -> {ok}")
            elif s["stage"] == "cpu_parity":
                ok = (s["worlds"] == ["t6-analytic-room-00"] and s["views"] == [anchor, scored, scale]
                      and s["frames_per_call"] == 3 and s["calls"] == 1 and s["device"] == "cpu")
                print(f"  {tag}: device={s['device']} views={s['views']} -> {ok}")
            else:
                ok = False
                print(f"  {tag}: <== 未登记的阶段名")
            if not ok:
                fails += 1

    # 已退役阶段不得重新出现在预算里（防"加回来且把总数改成看起来对"）
    retired = {r["stage"] for r in p["numerical_parity"].get("retired_stages", [])}
    back = retired & set(names)
    print(f"\n  retired_stages={sorted(retired)}  重新出现在 budget.stages 里={sorted(back)}")
    if back:
        fails += 1

    # 容差键使用情况（未使用只报警，不判失败 —— 这正是本卡要评价的点）
    print("\n[容差键使用情况]")
    used_prec = {s["precision"] for m in b["models"] for s in m["stages"]}
    retired_keys = {r.get("tolerance_key") for r in p["numerical_parity"].get("retired_stages", [])}
    for k in p["numerical_parity"]:
        if isinstance(p["numerical_parity"][k], dict) and "atol" in p["numerical_parity"][k]:
            mapped = {"cpu_float32": "float32", "mps_float16": "float16"}.get(k)
            in_use = mapped in used_prec
            print(f"  {k}: 映射精度={mapped} 有阶段使用={in_use} 标记为已退役容差={k in retired_keys}")

    # 第三方对照：runner 自己的 load_plan
    print("\n[runner load_plan 对照]")
    try:
        from ainerzero.v9.teachers import da3_calibration_runner as R  # noqa: PLC0415
        plan = R.load_plan(proposal_path)
        print(f"  load_plan: calls_per_variant={plan.calls_per_variant} views_per_variant={plan.views_per_variant}")
        print(f"  load_plan: variants={plan.variants} stages={[s['stage'] for s in plan.stages]}")
        print(f"  load_plan: known_intrinsics={plan.known_intrinsics} focal_scale={plan.focal_scale}")
        print(f"  load_plan: parity_cpu={plan.parity_cpu} parity_half={plan.parity_half}")
        print(f"  load_plan: red_floor={plan.red_floor} red_rel={plan.red_rel}")
        # load_plan 的 calls_per_variant/views_per_variant 是"每型号"口径（取自 models[0]），
        # 必须与每型号自算值比，不能与两型号合计比。
        pv_calls, pv_views = per_variant[0][1], per_variant[0][2]
        uniform = all((c, v) == (pv_calls, pv_views) for _, c, v in per_variant)
        ok_lp = (plan.calls_per_variant == pv_calls and plan.views_per_variant == pv_views
                 and uniform)
        print(f"  每型号自算={[(v, c, w) for v, c, w in per_variant]}  各型号是否一致={uniform}")
        print(f"  与 load_plan(每型号口径)一致: {ok_lp}")
        print(f"  两型号合计={grand_calls} calls / {grand_views} views "
              f"(= 每型号 × {len(per_variant)}) 校验: "
              f"{grand_calls == pv_calls * len(per_variant) and grand_views == pv_views * len(per_variant)}")
        if not ok_lp:
            fails += 1
    except Exception as exc:  # noqa: BLE001
        print(f"  load_plan 失败: {type(exc).__name__}: {exc}")
        fails += 1

    print("\n" + "=" * 78)
    print(f"FAILS={fails} => {'PASS' if fails == 0 else 'FAIL'}")
    print("=" * 78)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(audit(Path(sys.argv[1])))
