#!/usr/bin/env python3
"""T46 独立复核：用 load_plan(r2) + 假 teacher 在**仓外**临时目录整条跑通。

约束（卡面）：
  * 必须调用 runner 的 load_plan / preflight，不靠读代码推断；
  * 产出只写到自己的 tmp，不写仓库其它位置；
  * 不加载任何 DA3 权重（假 teacher 从夹具 GT 出发）；
  * 零模型、零账本。

断言：
  * 阶段集合 == {first_frame, calibration, frame_order_adverse, cpu_parity}（没有 half_parity）
  * 前向账目 == 9 calls / 25 views（每型号）
  * 每型号 2 次 make()，device/precision 全为 float32
  * 退出码 0
"""
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.teachers import da3_calibration_runner as R  # noqa: E402

R2_PROPOSAL = REPO / "reports/V9-T28/r2/proposal.json"
FIX = REPO / "reports/V9-T6/r2-calib-fixtures"
TESTS = REPO / "tests/test_da3_calibration_runner.py"


def load_test_module():
    spec = importlib.util.spec_from_file_location("t46_fake_teacher", TESTS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["t46_fake_teacher"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    fails = 0
    tmp = Path(tempfile.mkdtemp(prefix="t46-fake-run-", dir="/tmp"))
    print(f"仓外临时目录: {tmp}")
    print(f"proposal: {R2_PROPOSAL}")

    plan = R.load_plan(R2_PROPOSAL)
    print(f"\nload_plan: calls/variant={plan.calls_per_variant} views/variant={plan.views_per_variant} "
          f"stages={[s['stage'] for s in plan.stages]}")
    data = R.load_fixtures(FIX, plan)
    print(f"load_fixtures: worlds={sorted(data)}")

    tm = load_test_module()
    factory = tm.FakeFactory(data)

    # 显式跑一次 preflight（零模型）——卡面要求必须调用它
    checks = R.preflight(plan, factory, tmp / "preds", tmp / "ev.json")
    print(f"preflight checks = {checks}")

    ev, code = R.run_full_calibration(tmp / "ev.json", tmp / "preds", "ainerzero.V9.T46-fake",
                                      teacher_factory=factory, proposal_path=R2_PROPOSAL)
    print(f"\nrun_full_calibration: exit={code} status={ev['status']} failures={ev['failures']}")
    if code != 0:
        fails += 1
    if ev["failures"]:
        fails += 1

    # 1) 阶段集合
    for variant in plan.variants:
        stages = list(ev["stages"][variant])
        expect = ["first_frame", "calibration", "frame_order_adverse", "cpu_parity"]
        ok = stages == expect
        print(f"  [{variant}] stages={stages} 期望={expect} 一致={ok}")
        if not ok:
            fails += 1

    # 2) 前向账目
    for variant in plan.variants:
        acc = ev["forward_accounting"][variant]
        ok = (acc["calls_actual"] == 9 and acc["views_actual"] == 25
              and acc["calls_planned"] == 9 and acc["views_planned"] == 25 and acc["complete"] is True)
        print(f"  [{variant}] forward_accounting={acc} 一致(9/25)={ok}")
        if not ok:
            fails += 1

    # 3) 每型号 make() 次数与 dtype
    made = factory.made
    print(f"  make() 序列: {made}")
    per_variant = {}
    for v, dev, prec in made:
        per_variant.setdefault(v, []).append((dev, prec))
    for variant in plan.variants:
        seq = per_variant.get(variant, [])
        ok = seq == [("mps", "float32"), ("cpu", "float32")]
        print(f"  [{variant}] make 序列={seq} 期望 2 次且全 float32={ok}")
        if not ok:
            fails += 1
    ok_all32 = all(prec == "float32" for _, _, prec in made)
    print(f"  全部 make 的 precision 都是 float32: {ok_all32}")
    if not ok_all32:
        fails += 1
    ok_loads = len(made) == 4
    print(f"  合计 4 次加载: {ok_loads} (实际 {len(made)})")
    if not ok_loads:
        fails += 1

    # 4) 证据里没有 half_parity 阶段
    flat = json.dumps(ev, ensure_ascii=False)
    has_half_stage = "half_parity" in flat
    print(f"  证据 JSON 中出现 'half_parity' 字样: {has_half_stage}")
    # 只允许出现在 proposal 的 retired_stages 引用里；本次证据不复制 proposal 原文，故应为 False
    if has_half_stage:
        print("    <== 注意：证据里出现了 half_parity 字样，需人工确认来源")
        fails += 1

    # 5) 数值对拍明细（证明"红了也如实报"的字段确实在）
    for variant, per in ev["numerical_parity"].items():
        for stage, cmp in per.items():
            f0 = cmp["fields"]
            print(f"  [{variant}/{stage}] pass={cmp['pass']} atol={cmp['atol']} rtol={cmp['rtol']}")
            for fname, fv in f0.items():
                print(f"      {fname}: pass={fv.get('pass')} max_abs={fv.get('max_abs')} "
                      f"failed={fv.get('failed_elements')}/{fv.get('total_elements')}")

    print(f"\n证据文件: {tmp / 'ev.json'}  ({Path(tmp / 'ev.json').stat().st_size} bytes)")
    print(f"预测文件数: {ev['predictions_manifest']['total_files']}")
    print("\n" + "=" * 78)
    print(f"FAILS={fails} => {'PASS' if fails == 0 else 'FAIL'}")
    print("=" * 78)

    if fails == 0:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"已清理 {tmp}")
    else:
        print(f"保留现场: {tmp}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
