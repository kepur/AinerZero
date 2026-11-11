"""P214：在被审提交的干净副本与存活变异的副本上，跑复核者建议补的测试（proposed_tests/）。
期望：干净副本（clean）全过；对应的存活变异至少一条失败——说明该变异不等价，是现有测试漏了。

用法（在仓库根运行；runner 组导入 MLX，必须经锁，前台运行）：
  .venv/bin/python reports/V9-S4-PHASE2/impl-review/evidence/run_proposed_tests.py [--jobs N] <新的空目录> analysis clean X01_... X02_... X03_... X04_...
  .venv/bin/python <hold_lock.py> artifacts/locks/m0-worker.lock .venv/bin/python reports/V9-S4-PHASE2/impl-review/evidence/run_proposed_tests.py \
      [--jobs N] <新的空目录> runner clean M08b_... X06_...
副本的做法与 mutate_p214.py 相同（git archive c5387d8，逐字替换，PYTHONPATH 指向副本 src）。
"""
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mutate_p214 as MU  # noqa: E402

FILES = {"analysis": "test_p214_analysis_gaps.py", "runner": "test_p214_runner_gaps.py"}


def run(work: Path, group: str, target: str) -> list[str]:
    spec = {m[0]: m for m in MU.MUTANTS}
    subs = [] if target == "clean" else spec[target][1]
    root = work / f"{group}-{target}"
    MU.make_copy(root, need_weights=group == "runner")
    for f, old, new in subs:
        p = root / f
        text = p.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise SystemExit(f"{target}: 原文在 {f} 里出现 {text.count(old)} 次")
        p.write_text(text.replace(old, new), encoding="utf-8")
    dst = root / "tests/v9/experiments" / FILES[group]
    shutil.copyfile(HERE / "proposed_tests" / FILES[group], dst)
    env = {"PYTHONPATH": str(root / "src"), "PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")}
    cmd = [MU.PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *(["--native-mlx"] if group == "runner" else []),
           str(dst.relative_to(root))]
    r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=3600)
    lines = r.stdout.strip().splitlines()
    want = 0 if target == "clean" else 1
    verdict = "as expected" if r.returncode == want else "UNEXPECTED"
    out = [f"== {group} on {target}: exit={r.returncode} ({'should pass' if want == 0 else 'should fail'}) -> {verdict}  {lines[-1] if lines else r.stderr[-300:]}"]
    out += [f"   {ln[:220]}" for ln in lines if ln.startswith(("FAILED", "ERROR"))][:12]
    (root / "proposed-output.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    return out


def main() -> None:
    args = sys.argv[1:]
    jobs = 1
    if args[:1] == ["--jobs"]:
        jobs, args = int(args[1]), args[2:]
    work, group, targets = Path(args[0]).resolve(), args[1], args[2:]
    if work == MU.REPO or MU.REPO in work.parents:
        raise SystemExit("工作目录不能在仓库里")
    with ThreadPoolExecutor(jobs) as ex:
        for f in [ex.submit(run, work, group, t) for t in targets]:
            print("\n".join(f.result()), flush=True)


if __name__ == "__main__":
    main()
