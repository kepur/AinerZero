import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]).resolve()
assert str(M) != "/Users/mac/AinerWorkFlow/AinerZero" and not str(M).startswith("/Users/mac/AinerWorkFlow/AinerZero/")
S5 = M / "src/ainerzero/v9/experiments/s5"; R = M / "reports/V9-S5-PHASE1/run_s5p1.py"
T = ["tests/v9/experiments/test_s5_data.py", "tests/v9/experiments/test_s5_train_mlx.py", "tests/v9/experiments/test_s5_student_mlx.py",
     "tests/v9/experiments/test_s5_runner_plan.py", "tests/v9/experiments/test_s5_runner_native.py"]
muts = {
 "S1_no_subset": (R, "    if label_n is not None:\n        return ClipIndex(partition_dir).subset_by_worlds(", "    if False and label_n is not None:\n        return ClipIndex(partition_dir).subset_by_worlds("),
 "S2_subset_seed_varies": (R, "plan.L_WORLDS[int(label_n)], seed=LAB_SUBSET_SEED", "plan.L_WORLDS[int(label_n)], seed=LAB_SUBSET_SEED + int(label_n)"),
 "C1_first_read_unverified": (S5 / "data.py", "    got_sha = _sha256_file(file_path)\n    if got_sha != expected_sha:", "    got_sha = expected_sha\n    if got_sha != expected_sha:"),
 "C2_cache_ignores_limit": (S5 / "data.py", "        if nbytes < 0 or self.used_bytes + nbytes > self.max_bytes:", "        if nbytes < 0:"),
 "C3_cache_key_collision": (S5 / "data.py", '    clip_key = f"clip:{clip_file.resolve()}"', '    clip_key = f"clip:{clip_file.name}"'),
 "F1_flat_reads_first_tubelet": (S5 / "heads.py", "        last = tokens.reshape(B, 8, 196, d)[:, 7]\n        scores = self.score", "        last = tokens.reshape(B, 8, 196, d)[:, 0]\n        scores = self.score"),
 "F2_flat_pools_positions": (S5 / "heads.py", "        scores = self.score(self.norm(last)).reshape(B, 196 * self.k)", "        scores = mx.broadcast_to(self.score(self.norm(last)).mean(axis=1, keepdims=True), (B, 196, self.k)).reshape(B, 196 * self.k)"),
 "F3_predict_r2_unrestored": (S5 / "train.py", "        r2_logit = heads_container[\"r2\"](r1_tokens)", "        r2_logit = heads_container[\"r2\"](tokens)"),
 "F4_supervised_gridhead": (S5 / "train.py", "        heads_dict[\"r2\"] = FlatHead(d=curr_student.d, k=4)", "        heads_dict[\"r2\"] = GridHead(out=(12, 7), d=curr_student.d, heads=curr_student.heads)"),
 "F5_heads_r2_unrestored": (S5 / "train.py", "                logits_r2 = model_heads[\"r2\"](r1_tokens)", "                logits_r2 = model_heads[\"r2\"](b_tokens)"),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
def run(x=True):
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-rf"] + (["-x"] if x else []) + T
    r = subprocess.run(args, cwd=M, env=env, capture_output=True, text=True, timeout=5400)
    return r.returncode, [l.split("::")[-1][:55] for l in r.stdout.splitlines() if l.startswith("FAILED") or l.startswith("ERROR")], [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
rc, f, t = run(x=False); print("BASELINE", rc, f, t, flush=True)
if rc != 0:
    print("baseline failed; mutation results would be meaningless"); sys.exit(1)
for name, (p, a, b) in muts.items():
    orig = p.read_text(); n = orig.count(a)
    if n != 1: print(name, "ANCHOR", n, flush=True); continue
    p.write_text(orig.replace(a, b)); rc, f, t = run(); p.write_text(orig)
    print(f"{name}: {'KILLED' if rc else 'SURVIVED'} {f[:2]} {t}", flush=True)
