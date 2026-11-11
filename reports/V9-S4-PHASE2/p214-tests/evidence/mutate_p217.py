"""P217 变异测试（S4 第二阶段实现：按 DESIGN-r1 改写 P214 补充测试后的变异消杀证明）。

用法：
  纯 CPU 变异：
    .venv/bin/python reports/V9-S4-PHASE2/p214-tests/evidence/mutate_p217.py <工作目录> [变异名 ...]
  MLX 变异（必须经锁）：
    .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock \
        .venv/bin/python reports/V9-S4-PHASE2/p214-tests/evidence/mutate_p217.py <工作目录> clean_runner M08b_weight_files_checked_after_marker_in_final X06_reserve_check_removed

- 副本做法：
  1. `git archive HEAD src tests pyproject.toml reports/V9-S4-PHASE2` 解出副本。
  2. 将实盘工作树中已改写的两份测试文件：
     - tests/v9/experiments/test_s4_analysis_p2.py
     - tests/v9/experiments/test_s4p2_runner_native.py
     复制入副本对应位置。
  3. 若测试涉及运行器（TR），复制 6 个 safetensors 权重文件。
  4. 对指定变异在副本内进行精确字符串替换（替换前断言恰出现 1 次）。
  5. 检查 importlib.util.find_spec 确认导入模块源自副本内部，而非实盘。
  6. 运行 pytest，收集输出并判定：
     - baseline: 退出码 0 为 baseline-ok
     - mutant: 退出码 1 为 killed，0 为 SURVIVED
"""
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
COMMIT = "HEAD"
PY = str(REPO / ".venv/bin/python")
WEIGHTS = "artifacts/v9/s4/phase1/final-final/weights"
WEIGHT_NAMES = [f"{a}#{s}" for a in ("L-int", "L-ind") for s in (1, 2, 3)]

P = "src/ainerzero/v9/experiments/s4/analysis_p2.py"
RUN = "reports/V9-S4-PHASE2/run_s4p2.py"
TA = "tests/v9/experiments/test_s4_analysis_p2.py"
TR = "tests/v9/experiments/test_s4p2_runner_native.py"

MUTANTS = [
    # --- CPU 分析组变异 ---
    ("clean_analysis", [], [TA], "纯 CPU 分析测试基线（不改源码）"),
    ("X01_GC_uses_95_not_bonferroni",
     [(P, '_gt(st["GC"], "bonf_low", T["GC"]["C_low"])', '_gt(st["GC"], "ci_low", T["GC"]["C_low"])')],
     [TA], "GC 的下界改用 95% 区间 ci_low 而非 Bonferroni 区间 bonf_low"),
    ("X01_GR_uses_95_not_bonferroni",
     [(P, '_gt(st["GR"], "bonf_low", T["GR"]["diff_low"])', '_gt(st["GR"], "ci_low", T["GR"]["diff_low"])')],
     [TA], "GR 的下界改用 95% 区间 ci_low 而非 Bonferroni 区间 bonf_low"),
    ("X02_GD_D_bonferroni_m1",
     [(P, '"GD_D": D_of(main, a),', '"GD_D": D_of(main, a, m=1),')],
     [TA], "GD 的 D 统计用 m=1（退化为 95% 区间）"),
    ("X03_GX_C_from_main_records",
     [(P, '"GX_C": C_of(extrap, a)', '"GX_C": C_of(main, a)')],
     [TA], "GX 的 C 误读主评测而非外推"),
    ("X04_seed_average_seed1_only",
     [(P, 'for s in SEEDS], axis=0) if r["events"] else np.zeros(0)',
       'for s in SEEDS[:1]], axis=0) if r["events"] else np.zeros(0)')],
     [TA], "每个事件的对错与重新出现覆盖率只取种子 1"),
    ("X07_neg_control_uses_95_high",
     [(P, '_lt(st["neg_C"], "bonf_high", T["negative_control"]["C_high_below"])',
       '_lt(st["neg_C"], "ci_high", T["negative_control"]["C_high_below"])'),
      (P, '_lt(st["neg_D"], "bonf_high", T["negative_control"]["D_high_below"])',
       '_lt(st["neg_D"], "ci_high", T["negative_control"]["D_high_below"])')],
     [TA], "负对照 neg_C 与 neg_D 改回读 95% 上界 ci_high（退回 r0 口径）"),

    # --- MLX 运行器组变异（经锁） ---
    ("clean_runner", [], [TR], "MLX 运行器测试基线（不改源码）"),
    ("M08b_weight_files_checked_after_marker_in_final",
     [(RUN, "        weights = check_weights()\n        ns = namespace(a.stage)\n",
       "        weights = check_weights() if a.stage != \"final\" else None\n        ns = namespace(a.stage)\n"),
      (RUN, "            R[\"final_read_marker_sha256\"] = sha(FINAL_MARKER)\n",
       "            weights = check_weights()\n            R[\"weights_sha256\"] = {n: sha(p) for n, p in weights.items()}\n            R[\"final_read_marker_sha256\"] = sha(FINAL_MARKER)\n"),
      (RUN, "             \"weights_sha256\": {n: sha(p) for n, p in weights.items()}, \"workers\": WORKERS}",
       "             \"weights_sha256\": {n: sha(p) for n, p in (weights or {}).items()}, \"workers\": WORKERS}")],
     [TR], "运行器：final 时权重文件 SHA 核对挪到写标记之后（smoke/probe 不变）"),
    ("X06_reserve_check_removed",
     [(RUN, "            if deadline.left() < reserve:\n                raise GD.GuardError(f\"only {deadline.left():.0f} s left, the evaluation needs {reserve:.0f} s: the final read is not spent\")\n", "")],
     [TR], "运行器：删掉写标记前的剩余墙钟 >= 评测预留检查"),
]


