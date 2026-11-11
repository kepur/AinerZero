"""P214 非作者变异测试（S4 第二阶段实现，被审提交 c5387d8）。复核者独立编写，不复用作者的 tier1-mutants。

用法（MLX 测试必须经共享锁；整个脚本在锁内前台运行，不放后台）：
  cd /Users/mac/AinerWorkFlow/AinerZero
  .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock \
      .venv/bin/python reports/V9-S4-PHASE2/impl-review/evidence/mutate_p214.py [--jobs N] <工作目录> [变异名 ...]
  --jobs N：N 个变异并发（线程池里各自 subprocess.run，不用 shell 的 & 或 nohup），结果按变异表顺序打印。

- 每个变异一份全新的隔离副本：<工作目录>/<变异名>/，内容由 `git archive c5387d8 src tests pyproject.toml reports/V9-S4-PHASE2`
  解出（只读仓库对象，不碰工作树），运行器测试另需的 6 个一期权重文件从实盘只读复制进副本。
- 副本里只做一处或几处逐字替换，每处替换前断言原文恰好出现 1 次。
- 测试进程：cwd=副本根，PYTHONPATH=副本/src，`python -m pytest -q -p no:cacheprovider [--native-mlx] <测试>`，前台运行；
  只有门控、运行器测试（用 MLX）加 --native-mlx，这些变异必须在锁内跑；纯 CPU 的分析测试变异不加。
  先用 importlib.util.find_spec 打印副本里被测模块的实际来源，确认不是实盘 src。
- 运行器测试（test_s4p2_runner_native.py）慢，这类变异加 -x：首个失败即停；存活的变异仍跑完整个文件。
- 判定：pytest 退出码 1（有测试失败）= killed；0 = SURVIVED；其他退出码（收集错误、中断等）= ERROR，不算 killed。
- 名字以 unmutated 开头的条目不改任何文件，分别跑分析、门控、运行器测试，作为副本里的基线（必须 0）。
"""
import os
import shutil
import subprocess
import sys
import tarfile
import io
from pathlib import Path

REPO = Path(os.environ.get("P214_REPO") or Path(__file__).resolve().parents[4])   # 放在 reports/V9-S4-PHASE2/impl-review/evidence/ 下时即仓库根
COMMIT = "c5387d8"
PY = str(REPO / ".venv/bin/python")
WEIGHTS = "artifacts/v9/s4/phase1/final-final/weights"
WEIGHT_NAMES = [f"{a}#{s}" for a in ("L-int", "L-ind") for s in (1, 2, 3)]

G = "src/ainerzero/v9/experiments/s4/gated.py"
P = "src/ainerzero/v9/experiments/s4/analysis_p2.py"
RUN = "reports/V9-S4-PHASE2/run_s4p2.py"
MK = "reports/V9-S4-PHASE2/make_prereg.py"
TG = "tests/v9/experiments/test_s4_gated.py"
TA = "tests/v9/experiments/test_s4_analysis_p2.py"
TR = "tests/v9/experiments/test_s4p2_runner_native.py"

