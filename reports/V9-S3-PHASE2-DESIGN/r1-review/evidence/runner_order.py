"""启动顺序对抗：在假根目录跑真实 run_phase2.py，看哪些路径在校验后才失败却已扣次数。不训练。"""
import fcntl, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
W = Path(sys.argv[1]).resolve(); PY = str(Path("/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"))
BASE = W / "base"; RUN = "reports/V9-S3-PHASE2/run_phase2.py"
sys.path.insert(0, str(BASE / "src"))
from ainerzero.v9.experiments.s3 import run_guard as GD
real = Path("/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s3/phase2"); before = sorted(str(p) for p in real.iterdir())
def git(r, *a): subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=r, check=True, capture_output=True)
def fake(name):
    r = W / "fake" / name
    if r.exists(): shutil.rmtree(r)
    (r / "reports/V9-S3-PHASE2").mkdir(parents=True); shutil.copytree(BASE / "src", r / "src", ignore=shutil.ignore_patterns("__pycache__")); shutil.copy2(BASE / RUN, r / RUN)
    d = r / "reports/DESIGN.md"; d.write_text("design"); (r / "artifacts/locks").mkdir(parents=True); (r / "artifacts/v9/s3/phase2").mkdir(parents=True)
    pre = {"manifest": GD.build_manifest(r, [r / RUN], src_root=r / "src", extra=[d]), "third_party": GD.third_party_versions(BASE, ("numpy", "mlx.core")), "dev_max_uses": 2, "final_approval_line": "LINE", "h3_capacity": 64}
    (r / "reports/V9-S3-PHASE2/PREREG-r1.json").write_text(json.dumps(pre)); (r / ".gitignore").write_text("artifacts/\n__pycache__/\n"); git(r, "init", "-q"); git(r, "add", "."); git(r, "commit", "-qm", "frozen"); return r
def run(r, *a, prefix=None, report="out.json", timeout=120):
    cmd = [PY, "-I", "-X", f"pycache_prefix={prefix or (r.parent / (r.name + '-pyc'))}", str(r / RUN), "--report", str(r / "reports" / report), *a]
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    p = subprocess.run(cmd, cwd=r, env=env, capture_output=True, text=True, timeout=timeout)
    return p
def state(r):
    a = r / "artifacts/v9/s3/phase2"; L = a / "dev_uses.json"; M = a / "FINAL_READ_ONCE.json"
    return {"ledger": [u["id"] for u in json.loads(L.read_text())] if L.exists() else [], "final_marker": M.exists(), "report_exists": (r / "reports/out.json").exists()}
OUT = {}
def rec(k, p, r):
    OUT[k] = {"exit": p.returncode, "last_err": (p.stderr.strip().splitlines() or [""])[-1][:160], **state(r)}; print(k, json.dumps(OUT[k], ensure_ascii=False), flush=True)
DEV = ("--stage", "dev", "--use-id", "dev1", "--purpose", "x"); FINAL = ("--stage", "final", "--approval", "LINE")
r = fake("c1"); (r / "artifacts/v9/s3/phase2/dev-dev1").mkdir(); rec("C1_dev_run_dir_exists", run(r, *DEV), r)
r = fake("c2"); (r / "artifacts/v9/s3/phase2/final-final").mkdir(); rec("C2_final_run_dir_exists", run(r, *FINAL), r)
r = fake("c3"); p = run(r, "--stage", "dev", "--use-id", "dev1"); rec("C3_refused_at_consume_leaves_report_stub", p, r)
p2 = run(r, *DEV); rec("C3b_retry_same_report_is_blocked", p2, r)
r = fake("c4"); (r / "reports/V9-S3-PHASE2/PREREG-r1.json").unlink(); git(r, "add", "-A"); git(r, "commit", "-qm", "x"); rec("C4_no_prereg_refused", run(r, *DEV), r)
# 陈旧字节码目录
r = fake("c5"); prefix = r.parent / "c5-stale"; f = r / "src/ainerzero/v9/experiments/s3/analysis_p2.py"; orig = f.read_text(); st = int(time.time()) - 900
assert orig.count("H2_MIN_DELTA = 0.05") == 1; f.write_text(orig.replace("H2_MIN_DELTA = 0.05", "H2_MIN_DELTA = 0.50")); os.utime(f, (st, st))
env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
subprocess.run([PY, "-I", "-X", f"pycache_prefix={prefix}", "-c", f"import sys; sys.path.insert(0, {str(r / 'src')!r}); import ainerzero.v9.experiments.s3.analysis_p2"], env=env, check=True, capture_output=True)
f.write_text(orig); os.utime(f, (st, st)); git(r, "add", "-A"); subprocess.run(["git", "status", "--short"], cwd=r, capture_output=True)
(r / "artifacts/v9/s3/phase2/dev-dev1").mkdir()
seen = subprocess.run([PY, "-I", "-X", f"pycache_prefix={prefix}", "-c", f"import sys; sys.path.insert(0, {str(r / 'src')!r}); import ainerzero.v9.experiments.s3.analysis_p2 as G; print(G.H2_MIN_DELTA)"], env=env, capture_output=True, text=True).stdout.strip()
OUT["C5_value_loaded_from_stale_prefix"] = seen; print("C5 value", seen, flush=True)
rec("C5_stale_prefix_passes_all_checks", run(r, *DEV, prefix=prefix), r)
after = sorted(str(p) for p in real.iterdir()); OUT["real_artifacts_untouched"] = before == after; print("REAL_UNTOUCHED", before == after, flush=True)
(W / "out/runner_order.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1))
