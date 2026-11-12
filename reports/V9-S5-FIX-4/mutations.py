import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]).resolve()
assert not str(M).startswith("/Users/mac/AinerWorkFlow/AinerZero")
T = ["tests/v9/experiments/test_s5_data.py", "tests/v9/experiments/test_s5_train_mlx.py", "tests/v9/experiments/test_s5_student_mlx.py", "tests/v9/experiments/test_s5_tokens.py",
     "tests/v9/experiments/test_s5_runner_plan.py", "tests/v9/experiments/test_s5_runner_native.py", "tests/v9/experiments/test_s5_evaluate.py"]
muts = {
 "Q1_no_per_cell_manifest_check": (M / "reports/V9-S5-PHASE1/run_s5p1.py", "            changed = GD.check_manifest(REPO, manifest)\n            if changed:", "            changed = []\n            if changed:"),
 "Q2_heads_per_step_reload": (M / "src/ainerzero/v9/experiments/s5/train.py", "            r1_logd_mx = mx.array(all_r1_logd[bi])\n", "            _ = [load_item(index, b, cache=active_cache) for b in b_indices]\n            r1_logd_mx = mx.array(all_r1_logd[bi])\n"),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
def run(x=True):
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-rf"] + (["-x"] if x else []) + T, cwd=M, env=env, capture_output=True, text=True, timeout=5400)
    return r.returncode, [l.split("::")[-1][:55] for l in r.stdout.splitlines() if l.startswith(("FAILED", "ERROR"))], [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
rc, f, t = run(False); print("BASELINE", rc, f, t, flush=True)
if rc: sys.exit("baseline failed")
for name, (p, a, b) in muts.items():
    o = p.read_text(); assert o.count(a) == 1, name
    p.write_text(o.replace(a, b)); rc, f, t = run(); p.write_text(o)
    print(f"{name}: {'KILLED' if rc else 'SURVIVED'} {f[:2]} {t}", flush=True)