# (名字, [(文件, 原文, 替换)], [测试], 说明)
MUTANTS = [
    # --- 卡片指定的 8 类 ---
    ("M01_gate_open_closed_swapped", [(G, "        g = g[..., None]\n", "        g = ~g[..., None]\n")], [TG],
     "门开取 E-B、门关取学习模型（互换）"),
    ("M02_head_threshold_ge", [(G, "np.float64) > math.log(p / (1 - p)))", "np.float64) >= math.log(p / (1 - p)))")], [TG],
     "头门：接触概率 > p 改成 >= p"),
    ("M03_onestep_contacts_of_step_t", [(P, "        touched = {i for kind, i, j in self.ep.steps[t - 1].contacts if kind == \"disk\"} | {j for kind, i, j in self.ep.steps[t - 1].contacts if kind == \"disk\"}\n",
                                         "        touched = {i for kind, i, j in self.ep.steps[t].contacts if kind == \"disk\"} | {j for kind, i, j in self.ep.steps[t].contacts if kind == \"disk\"}\n")], [TA],
     "一步覆盖率的步类改用第 t 步（t -> t+1）的接触"),
    ("M04_reappear_track_at_b", [(P, "        trk = at[e[\"a\"]][e[\"k\"]]\n", "        trk = at[e[\"b\"]][e[\"k\"]]\n")], [TA],
     "重新出现覆盖率改用 b 步持有该盘的轨迹"),
    ("M05_GN_lower_bound_reversed", [(P, "_gt(st[\"GN\"], \"bonf_low\", T[\"GN\"][\"diff_low\"])", "_lt(st[\"GN\"], \"bonf_low\", T[\"GN\"][\"diff_low\"])")], [TA],
     "GN：下界 > -0.03 改成下界 < -0.03"),
    ("M06_GK1_no_interval", [(P, " and _ge(k1a, \"bonf_low\", lo1i) and _le(k1a, \"bonf_high\", hi1i)", "")], [TA],
     "GK1 全部步：去掉区间在 [0.85, 0.95] 内的条件"),
    ("M07a_negative_control_lower_bound", [(P, "_lt(st[\"neg_C\"], \"ci_high\"", "_lt(st[\"neg_C\"], \"ci_low\""),
                                           (P, "_lt(st[\"neg_D\"], \"ci_high\"", "_lt(st[\"neg_D\"], \"ci_low\"")], [TA],
     "负对照：C、D 的 95% 上界 < 0.5 改成 95% 下界 < 0.5"),
    ("M07b_negative_control_phase1_rule", [(P, "\"negative_control\": {\"C_high_below\": 0.5, \"D_high_below\": 0.5}", "\"negative_control\": {\"C_high_below\": 0.25, \"D_high_below\": 0.25}"),
                                           (P, "_lt(st[\"neg_C\"], \"ci_high\"", "_lt(st[\"neg_C\"], \"ci_low\""),
                                           (P, "_lt(st[\"neg_D\"], \"ci_high\"", "_lt(st[\"neg_D\"], \"ci_low\"")], [TA],
     "负对照：完全改回一期写法（95% 下界 < 0.25）"),
    ("M08a_prereg_weights_checked_after_marker",
     [(RUN, "    if pre.get(\"weights_sha256\") != WEIGHTS_SHA256:\n        raise GD.GuardError(\"the weights registered in the preregistration differ from the runner's\")\n", ""),
      (RUN, "            R[\"final_read_marker_sha256\"] = sha(FINAL_MARKER)\n",
       "            if pre.get(\"weights_sha256\") != WEIGHTS_SHA256:\n                raise GD.GuardError(\"the weights registered in the preregistration differ from the runner's\")\n            R[\"final_read_marker_sha256\"] = sha(FINAL_MARKER)\n")], [TR],
     "运行器：预登记权重 SHA 与运行器的比对挪到写只读一次标记之后"),
    ("M08b_weight_files_checked_after_marker_in_final",
     [(RUN, "        weights = check_weights()\n        ns = namespace(a.stage)\n", "        weights = check_weights() if a.stage != \"final\" else None\n        ns = namespace(a.stage)\n"),
      (RUN, "            R[\"final_read_marker_sha256\"] = sha(FINAL_MARKER)\n",
       "            weights = check_weights()\n            R[\"weights_sha256\"] = {n: sha(p) for n, p in weights.items()}\n            R[\"final_read_marker_sha256\"] = sha(FINAL_MARKER)\n"),
      (RUN, "             \"weights_sha256\": {n: sha(p) for n, p in weights.items()}, \"workers\": WORKERS}",
       "             \"weights_sha256\": {n: sha(p) for n, p in (weights or {}).items()}, \"workers\": WORKERS}")], [TR],
     "运行器：final 时权重文件 SHA 核对挪到写标记之后（smoke/probe 不变）"),
    # --- 复核者另加 ---
    ("X01_GC_uses_95_not_bonferroni", [(P, "_gt(st[\"GC\"], \"bonf_low\", T[\"GC\"][\"C_low\"])", "_gt(st[\"GC\"], \"ci_low\", T[\"GC\"][\"C_low\"])")], [TA],
     "GC 的下界改用 95% 区间而非 Bonferroni 区间"),
    ("X02_GD_D_bonferroni_m1", [(P, "\"GD_D\": D_of(main, a),", "\"GD_D\": D_of(main, a, m=1),")], [TA],
     "GD 的 D 统计用 m=1（Bonferroni 退化为 95%）"),
    ("X03_GX_C_from_main_records", [(P, "\"GX_C\": C_of(extrap, a)", "\"GX_C\": C_of(main, a)")], [TA],
     "GX 的 C 误读主评测而非外推"),
    ("X04_seed_average_seed1_only", [(P, "np.mean([np.asarray(r[\"cells\"][cell_key(arm, s)][field], dtype=np.float64) for s in SEEDS], axis=0)",
                                      "np.mean([np.asarray(r[\"cells\"][cell_key(arm, s)][field], dtype=np.float64) for s in SEEDS[:1]], axis=0)")], [TA],
     "事件按种子平均改成只取种子 1"),
    ("X05_GK2_collision_uses_non_collision", [(P, "\"GK2_collision\": coverage_reappear(main, a, \"collision\")", "\"GK2_collision\": coverage_reappear(main, a, \"all\")")], [TA],
     "GK2 有碰撞改用全部事件"),
    ("X06_reserve_check_removed", [(RUN, "            if deadline.left() < reserve:\n                raise GD.GuardError(f\"only {deadline.left():.0f} s left, the evaluation needs {reserve:.0f} s: the final read is not spent\")\n", "")], [TR],
     "运行器：删掉写标记前的剩余墙钟 >= 评测预留检查"),
    ("X07_request_checked_after_report_claim", [(RUN, "        check_request(a, pre)\n        report = Path(a.report)\n", "        report = Path(a.report)\n"),
                                                 (RUN, "        GD.claim_report(report)\n        out.mkdir(parents=True)\n", "        GD.claim_report(report)\n        out.mkdir(parents=True)\n        check_request(a, pre)\n")], [TR],
     "运行器：请求检查挪到占报告、建运行目录之后"),
    ("X08_prereg_reserve_without_margin", [(MK, "    eval_reserve = math.ceil(1.5 * scale * pr[\"post_marker_seconds\"])\n", "    eval_reserve = math.ceil(scale * pr[\"post_marker_seconds\"])\n")], [TR],
     "make_prereg：评测预留去掉 1.5 倍余量"),
    ("X09_geo_gate_tau_le_dt", [(G, "(tau >= 0) & (tau < W.DT))", "(tau >= 0) & (tau <= W.DT))")], [TG],
     "几何门：tau < DT 改成 tau <= DT（边界）"),
    ("unmutated_cpu", [], [TA], "不改，纯 CPU 分析测试基线（可不经锁）"),
    ("unmutated_gated", [], [TG], "不改，门控测试基线（MLX，经锁）"),
    ("unmutated_runner", [], [TR], "不改，运行器测试基线（MLX，经锁）"),
]


