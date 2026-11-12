import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]); L = M / "src/ainerzero/v9/experiments/s5/labels.py"; MAT = M / "src/ainerzero/v9/experiments/s5/materialize.py"
muts = {
 "K1_obj_excludes_non_wall": (L, "obj_arr[k, r, c] = float(np.sum(p_ids >= 0)) / (PATCH_SIZE * PATCH_SIZE)", "obj_arr[k, r, c] = float(np.sum(p_ids == 0)) / (PATCH_SIZE * PATCH_SIZE)"),
 "K2_disk_groups_unoccluded_wrong_id": (L, "unoccluded_px = int(np.sum(single_ids == 100))", "unoccluded_px = int(np.sum(single_ids == disk_oid))"),
 "K3_ordering_closer_inverted": (L, 'closer = "a" if a["z_median"] < b["z_median"] else ("b" if b["z_median"] < a["z_median"] else "equal")', 'closer = "b" if a["z_median"] < b["z_median"] else ("a" if b["z_median"] < a["z_median"] else "equal")'),
 "K4_mat_r3_uses_r2": (MAT, "lbl_r3 = r3(ep, c, precomputed_frame=r3_rendered)", "lbl_r3 = r2(ep, c, precomputed_frame=rendered_frames[15])"),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
assert str(M.resolve()) != "/Users/mac/AinerWorkFlow/AinerZero", "refusing to mutate the live repository"
def run():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", "tests/v9/experiments/"], cwd=M, env=env, capture_output=True, text=True)
    return r.returncode, [l.split("::")[-1][:55] for l in r.stdout.splitlines() if l.startswith("FAILED")], [l for l in r.stdout.splitlines() if " passed" in l][-1:]
print("BASELINE", *run())
for name, (p, a, b) in muts.items():
    orig = p.read_text(); n = orig.count(a)
    if n != 1: print(name, "ANCHOR", n); continue
    p.write_text(orig.replace(a, b)); rc, f, t = run(); p.write_text(orig)
    print(f"{name}: {'KILLED' if rc else 'SURVIVED'} {f[:3]} {t}", flush=True)
