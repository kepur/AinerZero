import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]).resolve()
assert str(M) != "/Users/mac/AinerWorkFlow/AinerZero", "refusing to mutate the live repository"
F = M / "src/ainerzero/v9/experiments/s5/train.py"
muts = {
 "J2_predict_grid_mask_none": ('        r2_logit = heads_container["r2"](tokens, mask=mask)\n        r3_logit = heads_container["r3"](tokens, mask=mask)',
                               '        r2_logit = heads_container["r2"](tokens, mask=None)\n        r3_logit = heads_container["r3"](tokens, mask=None)'),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
def run():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-rf", "tests/v9/experiments/test_s5_train_mlx.py"], cwd=M, env=env, capture_output=True, text=True)
    return r.returncode, [l.split("::")[-1][:60] for l in r.stdout.splitlines() if l.startswith("FAILED")], [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
print("BASELINE", *run(), flush=True)
orig = F.read_text()
for name, (a, b) in muts.items():
    assert orig.count(a) == 1, name
    F.write_text(orig.replace(a, b)); rc, f, t = run(); F.write_text(orig)
    print(f"{name}: {'KILLED' if rc else 'SURVIVED'} {f} {t}", flush=True)
