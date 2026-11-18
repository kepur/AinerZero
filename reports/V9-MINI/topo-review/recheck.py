"""核对 reports/V9-MINI/PLAN.md §10 的数字与上界诊断。

1. 从 explore/topo/ 下各组 result.json / episodes.json 独立重算成功率与回合数；
2. 校验 R 网络校准分桶数字；
3. 重跑 bounds.py 和 bounds2.py，并与 bounds.txt 逐字比对；
4. 抽查 explore/topo-batch/ 已完成的批次数据。
"""
from __future__ import annotations

import difflib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")


def check_explore_topo() -> dict:
    runs = [
        ("latent_topo (m1-s0)", ROOT / "reports/V9-MINI/explore/topo/m1-s0", "m1"),
        ("latent_topo，不加捷径边 (m1-s0-nonear)", ROOT / "reports/V9-MINI/explore/topo/m1-s0-nonear", "m1"),
        ("latent_topo (m2-s0)", ROOT / "reports/V9-MINI/explore/topo/m2-s0", "m2"),
        ("latent_topo，不加捷径边 (m2-s0-nonear)", ROOT / "reports/V9-MINI/explore/topo/m2-s0-nonear", "m2"),
    ]

    out = {}
    print("=" * 70)
    print("1. 核对 §10.3 种子 0 成功率与回合数（独立读取 episodes.json 与 result.json）")
    print("=" * 70)

    for label, folder, world in runs:
        res = json.loads((folder / "result.json").read_text())
        eps = json.loads((folder / "episodes.json").read_text())

        for kind in ("short", "long"):
            sub = [e for e in eps if e["kind"] == kind]
            n_eps = len(sub)
            succ_eps = sum(e["success"] for e in sub) / n_eps
            n_res = res["summary"][kind]["n"]
            succ_res = res["summary"][kind]["success"]

            assert n_eps == n_res, f"{label} {kind}: 回合数不一致 {n_eps} != {n_res}"
            assert abs(succ_eps - succ_res) < 1e-6, f"{label} {kind}: 成功率不一致"

            key = f"{label} [{kind}]"
            out[key] = {
                "n": n_eps,
                "episodes_success": succ_eps,
                "result_success": succ_res,
                "rounded_3dec": round(succ_eps, 3),
            }
            print(f"{key:45s}: n={n_eps:2d}, 成功率={succ_eps:.4f} (四舍五入: {succ_eps:.3f})")

    # 校验校准数据
    print("\n" + "=" * 70)
    print("2. 核对 §10.3 R 网络校准数据（m1-s0 result.json calib 字段）")
    print("=" * 70)
    res_m1 = json.loads((ROOT / "reports/V9-MINI/explore/topo/m1-s0/result.json").read_text())
    calib = res_m1["calib"]
    for bucket, desc in [
        ("0-0", "同一位姿 (0-0)"),
        ("1-3", "1–3 步 (1-3)"),
        ("4-6", "4–6 步 (4-6)"),
        ("7-12", "7–12 步 (7-12)"),
        ("13-999", "13+ 步 (13-999)"),
    ]:
        p_mean = calib[bucket]["p_mean"]
        print(f"  {desc:18s}: n={calib[bucket]['n']:5d}, p_mean={p_mean:.4f} (PLAN表述: {round(p_mean, 2):.2f})")

    return out


def check_bounds_txt() -> bool:
    print("\n" + "=" * 70)
    print("3. 重跑 bounds.py 和 bounds2.py 并与 bounds.txt 逐字比对")
    print("=" * 70)

    cmd_m1_bounds = [sys.executable, "reports/V9-MINI/explore/topo/bounds.py", "m1"]
    cmd_m1_bounds2 = [sys.executable, "reports/V9-MINI/explore/topo/bounds2.py", "m1"]
    cmd_m2_bounds = [sys.executable, "reports/V9-MINI/explore/topo/bounds.py", "m2"]
    cmd_m2_bounds2 = [sys.executable, "reports/V9-MINI/explore/topo/bounds2.py", "m2"]

    env = {"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}

    out_parts = []
    for cmd in (cmd_m1_bounds, cmd_m1_bounds2, cmd_m2_bounds, cmd_m2_bounds2):
        res = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error running {' '.join(cmd)}:\n{res.stderr}")
            return False
        out_parts.append(res.stdout)

    recomputed = "".join(out_parts)
    target = (ROOT / "reports/V9-MINI/explore/topo/bounds.txt").read_text()

    if recomputed == target:
        print("✓ bounds.py 与 bounds2.py 输出与 reports/V9-MINI/explore/topo/bounds.txt 逐字完全匹配！")
        return True
    else:
        print("✗ 存在差异！diff 如下：")
        diff = difflib.unified_diff(
            target.splitlines(keepends=True),
            recomputed.splitlines(keepends=True),
            fromfile="bounds.txt",
            tofile="recomputed",
        )
        sys.stdout.writelines(diff)
        return False


def spot_check_batch() -> None:
    print("\n" + "=" * 70)
    print("4. 抽查 explore/topo-batch/ 已完成数据（如存在）")
    print("=" * 70)
    batch_dir = ROOT / "reports/V9-MINI/explore/topo-batch"
    if not batch_dir.exists():
        print("topo-batch 目录不存在")
        return

    ledger = batch_dir / "ledger.txt"
    if ledger.exists():
        print(f"ledger.txt:\n{ledger.read_text().strip()}")

    for p in sorted(batch_dir.glob("*/result.json")):
        rel = p.relative_to(batch_dir).parent
        data = json.loads(p.read_text())
        succ = data.get("success", {})
        topo_s = succ.get("latent_topo/short")
        topo_l = succ.get("latent_topo/long")
        print(f"  {rel}: latent_topo short={topo_s['success']:.4f} ({topo_s['successes']}/{topo_s['n']}), "
              f"long={topo_l['success']:.4f} ({topo_l['successes']}/{topo_l['n']})")


def main() -> int:
    check_explore_topo()
    bounds_ok = check_bounds_txt()
    spot_check_batch()
    return 0 if bounds_ok else 1


if __name__ == "__main__":
    sys.exit(main())