def make_copy(dst: Path, need_weights: bool) -> None:
    if dst.exists():
        raise SystemExit(f"副本目录已存在，不覆盖：{dst}")
    dst.mkdir(parents=True)
    blob = subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar", COMMIT, "src", "tests", "pyproject.toml", "reports/V9-S4-PHASE2"],
        check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        tf.extractall(dst, filter="data")
    # 覆盖测试文件为当前工作树中改写合并后的版本
    for test_rel in (TA, TR):
        shutil.copyfile(REPO / test_rel, dst / test_rel)
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
            raise SystemExit(f"{name}: 原文在 {f} 里出现 {n} 次（期望 1 次）")
        p.write_text(text.replace(old, new), encoding="utf-8")
    env = {"PYTHONPATH": str(root / "src"), "PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")}
    probe = subprocess.run(
        [PY, "-c", "import importlib.util as u; [print(u.find_spec('ainerzero.v9.experiments.s4.' + m).origin) for m in ('gated', 'analysis_p2', 'worker_p2')]"],
        cwd=root, env=env, capture_output=True, text=True)
    files = probe.stdout.split()
    if probe.returncode != 0 or not files or not all(Path(f).resolve().is_relative_to(root) for f in files):
        raise SystemExit(f"{name}: 导入的不是副本里的模块：{probe.stdout} {probe.stderr[-500:]}")
    out.append(f"== {name}: {why}")
    out.append(f"   imported from copy: {files}")
    for f, old, new in subs:
        out.append(f"   {f}: -{old.strip()[:140]!r}")
        out.append(f"   {' ' * len(f)}  +{new.strip()[:140]!r}")
    native = TR in tests
    fast = TR in tests and not name.startswith("clean")
    cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *(["-x"] if fast else []), *(["--native-mlx"] if native else []), *tests]
    r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=3600)
    tail = r.stdout.strip().splitlines()
    last = tail[-1] if tail else r.stderr[-300:]
    failed = [ln for ln in tail if ln.startswith("FAILED") or ln.startswith("ERROR")]
    verdict = {0: "SURVIVED", 1: "killed"}.get(r.returncode, f"ERROR(exit {r.returncode})")
    if name.startswith("clean"):
        verdict = "baseline-ok" if r.returncode == 0 else f"BASELINE-FAILED(exit {r.returncode})"
    out.append(f"   result: {verdict}  exit={r.returncode}  {last}")
    out += [f"   {ln[:220]}" for ln in failed[:8]]
    (root / "pytest-output.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    return out


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(f"Usage: {sys.argv[0]} <work_dir> [mutant_name ...]")
        sys.exit(1)
    work = Path(args[0]).resolve()
    if work == REPO or REPO in work.parents:
        raise SystemExit("工作目录不能在仓库里")
    want = args[1:]
    names = [m[0] for m in MUTANTS]
    for w in want:
        if w not in names:
            raise SystemExit(f"没有这个变异：{w}")
    todo = [m for m in MUTANTS if not want or m[0] in want]
    for m in todo:
        res = run_one(work, *m)
        print("\n".join(res), flush=True)


if __name__ == "__main__":
    main()
