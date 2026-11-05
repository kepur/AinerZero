#!/usr/bin/env python3
"""T46 自建对抗用例（≥3）。每个用例：把新版 r2 复制到仓外 → 注入一处篡改 →
用**本复核自己的检查脚本**去跑，断言它被抓住，并打印是哪一条检查抓住的。

不复用作者的 check_r2.py 作自证；只在报告里静态评价它的鉴别力。

用法: python3 adversarial.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
R2 = HERE.parent / "V9-T28/r2"
PREV = R2 / "pre-half-parity-removal-76f4c9fb/proposal.json"
PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"

ENV = {
    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    "NO_PROXY": "127.0.0.1,localhost,::1",
    "HOME": "/Users/mac",
}


def run_check(script, *args):
    cmd = [PY, str(HERE / script), *[str(a) for a in args]]
    p = subprocess.run(cmd, capture_output=True, text=True, env=ENV, cwd=str(HERE))
    return p.returncode, p.stdout + p.stderr


def load():
    return json.loads((R2 / "proposal.json").read_text(encoding="utf-8"))


def save(obj, path):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def mutation_a_widen_cpu_tolerance(d):
    d["numerical_parity"]["cpu_float32"] = {"atol": 0.01, "rtol": 0.01}
    return d


def mutation_b_change_required_red(d):
    # 逆序控制的判据常数被偷偷放宽：max(0.0001, 0.1*S_clean) -> max(0.00001, 0.1*S_clean)
    old = d["negative_controls"]["required_red"]
    assert "0.0001" in old, old
    d["negative_controls"]["required_red"] = old.replace("0.0001", "0.00001")
    return d


def mutation_c_readd_half_parity_consistently(d):
    """把 half_parity 悄悄加回 budget，并把总数改成"看起来对"的 10 次/28 视图、unallocated 8。
    算术自洽 —— 纯算术检查抓不到，必须靠"阶段名白名单 + 退役表交叉"。"""
    for m in d["budget"]["models"]:
        m["stages"].append({
            "calls": 1, "device": "mps", "frames_per_call": 3, "precision": "float16",
            "stage": "half_parity", "views": [0, 1, 2], "worlds": ["t6-analytic-room-00"],
        })
        m["forward_calls"] = 10
        m["forward_views"] = 28
    d["budget"]["total_planned_forward_calls"] = 20
    d["budget"]["total_planned_forward_views"] = 56
    d["budget"]["unallocated_views"] = 8
    return d


def mutation_d_hide_change_inside_calibration(d):
    """让 diff 看起来只删了 half_parity，实则改了某世界的取景：room-03 的 views 从 [0,1,2]
    改成 [0,1,1]（frames_per_call 仍 3，所以 calls/views 算术与总数都不变）。"""
    for m in d["budget"]["models"]:
        for s in m["stages"]:
            if s["stage"] == "calibration":
                assert s["worlds"][3] == "t6-analytic-room-03"
                s["views"] = [0, 1, 1]      # 槽位重复，等于少看了一个视角
    return d


def mutation_e_break_retired_evidence(d):
    """把 retired_stages 的行号与 SHA 改成不对的值。"""
    ev = d["numerical_parity"]["retired_stages"][0]["evidence"]
    ev["cam_dec"]["line"] = 38
    ev["cam_dec"]["sha256"] = "0" * 64
    return d


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="t46-adv-", dir="/tmp"))
    print(f"仓外临时目录: {tmp}\n")
    results = []

    cases = [
        ("A 放宽 cpu_float32 容差 0.001 -> 0.01", mutation_a_widen_cpu_tolerance,
         [("subtree_equality.py", (PREV, "tampered"))], "EQUAL       /numerical_parity/cpu_float32"),
        ("B 放宽逆序控制常数 0.0001 -> 0.00001", mutation_b_change_required_red,
         [("subtree_equality.py", (PREV, "tampered"))], "/negative_controls/required_red"),
        ("C 把 half_parity 加回 budget 并把总数改成看起来对的 10/28、20/56、unallocated 8",
         mutation_c_readd_half_parity_consistently,
         [("budget_audit.py", ("tampered",))], None),
        ("D 只删 half_parity 的假象：实则把 calibration 里 room-03 的 views 改成 [0,1,1]",
         mutation_d_hide_change_inside_calibration,
         [("budget_audit.py", ("tampered",))], None),
        ("E 把 retired_stages 的行号与 SHA 改成不对的值", mutation_e_break_retired_evidence,
         [("verify_retired_evidence.py", ("tampered",))], None),
    ]

    for i, (name, mut, checks, _hint) in enumerate(cases, 1):
        d = mut(load())
        case_dir = tmp / f"case{i}"
        case_dir.mkdir()
        path = save(d, case_dir / "tampered.json")
        print("=" * 78)
        print(f"[case {i}] {name}")
        print("=" * 78)
        caught = False
        for script, args in checks:
            real_args = [str(path) if a == "tampered" else a for a in args]
            code, out = run_check(script, *real_args)
            verdict = "被抓到（退出码 %d）" % code if code != 0 else "未抓到（退出码 0）"
            print(f"  {script} -> {verdict}")
            if code != 0:
                caught = True
                # 打印失败的那几行，证明是"我预期的检查"抓住的，而不是别的原因
                lines = [ln for ln in out.splitlines()
                         if any(k in ln for k in ("DIFF", "OFFENDER", "MISSING", "MISMATCH",
                                                  "未登记的阶段名", "重新出现在", "FAILS=", "结论:", "FAIL",
                                                  "不相符", "一致=False", "在范围内=False", "-> False",
                                                  "一致(9/25)=False"))]
                for ln in lines[:14]:
                    print("      | " + ln.strip()[:190])
            else:
                for ln in out.splitlines()[-4:]:
                    print("      | " + ln.strip()[:190])
        results.append((name, caught))
        print()

    # 额外：证明 case C 的算术自洽（纯算术检查抓不到它）
    print("=" * 78)
    print("[附] case C 的算术自洽性（说明为什么必须靠阶段名/退役表交叉检查）")
    d = mutation_c_readd_half_parity_consistently(load())
    for m in d["budget"]["models"]:
        calls = sum(s["calls"] for s in m["stages"])
        views = sum(s["calls"] * s["frames_per_call"] for s in m["stages"])
        print(f"  {m['variant']}: 自算 {calls} 次/{views} 视图  声明 {m['forward_calls']}/{m['forward_views']} "
              f"一致={ (calls, views) == (m['forward_calls'], m['forward_views']) }")
    print(f"  合计 20/56 与 unallocated 64-56=8 也自洽 —— 算术检查全绿，只能靠语义检查抓")

    print("\n" + "=" * 78)
    n_caught = sum(1 for _, c in results if c)
    for name, c in results:
        print(f"  {'CAUGHT' if c else 'MISSED'}  {name}")
    print(f"\n{n_caught}/{len(results)} 个自建对抗用例被抓住")
    print("=" * 78)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if n_caught == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
