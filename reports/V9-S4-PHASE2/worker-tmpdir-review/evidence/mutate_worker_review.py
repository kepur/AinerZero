"""P220 复核变异测试：针对 S4 二期评测工作进程独立 MLX 编译目录修法的 3 个变异测试。

用法：
  .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock \
      .venv/bin/python reports/V9-S4-PHASE2/worker-tmpdir-review/evidence/mutate_worker_review.py <工作目录> [变异名 ...]
"""
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
COMMIT = "d14e04b"
PY = str(REPO / ".venv/bin/python")

WSRC = "src/ainerzero/v9/experiments/s4/worker_p2.py"
WTST = "tests/v9/experiments/test_s4p2_worker_native.py"

MUTANTS = [
    ("clean_worker", [], [WTST], "工作进程测试基线（不改源码）"),
    ("M01_remove_call_in_init",
     [(WSRC, "def init(weights: Mapping[str, str]) -> None:\n    private_compile_dir()\n",
             "def init(weights: Mapping[str, str]) -> None:\n")],
     [WTST], "变异 1：去掉 init() 里的 private_compile_dir() 调用"),
    ("M02_call_after_build_models",
     [(WSRC, "    private_compile_dir()\n    mx.set_default_device(mx.cpu)\n    models, counters, dyn = build_models(weights)\n",
             "    mx.set_default_device(mx.cpu)\n    models, counters, dyn = build_models(weights)\n    private_compile_dir()\n")],
     [WTST], "变异 2：将 private_compile_dir() 挪到 build_models 之后"),
    ("M03_dir_without_pid",
     [(WSRC, 'd = Path(tempfile.gettempdir()) / "ainerzero-mlx-cpu" / str(os.getpid())',
             'd = Path(tempfile.gettempdir()) / "ainerzero-mlx-cpu"')],
     [WTST], "变异 3：目录不带 pid，即所有进程共用一个目录"),
]


def make_copy(dst: Path) -> None:
    if dst.exists():
        raise SystemExit(f"副本目录已存在，不覆盖：{dst}")
    dst.mkdir(parents=True)
    blob = subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar", COMMIT, "src", "tests", "pyproject.toml", "reports/V9-S4-PHASE2"],
        check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        tf.extractall(dst, filter="data")


def run_one(work: Path, name: str, subs, tests, why) -> list[str]:
    out: list[str] = []
    root = work / name
    make_copy(root)
    for f, old, new in subs:
        p = root / f
        text = p.read_text(encoding="utf-8")
        n = text.count(old)
        if n != 1:
            raise SystemExit(f"{name}: 原文在 {f} 里出现 {n} 次（期望 1 次）")
        p.write_text(text.replace(old, new), encoding="utf-8")
    env = {"PYTHONPATH": str(root / "src"), "PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")}
    probe = subprocess.run(
        [PY, "-c", "import importlib.util as u; [print(u.find_spec('ainerzero.v9.experiments.s4.' + m).origin) for m in ('worker_p2',)]"],
        cwd=root, env=env, capture_output=True, text=True)
    files = probe.stdout.split()
    if probe.returncode != 0 or not files or not all(Path(f).resolve().is_relative_to(root) for f in files):
        raise SystemExit(f"{name}: 导入的不是副本里的模块：{probe.stdout} {probe.stderr[-500:]}")
    out.append(f"== {name}: {why}")
    out.append(f"   imported from copy: {files}")
    for f, old, new in subs:
        out.append(f"   {f}: -{old.strip()[:140]!r}")
        out.append(f"   {' ' * len(f)}  +{new.strip()[:140]!r}")
    cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", *tests]
    r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=300)
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

    for name, subs, tests, why in targets:
        lines = run_one(work, name, subs, tests, why)
        print("\n".join(lines))
        print()


if __name__ == "__main__":
    main()
