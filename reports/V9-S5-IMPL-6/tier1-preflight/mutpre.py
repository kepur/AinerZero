import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]).resolve()
assert str(M) != "/Users/mac/AinerWorkFlow/AinerZero"
R = M / "reports/V9-S5-PHASE1/run_s5p1.py"
muts = {
 "P1_teachers_unpartitioned": ('"pool": {"vjepa": TEACHERS / "vjepa" / "s5p1-pool", "da2": TEACHERS / "da2" / "s5p1-pool"},\n    "lab": {"vjepa": TEACHERS / "vjepa" / "s5p1-lab"},',
                               '"pool": {"vjepa": TEACHERS / "vjepa", "da2": TEACHERS / "da2"},\n    "lab": {"vjepa": TEACHERS / "vjepa"},'),
 "P2_no_preflight_before_dev_use": ('        _preflight_real_inputs()\n        GD.consume_dev_use(', '        GD.consume_dev_use('),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
def run():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-rf", "tests/v9/experiments/test_s5_runner_native.py", "-k", "preflight or without_real_inputs"], cwd=M, env=env, capture_output=True, text=True)
    return r.returncode, [l.split("::")[-1][:60] for l in r.stdout.splitlines() if l.startswith("FAILED")], [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
print("BASELINE", *run())
orig = R.read_text()
for name, (a, b) in muts.items():
    assert orig.count(a) == 1, name
    R.write_text(orig.replace(a, b)); rc, f, t = run(); R.write_text(orig)
    print(f"{name}: {'KILLED' if rc else 'SURVIVED'} {f} {t}")