def make_copy(dst: Path, need_weights: bool) -> None:
    if dst.exists():
        raise SystemExit(f"副本目录已存在，不覆盖：{dst}")
    dst.mkdir(parents=True)
    blob = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", COMMIT, "src", "tests", "pyproject.toml", "reports/V9-S4-PHASE2"],
                          check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        tf.extractall(dst, filter="data")
    if need_weights:
        w = dst / WEIGHTS
        w.mkdir(parents=True)
        for n in WEIGHT_NAMES:
            shutil.copyfile(REPO / WEIGHTS / f"{n}.safetensors", w / f"{n}.safetensors")


def run_one(work: Path, name: str, subs, tests, why) -> list[str]:
    out: list[str] = []
    root = work / name
    make_copy(root, need_weights=TR in tests)
    for f, old, new in subs:
        p = root / f
        text = p.read_text(encoding="utf-8")
        n = text.count(old)
        if n != 1:
            raise SystemExit(f"{name}: 原文在 {f} 里出现 {n} 次")
        p.write_text(text.replace(old, new), encoding="utf-8")
    env = {"PYTHONPATH": str(root / "src"), "PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")}
    # find_spec 只定位、不执行被测模块（不导入 MLX）
    probe = subprocess.run([PY, "-c", "import importlib.util as u; [print(u.find_spec('ainerzero.v9.experiments.s4.' + m).origin) for m in ('gated', 'analysis_p2', 'worker_p2')]"],
                           cwd=root, env=env, capture_output=True, text=True)
    files = probe.stdout.split()
    if probe.returncode != 0 or not files or not all(Path(f).resolve().is_relative_to(root) for f in files):
        raise SystemExit(f"{name}: 导入的不是副本里的模块：{probe.stdout} {probe.stderr[-500:]}")
    out.append(f"== {name}: {why}")
    out.append(f"   imported from copy: {files}")
    for f, old, new in subs:
        out.append(f"   {f}: -{old.strip()[:140]!r}")
        out.append(f"   {' ' * len(f)}  +{new.strip()[:140]!r}")
    native = TG in tests or TR in tests          # 纯 CPU 的分析测试不加 --native-mlx，可不经锁
    fast = TR in tests and not name.startswith("unmutated")   # 运行器测试慢：变异在首个失败处停（-x）；存活者照样跑完整个文件
    cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *(["-x"] if fast else []), *(["--native-mlx"] if native else []), *tests]
    r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=3600)
    tail = r.stdout.strip().splitlines()
    last = tail[-1] if tail else r.stderr[-300:]
    failed = [ln for ln in tail if ln.startswith("FAILED") or ln.startswith("ERROR")]
    verdict = {0: "SURVIVED", 1: "killed"}.get(r.returncode, f"ERROR(exit {r.returncode})")
    if name.startswith("unmutated"):
        verdict = "baseline-ok" if r.returncode == 0 else f"BASELINE-FAILED(exit {r.returncode})"
    out.append(f"   result: {verdict}  exit={r.returncode}  {last}")
    out += [f"   {ln[:220]}" for ln in failed[:8]]
    (root / "pytest-output.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    return out


def main() -> None:
    args = sys.argv[1:]
    jobs = 1
    if args[:1] == ["--jobs"]:
        jobs, args = int(args[1]), args[2:]
    work = Path(args[0]).resolve()
    if work == REPO or REPO in work.parents:
        raise SystemExit("工作目录不能在仓库里")
    want = args[1:]
    names = [m[0] for m in MUTANTS]
    for w in want:
        if w not in names:
            raise SystemExit(f"没有这个变异：{w}")
    todo = [m for m in MUTANTS if not want or m[0] in want]
    if jobs == 1:
        for m in todo:
            print("\n".join(run_one(work, *m)), flush=True)
        return
    # 并发：线程池里各自 subprocess.run（不经 shell 的 &，子进程的 SIGINT 处理保持默认）；结果按变异表的顺序打印
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(jobs) as ex:
        futs = [ex.submit(run_one, work, *m) for m in todo]
        for f in futs:
            print("\n".join(f.result()), flush=True)


if __name__ == "__main__":
    main()
