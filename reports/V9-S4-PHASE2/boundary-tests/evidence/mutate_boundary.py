"""P219 边界测试证明：评测预留放宽变异与几何门 tau=DT 变异消杀证明。

用法：
  .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock \
      .venv/bin/python reports/V9-S4-PHASE2/boundary-tests/evidence/mutate_boundary.py <工作目录> [变异名 ...]

- 副本做法：
  1. `git archive HEAD src tests pyproject.toml reports/V9-S4-PHASE2` 解出副本。
  2. 将实盘工作树中已补充边界用例的两份测试文件：
     - tests/v9/experiments/test_s4_gated.py
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

GATED_SRC = "src/ainerzero/v9/experiments/s4/gated.py"
RUNNER_SRC = "reports/V9-S4-PHASE2/run_s4p2.py"
TG = "tests/v9/experiments/test_s4_gated.py"
TR = "tests/v9/experiments/test_s4p2_runner_native.py"

MUTANTS = [
    # --- 门控边界测试组 ---
    ("clean_gated", [], [TG], [], "门控测试基线（不改源码）"),
    ("X09_geo_gate_tau_le_dt",
     [(GATED_SRC, "(tau >= 0) & (tau < W.DT))", "(tau >= 0) & (tau <= W.DT))")],
     [TG], [], "几何门：tau < DT 改成 tau <= DT（边界测试）"),

    # --- 运行器预留边界测试组 ---
    ("clean_runner_reserve", [], [TR],
     ["-k", "test_final_refuses_when_the_wall_clock_left_is_below_the_reserve"],
     "运行器预留检查基线（不改源码）"),
    ("ru_reserve_tenth",
     [(RUNNER_SRC, "            if deadline.left() < reserve:\n", "            if deadline.left() < reserve / 10:\n")],
     [TR], ["-k", "test_final_refuses_when_the_wall_clock_left_is_below_the_reserve"],
     "运行器：写标记前预留检查放宽十倍（ru_reserve_tenth）"),
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
    for test_rel in (TG, TR):
        shutil.copyfile(REPO / test_rel, dst / test_rel)
    if need_weights:
        w = dst / WEIGHTS
        w.mkdir(parents=True)
        for n in WEIGHT_NAMES:
            shutil.copyfile(REPO / WEIGHTS / f"{n}.safetensors", w / f"{n}.safetensors")


def run_one(work: Path, name: str, subs, tests, extra_args, why) -> list[str]:
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
    native = True
    cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *(["--native-mlx"] if native else []), *extra_args, *tests]
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
    targets = [m for m in MUTANTS if not want or m[0] in want]
    if not targets:
        raise SystemExit(f"未匹配到任何变异: {want}")

    for name, subs, tests, extra_args, why in targets:
        lines = run_one(work, name, subs, tests, extra_args, why)
        print("\n".join(lines))
        print()


if __name__ == "__main__":
    main()
