import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]).resolve()
assert not str(M).startswith("/Users/mac/AinerWorkFlow/AinerZero")
S5 = M / "src/ainerzero/v9/experiments/s5"
T = ["tests/v9/experiments/test_s5_tokens.py", "tests/v9/experiments/test_s5_data.py", "tests/v9/experiments/test_s5_student_mlx.py", "tests/v9/experiments/test_s5_train_mlx.py"]
muts = {
 "V1_strict_threshold": (S5 / "tokens.py", "        keep[:, 1:] = diff_max >= tau", "        keep[:, 1:] = diff_max > tau"),
 "V2_run_len_minus_one": (S5 / "tokens.py", "    run_len = np.where(keep, next_kept - t_idx, 0)", "    run_len = np.where(keep, next_kept - t_idx - 1, 0)"),
 "V3_rlt_cache_key_no_tau": (S5 / "data.py", '        rlt_key = f"rlt:{clip_file.resolve()}:tau={tau_val!r}"', '        rlt_key = f"rlt:{clip_file.resolve()}"'),
 "V4_ungather_off_by_one": (S5 / "student.py", "            mx.cumsum(mask_int, axis=1) - 1,", "            mx.cumsum(mask_int, axis=1),"),
 "V5_padding_mask_one_extra": (S5 / "student.py", "        valid_compact = mx.arange(k_max, dtype=mx.int32)[None, :] < counts[:, None]", "        valid_compact = mx.arange(k_max, dtype=mx.int32)[None, :] <= counts[:, None]"),
 "V6_sort_dropped_first": (S5 / "student.py", "        sort_key = (1 - mask_int) * self.num_tokens + idx_range", "        sort_key = mask_int * self.num_tokens + idx_range"),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
def run(x=True):
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-rf"] + (["-x"] if x else []) + T, cwd=M, env=env, capture_output=True, text=True, timeout=3600)
    return r.returncode, [l.split("::")[-1][:55] for l in r.stdout.splitlines() if l.startswith(("FAILED", "ERROR"))], [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
rc, f, t = run(False); print("BASELINE", rc, f, t, flush=True)
if rc: sys.exit("baseline failed")
for name, (p, a, b) in muts.items():
    o = p.read_text(); n = o.count(a)
    if n != 1: print(name, "ANCHOR", n); continue
    p.write_text(o.replace(a, b)); rc, f, t = run(); p.write_text(o)
    print(f"{name}: {'KILLED' if rc else 'SURVIVED'} {f[:2]} {t}", flush=True)
