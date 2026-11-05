import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
SRC = REPO / "src/ainerzero/v9/teachers"
MUTANTS = {
 "A 不再把 w2c 取逆(r1 约定错误)": ("da3_calibration_math.py", "    return np.linalg.inv(full)", "    return full"),
 "B 允许静默缩放(吞掉尺寸不匹配)": ("da3_calibration_math.py", 'if np.asarray(pred_depths[i]).shape != np.asarray(gt_depths[i]).shape:', 'if False:'),
 "C 目标视图自拟合深度(违反 T28)": ("da3_calibration_math.py", "s_depth = float(np.median(g0[m0] / p0[m0]))", "s_depth = float(np.median(g1[m1] / p1[m1]))"),
 "D 写死 verified:True(未执行的控制)": ("da3_calibration_runner.py", '"kind": "boundary_rejection"})\n                self.failures', '"kind": "boundary_rejection", "verified": True})\n                self.failures'),
 "E 真实工厂谎称能用 K 条件化": ("da3_calibration_runner.py", "REAL_DA3_CONDITIONS_ON_INTRINSICS_ONLY = False", "REAL_DA3_CONDITIONS_ON_INTRINSICS_ONLY = True"),
 "F 对拍失败不记入 failures(放宽/吞掉)": ("da3_calibration_runner.py", 'self.failures.append(f"{variant}/{name}: numerical parity failed (tolerances not relaxed)")', 'pass'),
 "G 逆向控制不红也算过": ("da3_calibration_runner.py", 'self.failures.append(f"{variant}/{name}: adverse control did not turn red")', 'pass'),
 "H 失败也退出 0": ("da3_calibration_runner.py", "code = EXIT_STAGE_FAILED", "code = EXIT_OK"),
 "I 预检放过已存在输出目录": ("da3_calibration_runner.py", "if Path(pred_dir).exists() and any(Path(pred_dir).iterdir()):", "if False:"),
 "J 写入写死结论字段 rotation_offset_deg": ("da3_calibration_runner.py", 'ev["registration"] =', 'ev["rotation_offset_deg"] = 180.0; ev["registration"] ='),
}
results = []
for name, (fname, old, new) in MUTANTS.items():
    base = Path(tempfile.mkdtemp(prefix="t37mut-"))
    (base / "tests").mkdir(); (base / "src/ainerzero/v9/teachers").mkdir(parents=True)
    for f in ("da3_calibration_math.py", "da3_calibration_runner.py", "da3_worker.py"):
        shutil.copy(SRC / f, base / "src/ainerzero/v9/teachers" / f)
    shutil.copy(REPO / "tests/test_da3_calibration_runner.py", base / "tests/")
    os.symlink(REPO / "reports", base / "reports"); os.symlink(REPO / "envs", base / "envs")
    target = base / "src/ainerzero/v9/teachers" / fname
    txt = target.read_text()
    if old not in txt:
        results.append((name, "MUTATION NOT APPLIED")); shutil.rmtree(base); continue
    target.write_text(txt.replace(old, new, 1))
    r = subprocess.run([str(REPO / ".venv/bin/python"), "-m", "pytest", "tests/test_da3_calibration_runner.py", "-q", "--no-header",
                        "-p", "no:cacheprovider", "--tb=no"], cwd=base, capture_output=True, text=True)
    failed = re.findall(r"FAILED tests/test_da3_calibration_runner.py::(\S+)", r.stdout)
    results.append((name, f"{len(failed)} 条红: " + ", ".join(f.split('::')[-1][:44] for f in failed[:3]) if failed else "!!! 没有任何测试抓到 !!!"))
    shutil.rmtree(base)
for n, r in results: print(f"{n}\n    -> {r}")
