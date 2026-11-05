"""T40 反向验证：在仓外镜像里逐个注入缺陷，新测试必须变红。用法：.venv/bin/python mutate_t40.py"""
import os, re, shutil, subprocess, tempfile
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "src/ainerzero/v9/teachers"
RUN, MATH, WORK = "da3_calibration_runner.py", "da3_calibration_math.py", "da3_worker.py"
M = {
 "NEW-5 对拍字段退化成只比 depth": (RUN, 'parity_fields=tuple(par["fields"]),', 'parity_fields=("depth",),'),
 "NEW-6 holdout 混入 fit 协方差": (RUN, '(fit if w in plan.fit_worlds else hold).append(m["residual_7d"])', 'fit.append(m["residual_7d"]); hold.append(m["residual_7d"])'),
 "NEW-8 协方差分母 N 而非 N-1": (MATH, "cov = (centered.T @ centered) / (x.shape[0] - 1)", "cov = (centered.T @ centered) / x.shape[0]"),
 "T40-a load_plan 又无条件解析 intrinsics 键": (RUN, 'adv_text = p["negative_controls"].get("intrinsics")', 'adv_text = p["negative_controls"]["intrinsics"]'),
 "T40-b 去掉逐阶段落盘": (RUN, "            self.checkpoint()                       #", "            pass                                    #"),
 "T40-c 去掉开始即落盘的 in_progress": (RUN, "    run.checkpoint()                                  #", "    pass                                              #"),
 "T40-d --proposal 被忽略(preflight)": (RUN, "plan = load_plan(a.proposal or PROPOSAL_PATH)", "plan = load_plan(PROPOSAL_PATH)"),
 "T40-e 环境变量 T6_PROPOSAL_PATH 被忽略": (RUN, 'PROPOSAL_PATH = Path(os.environ["T6_PROPOSAL_PATH"]) if os.environ.get("T6_PROPOSAL_PATH") else REPO_ROOT / "reports/V9-T28/proposal.json"', 'PROPOSAL_PATH = REPO_ROOT / "reports/V9-T28/proposal.json"'),
 "T40-f 证据不再记录 proposal 路径": (RUN, '    ev["protocol"]["proposal_path"] = str(Path(proposal_path).resolve())\n', ""),
}
out = []
for name, (fname, old, new) in M.items():
    base = Path(tempfile.mkdtemp(prefix="t40mut-"))
    (base / "tests").mkdir(); (base / "src/ainerzero/v9/teachers").mkdir(parents=True)
    for f in (RUN, MATH, WORK): shutil.copy(SRC / f, base / "src/ainerzero/v9/teachers" / f)
    shutil.copy(REPO / "tests/test_da3_calibration_runner.py", base / "tests/")
    os.symlink(REPO / "reports", base / "reports"); os.symlink(REPO / "envs", base / "envs")
    tgt = base / "src/ainerzero/v9/teachers" / fname; txt = tgt.read_text()
    if txt.count(old) != 1: out.append((name, f"!!! 变异未能应用(出现{txt.count(old)}次)")); shutil.rmtree(base); continue
    tgt.write_text(txt.replace(old, new, 1))
    r = subprocess.run([str(REPO / ".venv/bin/python"), "-m", "pytest", "tests/test_da3_calibration_runner.py", "-q", "--no-header", "-p", "no:cacheprovider", "--tb=no"], cwd=base, capture_output=True, text=True)
    failed = re.findall(r"FAILED tests/test_da3_calibration_runner.py::(\S+)", r.stdout)
    out.append((name, (f"{len(failed)} 条红: " + ", ".join(x.split('::')[-1][:40] for x in failed[:3])) if failed else "!!! 没有任何测试抓到 !!!"))
    shutil.rmtree(base)
for n, r in out: print(f"{n}\n    -> {r}")
