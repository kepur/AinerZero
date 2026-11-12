import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]); S5 = M / "src/ainerzero/v9/experiments/s5"
T = ["tests/v9/experiments/test_s5_tokens.py", "tests/v9/experiments/test_s5_student_mlx.py"]
muts = {
 "E1_layer_off_by_one": ("student.py", "idx = (layer - 1) if layer > 0 else layer", "idx = layer if layer > 0 else layer"),
 "E2_gridmask_polarity": ("heads.py", "attn_mask = mx.where(m_bool, mx.zeros_like(m_bool, dtype=mx.float32), -1e9)", "attn_mask = mx.where(m_bool, -1e9, mx.zeros_like(m_bool, dtype=mx.float32))"),
 "E3_distill_ignores_mask": ("losses.py", "    if mask is not None:\n        m = mask.astype(mx.float32)", "    if False and mask is not None:\n        m = mask.astype(mx.float32)"),
 "E4_fisher_yates_not_sattolo": ("losses.py", "j = rng.integers(0, i)", "j = rng.integers(0, i + 1)"),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
for name, (fn, a, b) in muts.items():
    p = S5 / fn; orig = p.read_text(); n = orig.count(a)
    if n == 0: print(name, "ANCHOR NOT FOUND"); continue
    p.write_text(orig.replace(a, b))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-rf", *T], cwd=M, env=env, capture_output=True, text=True)
    p.write_text(orig)
    f = [l.split("::")[-1][:55] for l in r.stdout.splitlines() if l.startswith("FAILED")]
    print(f"{name} (x{n}): {'KILLED' if r.returncode else 'SURVIVED'} {f}", flush=True)
