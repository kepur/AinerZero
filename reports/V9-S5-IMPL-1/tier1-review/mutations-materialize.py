import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]); S5 = M / "src/ainerzero/v9/experiments/s5"
muts = {
 "P1_mat_r2_frame14": ("materialize.py", "lbl_r2 = r2(ep, c, precomputed_frame=rendered_frames[15])", "lbl_r2 = r2(ep, c, precomputed_frame=rendered_frames[14])"),
 "P2_mat_r3_step_plus7": ("materialize.py", "st_r3 = ep.steps[base_t + 15 + 8]", "st_r3 = ep.steps[base_t + 15 + 7]"),
 "P3_mat_groups_frame0": ("materialize.py", "groups = disk_groups(ep, c, precomputed_frame=rendered_frames[15])", "groups = disk_groups(ep, c, precomputed_frame=rendered_frames[0])"),
 "P4_mat_clip_base_15": ("materialize.py", "            base_t = c * 16\n", "            base_t = c * 15\n"),
 "P5_mat_ordering_frame14": ("materialize.py", "ordering = ordering_pairs(ep, c, precomputed_frame=rendered_frames[15])", "ordering = ordering_pairs(ep, c, precomputed_frame=rendered_frames[14])"),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
def run():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", "tests/v9/experiments/"], cwd=M, env=env, capture_output=True, text=True)
    return r.returncode, [l.split("::")[-1][:55] for l in r.stdout.splitlines() if l.startswith("FAILED")], [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
for name, (fn, a, b) in muts.items():
    p = S5 / fn; orig = p.read_text()
    assert orig.count(a) == 1, (name, orig.count(a))
    p.write_text(orig.replace(a, b)); rc, f, t = run(); p.write_text(orig)
    print(f"{name}: {'KILLED' if rc else 'SURVIVED'} {f} {t}", flush=True)
