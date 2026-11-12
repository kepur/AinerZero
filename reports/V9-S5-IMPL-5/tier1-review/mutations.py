import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]).resolve()
assert str(M) != "/Users/mac/AinerWorkFlow/AinerZero", "refusing to mutate the live repository"
S5 = M / "src/ainerzero/v9/experiments/s5"
T = ["tests/v9/experiments/test_s5_data.py", "tests/v9/experiments/test_s5_train_mlx.py"]
muts = {
 "T1_csh_ignores_perm": ("train.py", "t_idx = perm_map[b_idx] if perm_map is not None else b_idx", "t_idx = b_idx"),
 "T2_r_arm_no_da2_valid": ("train.py", "                        valid_mask = keep_56\n", "                        valid_mask = None\n"),
 "T3_align_layer_plus1": ("train.py", "min(cfg.align_layer, len(model.student.blocks))", "min(cfg.align_layer + 1, len(model.student.blocks))"),
 "T4_ckpt_every_eighth": ("train.py", "ckpt_interval = max(1, int(round(total_steps * cfg.ckpt_every_frac)))", "ckpt_interval = max(1, int(round(total_steps * cfg.ckpt_every_frac * 2)))"),
 "T5_no_seed_supervised": ("train.py", "    \"\"\"端到端监督训练学生与读出头（A0、A4、A0-R、A* 全量微调）。\"\"\"\n    mx.random.seed(cfg.seed)", "    \"\"\"端到端监督训练学生与读出头（A0、A4、A0-R、A* 全量微调）。\"\"\"\n    pass"),
 "T6_no_teacher_sha_check": ("data.py", "            if got_sha != vjepa_ledger[vjepa_rel]:", "            if False and got_sha != vjepa_ledger[vjepa_rel]:"),
 "T7_batches_no_shuffle": ("data.py", "    perm = rng.permutation(n_items)", "    perm = np.arange(n_items)"),
 "T8_a2_loss_no_mask": ("train.py", "l_vjepa = cosine_distill_loss(proj_vjepa, vjepa_mx, mask=mask)", "l_vjepa = cosine_distill_loss(proj_vjepa, vjepa_mx, mask=None)"),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
def run():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-rf", *T], cwd=M, env=env, capture_output=True, text=True)
    return r.returncode, [l.split("::")[-1][:55] for l in r.stdout.splitlines() if l.startswith("FAILED")], [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
print("imports from", subprocess.run([sys.executable, "-c", "import ainerzero;print(ainerzero.__file__)"], cwd=M, env=env, capture_output=True, text=True).stdout.strip())
print("BASELINE", *run(), flush=True)
for name, (fn, a, b) in muts.items():
    p = S5 / fn; orig = p.read_text(); n = orig.count(a)
    if n != 1: print(name, "ANCHOR", n, flush=True); continue
    p.write_text(orig.replace(a, b)); rc, f, t = run(); p.write_text(orig)
    print(f"{name}: {'KILLED' if rc else 'SURVIVED'} {f[:3]} {t}", flush=True)
