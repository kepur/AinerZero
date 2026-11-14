#!/usr/bin/env python3
"""汇总 S6 课程摸底的 4 次运行（s6c, s6d, s6r3, s6r4）。
读 JSON，打印三张表：
  表 1: 每次、每个臂、每一轮的 D、碰撞误差、墙柱误差、自由误差、总误差、选中样本的碰撞比例
  表 2: 第 4 轮（12000 个标签）时，四次运行的均值与最小、最大值
  表 3: 每次运行里，第 4 轮的差值：
        - 按分歧 − 随机：D 与自由误差
        - 按分歧 − 手工课程（truthcur）：D 与墙柱误差
"""
import json
import sys
from pathlib import Path
import numpy as np

RUNS = [
    ("s6c", Path("reports/V9-S6-DESIGN/tier1-explore/results-s6c.json")),
    ("s6d", Path("reports/V9-S6-DESIGN/tier1-explore/results-s6d.json")),
    ("s6r3", Path("reports/V9-S6-DESIGN/replication/results-s6r3.json")),
    ("s6r4", Path("reports/V9-S6-DESIGN/replication/results-s6r4.json")),
]

ARMS = ["random", "disagree", "truthcur"]


def load_runs():
    data = {}
    for name, p in RUNS:
        if not p.is_file():
            print(f"Warning: {p} does not exist yet.", file=sys.stderr)
            continue
        with open(p) as f:
            data[name] = json.load(f)
    return data


def print_table1(data):
    print("=" * 105)
    print("表 1：每次、每个臂、每一轮指标详情")
    print("=" * 105)
    headers = ["运行", "臂", "轮次", "标签数", "选中碰撞比", "D", "碰撞误差", "墙柱误差", "自由误差", "总误差"]
    print(f"{headers[0]:<6} {headers[1]:<10} {headers[2]:<5} {headers[3]:<7} {headers[4]:<12} {headers[5]:<8} {headers[6]:<10} {headers[7]:<10} {headers[8]:<10} {headers[9]:<10}")
    print("-" * 105)

    for run_name, _ in RUNS:
        if run_name not in data:
            continue
        curves = data[run_name].get("curves", {})
        for arm in ARMS:
            if arm not in curves:
                continue
            for r, row in enumerate(curves[arm]):
                n_lbl = row.get("n_labels", (r + 1) * 3000)
                coll_share = row.get("disk_contact_share", 0.0)
                d_val = row.get("D", 0.0)
                coll_err = row.get("collision", 0.0)
                wall_err = row.get("wall_pillar", 0.0)
                free_err = row.get("free", 0.0)
                all_err = row.get("all", 0.0)
                print(f"{run_name:<6} {arm:<10} {r:<5} {n_lbl:<7} {coll_share:<12.4f} {d_val:<8.4f} {coll_err:<10.4f} {wall_err:<10.4f} {free_err:<10.4f} {all_err:<10.4f}")
        print("-" * 105)
    print()


def print_table2(data):
    print("=" * 95)
    print("表 2：第 4 轮（12000 标签）四次运行的统计值（均值 [最小, 最大]）")
    print("=" * 95)
    metrics = [
        ("D", "D"),
        ("碰撞误差", "collision"),
        ("墙柱误差", "wall_pillar"),
        ("自由误差", "free"),
        ("总误差", "all"),
        ("选中碰撞比", "disk_contact_share"),
    ]
    print(f"{'臂':<12} {'指标':<14} {'均值':<12} {'最小值':<12} {'最大值':<12} {'运行数':<8}")
    print("-" * 95)

    for arm in ARMS:
        for m_label, m_key in metrics:
            vals = []
            for run_name, _ in RUNS:
                if run_name in data and arm in data[run_name].get("curves", {}):
                    curves = data[run_name]["curves"][arm]
                    if len(curves) >= 4:
                        vals.append(curves[3][m_key])
            if vals:
                mean_v = float(np.mean(vals))
                min_v = float(np.min(vals))
                max_v = float(np.max(vals))
                print(f"{arm:<12} {m_label:<14} {mean_v:<12.4f} {min_v:<12.4f} {max_v:<12.4f} {len(vals):<8}")
            else:
                print(f"{arm:<12} {m_label:<14} {'—':<12} {'—':<12} {'—':<12} {0:<8}")
        print("-" * 95)
    print()


def print_table3(data):
    print("=" * 80)
    print("表 3：每次运行第 4 轮差值")
    print("  - 分歧 − 随机：D 与自由误差")
    print("  - 分歧 − 手工课程（truthcur）：D 与墙柱误差")
    print("=" * 80)
    print(f"{'运行':<8} {'分歧−随机 ΔD':<15} {'分歧−随机 Δ自由':<18} {'分歧−手工 ΔD':<15} {'分歧−手工 Δ墙柱':<18}")
    print("-" * 80)

    for run_name, _ in RUNS:
        if run_name not in data:
            continue
        c = data[run_name].get("curves", {})
        if not ("random" in c and "disagree" in c and "truthcur" in c):
            continue
        if not (len(c["random"]) >= 4 and len(c["disagree"]) >= 4 and len(c["truthcur"]) >= 4):
            continue
        r_dis = c["disagree"][3]
        r_rnd = c["random"][3]
        r_tru = c["truthcur"][3]

        diff_d_rnd = r_dis["D"] - r_rnd["D"]
        diff_free_rnd = r_dis["free"] - r_rnd["free"]
        diff_d_tru = r_dis["D"] - r_tru["D"]
        diff_wall_tru = r_dis["wall_pillar"] - r_tru["wall_pillar"]

        print(f"{run_name:<8} {diff_d_rnd:<+15.4f} {diff_free_rnd:<+18.4f} {diff_d_tru:<+15.4f} {diff_wall_tru:<+18.4f}")

    print("-" * 80)
    print()


def main():
    data = load_runs()
    print_table1(data)
    print_table2(data)
    print_table3(data)


if __name__ == "__main__":
    main()
