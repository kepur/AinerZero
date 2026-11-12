import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]); S5 = M / "src/ainerzero/v9/experiments/s5"
muts = {
 "O1_obj_excludes_wall": ("labels.py", "obj_arr[k, r, c] = float(np.sum(p_ids >= 0))", "obj_arr[k, r, c] = float(np.sum(p_ids > 0))"),
 "O2_mat_no_obj": ("materialize.py", "                        r1_obj=lbl_r1[\"obj\"],\n", ""),
 "O3_mat_obj_is_sky": ("materialize.py", "r1_obj=lbl_r1[\"obj\"],", "r1_obj=lbl_r1[\"sky\"],"),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/v9/experiments/"], cwd=M, env=env, capture_output=True, text=True)
print("BASELINE", r.returncode, r.stdout.strip().splitlines()[-1])
for name, (fn, a, b) in muts.items():
    p = S5 / fn; orig = p.read_text(); assert orig.count(a) == 1, name
    p.write_text(orig.replace(a, b))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", "tests/v9/experiments/"], cwd=M, env=env, capture_output=True, text=True)
    p.write_text(orig)
    print(name, "KILLED" if r.returncode else "SURVIVED", [l.split("::")[-1][:50] for l in r.stdout.splitlines() if l.startswith("FAILED")])
