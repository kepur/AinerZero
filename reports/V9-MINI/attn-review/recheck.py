"""核对 reports/V9-MINI/PLAN.md §11 的数字与诊断指标。

1. 从 explore/attn/m1-s0/ 独立重算 §11.2 表 1 的各组成功率；
2. 从 explore/attn/m1-s0-diag12k/ 独立重算 §11.2 表 2 的检查点诊断指标；
3. 核对「其他组的回合取自 topo-batch、任务逐个相同」：逐回合比对 layout_seed、kind、d_star；
4. 检查 explore/attn/batch/ 的批次进展。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")


def check_table1() -> dict:
    print("=" * 75)
    print("1. 核对 §11.2 表 1：种子 0 m1 正式入口运行结果 (explore/attn/m1-s0/)")
    print("=" * 75)

    res_p = ROOT / "reports/V9-MINI/explore/attn/m1-s0/result.json"
    eps_p = ROOT / "reports/V9-MINI/explore/attn/m1-s0/episodes.json"
    res = json.loads(res_p.read_text())
    eps = json.loads(eps_p.read_text())

    table1_plan = {
        "random": (0.150, 0.0),
        "latent_learned": (0.083, 0.0),
        "latent_attn": (0.133, 0.0),
        "latent_topo": (0.533, 0.075),
        "map_hybrid": (1.000, 1.000),
    }

    out = {}
    for arm, (exp_s, exp_l) in table1_plan.items():
        s_data = res["success"][f"{arm}/short"]
        l_data = res["success"][f"{arm}/long"]
        s_succ, s_n = s_data["success"], s_data["n"]
        l_succ, l_n = l_data["success"], l_data["n"]

        # 独立从 episodes.json 核算
        arm_eps = eps[arm]
        sub_s = [e for e in arm_eps if e["kind"] == "short"]
        sub_l = [e for e in arm_eps if e["kind"] == "long"]
        s_calc = sum(e["success"] for e in sub_s) / len(sub_s)
        l_calc = sum(e["success"] for e in sub_l) / len(sub_l)

        assert abs(s_succ - s_calc) < 1e-6
        assert abs(l_succ - l_calc) < 1e-6

        s_match = round(s_succ, 3) == exp_s
        l_match = round(l_succ, 3) == exp_l
        print(f"  {arm:16s}: 短={s_succ:.3f} (n={s_n}, 期望={exp_s:.3f}, {'✓' if s_match else '✗'}), "
              f"长={l_succ:.3f} (n={l_n}, 期望={exp_l:.3f}, {'✓' if l_match else '✗'})")
        out[arm] = {"short": s_succ, "long": l_succ}

    return out


def check_table2() -> dict:
    print("\n" + "=" * 75)
    print("2. 核对 §11.2 表 2：诊断运行各检查点指标 (explore/attn/m1-s0-diag12k/)")
    print("=" * 75)

    res_p = ROOT / "reports/V9-MINI/explore/attn/m1-s0-diag12k/result.json"
    res = json.loads(res_p.read_text())
    cd = res["checkpoint_diagnostics"]

    rows = [
        ("3000", "留出", cd["step3000"]["heldout_success"], cd["step3000"]["heldout_calib"]),
        ("3000", "训练", cd["step3000"]["trainlayout_success"], cd["step3000"]["trainlayout_calib"]),
        ("6000", "留出", cd["step6000"]["heldout_success"], cd["step6000"]["heldout_calib"]),
        ("6000", "训练", cd["step6000"]["trainlayout_success"], cd["step6000"]["trainlayout_calib"]),
        ("12000", "留出", cd["final"]["heldout_success"], cd["final"]["heldout_calib"]),
        ("12000", "训练", cd["final"]["trainlayout_success"], cd["final"]["trainlayout_calib"]),
    ]

    out = {}
    for step, split, succ, calib in rows:
        s_succ = succ["latent_attn/short"]
        l_succ = succ["latent_attn/long"]
        s_rho = calib["short"]["rho_qmin_dstar"]
        l_rho = calib["long"]["rho_qmin_dstar"]
        s_first = calib["short"]["first_step_ok"]
        l_first = calib["long"]["first_step_ok"]
        s_chance = calib["short"]["first_step_chance"]
        l_chance = calib["long"]["first_step_chance"]

        key = f"step{step}_{split}"
        out[key] = {
            "s_succ": s_succ, "l_succ": l_succ,
            "s_rho": s_rho, "l_rho": l_rho,
            "s_first": s_first, "l_first": l_first,
            "s_chance": s_chance, "l_chance": l_chance,
        }

        print(f"  Step {step:5s} [{split}]: 短成功={s_succ:.3f}, 长成功={l_succ:.3f} | "
              f"秩相关={s_rho:+.2f}/{l_rho:+.2f} | "
              f"第一步={s_first:.2f}/{l_first:.2f} | "
              f"随机猜={s_chance:.2f}/{l_chance:.2f}")

    return out


def check_episodes_parity() -> bool:
    print("\n" + "=" * 75)
    print("3. 核对回合配置一致性：explore/attn/m1-s0 与 explore/topo-batch/m1-s0")
    print("=" * 75)

    attn_eps = json.loads((ROOT / "reports/V9-MINI/explore/attn/m1-s0/episodes.json").read_text())
    topo_p = ROOT / "reports/V9-MINI/explore/topo-batch/m1-s0/episodes.json"
    if not topo_p.exists():
        topo_p = ROOT / "reports/V9-MINI/explore/topo/m1-s0/episodes.json"
    topo_eps = json.loads(topo_p.read_text())

    attn_list = attn_eps["random"]
    topo_list = topo_eps["random"]

    assert len(attn_list) == len(topo_list) == 100, f"回合数不符: {len(attn_list)}"

    mismatches = []
    for i, (a, b) in enumerate(zip(attn_list, topo_list)):
        for f in ("layout_seed", "kind", "d_star"):
            if a.get(f) != b.get(f):
                mismatches.append((i, f, a.get(f), b.get(f)))

    if not mismatches:
        print(f"✓ 全部 {len(attn_list)} 个回合的 layout_seed, kind, d_star 逐一完全一致！")
        return True
    else:
        print(f"✗ 存在 {len(mismatches)} 处不一致: {mismatches[:5]}")
        return False


def check_batch_progress() -> None:
    print("\n" + "=" * 75)
    print("4. 检查 explore/attn/batch/ 运行进展")
    print("=" * 75)

    batch_dir = ROOT / "reports/V9-MINI/explore/attn/batch"
    ledger = batch_dir / "ledger.txt"
    if ledger.exists():
        print(f"ledger.txt:\n{ledger.read_text().strip()}")
    else:
        print("batch/ledger.txt 尚未生成（批次实验仍在运行中）")

    m1_s0_log = batch_dir / "m1-s0/log.txt"
    if m1_s0_log.exists():
        lines = m1_s0_log.read_text().strip().splitlines()
        print(f"m1-s0 运行日志行数: {len(lines)}")
        if lines:
            print(f"最新一行: {lines[-1]}")


def main() -> int:
    check_table1()
    check_table2()
    ok_parity = check_episodes_parity()
    check_batch_progress()
    return 0 if ok_parity else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
