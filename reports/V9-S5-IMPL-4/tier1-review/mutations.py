import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]); F = M / "src/ainerzero/v9/experiments/s5/metrics.py"
muts = {
 "G1_ties_positive_first": ("order = np.lexsort((t_flat, -s_flat))", "order = np.lexsort((-t_flat, -s_flat))"),
 "G2_rank_off_by_one": ("ranks = np.arange(1, len(sorted_targets) + 1, dtype=np.float64)", "ranks = np.arange(2, len(sorted_targets) + 2, dtype=np.float64)"),
 "G3_mid_group_narrow": ('    "mid": (4, 6),', '    "mid": (4, 5),'),
 "G4_recall_strict": ("is_hit = (prob >= threshold)", "is_hit = (prob > threshold)"),
 "G5_floor_strict": ("mask = valid & (floor >= 0.5)", "mask = valid & (floor > 0.5)"),
 "G6_equal_pred_correct": ("if math.isnan(z_pred_a) or math.isnan(z_pred_b) or z_pred_a == z_pred_b:", "if math.isnan(z_pred_a) or math.isnan(z_pred_b):"),
 "G7_partial_and": ('occ_group = "partial" if (occ_a == "partial" or occ_b == "partial") else "full"', 'occ_group = "partial" if (occ_a == "partial" and occ_b == "partial") else "full"'),
 "G8_no_interp": ("    ratio = (target - a_prev) / denom\n    interp_step = s_prev + ratio * (s_curr - s_prev)", "    ratio = (target - a_prev) / denom\n    interp_step = s_curr"),
 "G9_target_090": ("target_ap = float(0.95 * a0_last_median)", "target_ap = float(0.90 * a0_last_median)"),
 "G10_mean_not_median": ("median_a4 = float(np.median(a4_steps))", "median_a4 = float(np.mean(a4_steps))"),
 "G11_no_replacement": ("boot_idx = rng.choice(n_worlds, size=n_worlds, replace=True)", "boot_idx = rng.permutation(n_worlds)"),
 "G12_expand_wrong_stride": ("return (w_arr[:, None] * clips_per_world + offsets[None, :]).ravel()", "return (w_arr[:, None] * (clips_per_world - 1) + offsets[None, :]).ravel()"),
 "G13_alpha_not_halved": ("lo = float(np.percentile(boot_vals, 100.0 * (alpha / 2.0)))", "lo = float(np.percentile(boot_vals, 100.0 * alpha))"),
 "G14_ga_censor_flag_dropped": ("        return float(cap), True\n\n    j = int(hits[0])", "        return float(cap), False\n\n    j = int(hits[0])"),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
def run():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", "tests/v9/experiments/test_s5_metrics.py"], cwd=M, env=env, capture_output=True, text=True)
    return r.returncode, [l.split("::")[-1][:50] for l in r.stdout.splitlines() if l.startswith("FAILED")], [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
print("imports from", subprocess.run([sys.executable, "-c", "import ainerzero;print(ainerzero.__file__)"], cwd=M, env=env, capture_output=True, text=True).stdout.strip())
print("BASELINE", *run())
orig = F.read_text()
for name, (a, b) in muts.items():
    n = orig.count(a)
    if n != 1: print(name, "ANCHOR COUNT", n); continue
    F.write_text(orig.replace(a, b)); rc, f, t = run(); F.write_text(orig)
    print(f"{name}: {'KILLED' if rc else 'SURVIVED'} {f[:2]} {t}", flush=True)
