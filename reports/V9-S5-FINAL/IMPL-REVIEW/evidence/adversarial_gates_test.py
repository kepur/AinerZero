import sys, os, json, math
from pathlib import Path
import numpy as np

# Assert non-production repo
copy_root = Path("/tmp/v9_s5_p248_copy").resolve()
real_repo = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
assert copy_root != real_repo, "Must not run in production repo!"
assert copy_root.is_dir(), f"Missing copy root: {copy_root}"

sys.path.insert(0, str(copy_root / "src"))
sys.path.insert(0, str(copy_root / "reports/V9-S5-PHASE1"))

import run_s5p1_final as final_runner
import recompute_s5p1_final as recompute

def setup_synthetic_data(tmp_path: Path, n_boot: int = 100):
    metrics_dir = tmp_path / "metrics"
    timing_dir = tmp_path / "timing"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    timing_dir.mkdir(parents=True, exist_ok=True)

    prereg = {
        "schema": "s5.phase1.prereg.v1",
        "a_star": "A1",
        "boot_seed": 42,
        "n_boot": n_boot,
        "gt_level": 1.0 - 0.05/3.0,
        "distill_seeds": [0, 1],
        "readout_seeds": [0, 1, 2],
        "supervised_seeds": [0, 1, 2],
        "ga_cap": 3840,
        "frozen": {
            "a_star": "A1",
            "n_boot": n_boot,
            "boot_seed": 42,
            "seeds": {
                "distill": [0, 1],
                "readout": [0, 1, 2],
                "A0": [0, 1, 2],
                "A4": [0, 1, 2],
                "A0-R": [0, 1, 2],
                "FT": [0, 1, 2],
            },
            "partitions": {"final": "s5p1-final", "final_shift": "s5p1-final-shift"},
            "ga_ratio_max": 0.7,
        },
        "gates": {
            "family_gt": {"bonferroni_m": 3, "alpha": 0.05, "ci_level": 1.0 - 0.05/3.0},
            "GT1": {"level": 1.0 - 0.05/3.0},
            "GT2": {"level": 1.0 - 0.05/3.0},
            "GT3": {"level": 1.0 - 0.05/3.0},
            "GA": {"max_median_step_ratio": 0.7},
            "GR": {"keep_max": 0.8, "wall_drop_min": 0.15, "ap_drop_ci_max": 0.03, "ci_level": 0.95},
        },
        "pinned_artifacts": {
            "dev_distill_run": str(tmp_path),
            "dev_distill_stage_sha256": "0"*64,
            "tune_file": str(tmp_path / "tune.json"),
            "tune_sha256": "0"*64,
            "distill_students": {},
            "readout_heads": {},
            "a0_l64_students": {},
            "a0_l64_heads": {},
            "dev_distill_a_star_step_s": {"distill-A1-s0": 0.30, "distill-A1-s1": 0.30},
        },
        "budget": {"budget_h": 10.0},
        "manifest": {},
    }
    (tmp_path / "PREREG.json").write_text(json.dumps(prereg, indent=1), encoding="utf-8")

    n_worlds = 6
    cpw = 16
    n_clips = n_worlds * cpw
    rng = np.random.default_rng(42)
    r2_target = (rng.uniform(size=(n_clips, 12, 7)) < 0.25).astype(np.int64)
    r3_target = (rng.uniform(size=(n_clips, 12, 7)) < 0.25).astype(np.int64)
    r1_target = rng.uniform(0.5, 2.5, size=(n_clips, 16, 14, 14)).astype(np.float32)
    r1_sky = np.zeros((n_clips, 16, 14, 14), dtype=np.float32)
    r1_obj = np.ones((n_clips, 16, 14, 14), dtype=np.float32)
    world_ids = np.arange(n_worlds, dtype=np.int64)

    def _make_ev(boost, noise, kr=None):
        r2_logit = r2_target.astype(np.float32) * float(boost) + rng.normal(0, 0.5, size=r2_target.shape).astype(np.float32)
        r3_logit = r3_target.astype(np.float32) * float(boost) + rng.normal(0, 0.5, size=r3_target.shape).astype(np.float32)
        r1_logd = r1_target + rng.normal(0, float(noise), size=r1_target.shape).astype(np.float32)
        ev = {
            "r1_logd": r1_logd, "r2_logit": r2_logit, "r3_logit": r3_logit,
            "r1_target": r1_target, "r1_sky": r1_sky, "r1_obj": r1_obj,
            "r2": r2_target, "r3": r3_target, "world_ids": world_ids,
            "clips_per_world": cpw, "threshold": 0.5,
            "disk_groups": [[] for _ in range(n_clips)],
            "ordering_pairs": [[] for _ in range(n_clips)],
            "metrics": {"r2_ap": 0.5, "r3_ap": 0.5, "r1_rmse": float(noise)},
        }
        if kr is not None:
            ev["keep_rate_per_clip"] = np.full(n_clips, float(kr), dtype=np.float64)
            ev["metrics"]["keep_rate"] = float(kr)
        return ev

    specs = final_runner.build_model_specs(prereg, tmp_path / "weights")
    for spec in specs:
        mid = spec["model_id"]
        arm = spec["arm"]
        boost = 2.5 if arm == "A1" else (2.4 if arm == "R" else 1.0)
        noise = 0.10 if arm in ("A1", "R") else 0.12
        kr = 0.65 if spec["tau"] is not None else None
        ev = _make_ev(boost, noise, kr=kr)
        for part in ("s5p1-final", "s5p1-final-shift", "s5p1-final-shift.shift_bg", "s5p1-final-shift.shift_all"):
            final_runner._save_eval_artifacts(metrics_dir, mid, part, ev)

    steps_16 = [240 * (i + 1) for i in range(16)]
    for arm_name, ap_curve in (("A0", [0.10 + 0.02 * i for i in range(16)]), ("A4", [0.25 + 0.02 * i for i in range(16)])):
        for s in (0, 1, 2):
            cid = f"ckpt-{arm_name}-L512-s{s}"
            cdoc = {"steps": steps_16, "r2_ap": ap_curve, "cap": 3840}
            (metrics_dir / f"{cid}.json").write_text(json.dumps(cdoc), encoding="utf-8")
            (metrics_dir / f"{cid}.s5p1-final.json").write_text(json.dumps(cdoc), encoding="utf-8")
            ev_dummy = _make_ev(1.5, 0.1)
            np.savez_compressed(
                metrics_dir / f"{cid}.s5p1-final.npz",
                r1_logd=ev_dummy["r1_logd"], r2_logit=ev_dummy["r2_logit"], r3_logit=ev_dummy["r3_logit"],
                r1_target=ev_dummy["r1_target"], r1_sky=ev_dummy["r1_sky"], r1_obj=ev_dummy["r1_obj"],
                r2=ev_dummy["r2"], r3=ev_dummy["r3"], world_ids=ev_dummy["world_ids"],
                clips_per_world=np.asarray(cpw, dtype=np.int64),
            )

    completed_cells = []
    for d in (0, 1):
        c_row = {"cell_id": f"distill-C-sh-s{d}", "median_step_total_s": 0.30, "wall_per_step_s": 0.30, "wall_s": 2250.0, "steps_logged": 7500}
        r_row = {"cell_id": f"distill-R-s{d}", "median_step_total_s": 0.22, "wall_per_step_s": 0.22, "wall_s": 1650.0, "steps_logged": 7500}
        final_runner._write_timing_file(timing_dir, c_row)
        final_runner._write_timing_file(timing_dir, r_row)
        completed_cells.extend([c_row, r_row])

    return prereg, metrics_dir, completed_cells

def test_baseline():
    tmp = Path("/tmp/s5_gate_test_base")
    if tmp.exists(): os.system(f"rm -rf {tmp}")
    prereg, metrics_dir, completed_cells = setup_synthetic_data(tmp)
    gates = final_runner.compute_gates_from_metrics(prereg, metrics_dir, completed_cells=completed_cells)
    recomp = recompute.recompute_all(tmp, tmp / "PREREG.json")
    diffs = recompute.compare_gates(recomp, gates)
    assert len(diffs) == 0, f"Baseline diffs: {diffs}"
    assert all(gates["gates"][g]["passed"] for g in ("GT1", "GT2", "GT3", "GA", "GR"))
    print("Baseline test PASSED (0 diffs with independent recompute, all gates pass)")

def test_mutation_1_seed_order():
    tmp = Path("/tmp/s5_gate_test_m1")
    if tmp.exists(): os.system(f"rm -rf {tmp}")
    prereg, metrics_dir, completed_cells = setup_synthetic_data(tmp)
    
    orig_fn = final_runner.nested_seed_mean_on_clips
    try:
        def bad_seed_mean(nested_group, clips, metric):
            outer_means = []
            for inner_list in nested_group:
                inner_vals = [final_runner.s5_eval.metric_value(ev, clips, metric) for ev in inner_list]
                outer_means.append(float(sum(inner_vals) / len(inner_vals)))
            return float(outer_means[0] * 0.8 + outer_means[1] * 0.2 if len(outer_means) == 2 else sum(outer_means)/len(outer_means))
        final_runner.nested_seed_mean_on_clips = bad_seed_mean
        gates = final_runner.compute_gates_from_metrics(prereg, metrics_dir, completed_cells=completed_cells)
        recomp = recompute.recompute_all(tmp, tmp / "PREREG.json")
        diffs = recompute.compare_gates(recomp, gates)
        assert len(diffs) > 0, "Mutation 1 was NOT caught by recompute comparison!"
        diff_keys = [str(d['gate']) + '.' + str(d['field']) for d in diffs]
        print("Mutation 1 (Seed order / asymmetric distill mean) CAUGHT! Detected", len(diffs), "diffs in:", diff_keys)
    finally:
        final_runner.nested_seed_mean_on_clips = orig_fn

def test_mutation_2_bonferroni_95():
    tmp = Path("/tmp/s5_gate_test_m2")
    if tmp.exists(): os.system(f"rm -rf {tmp}")
    prereg, metrics_dir, completed_cells = setup_synthetic_data(tmp)
    
    orig_level = final_runner.GT_LEVEL
    try:
        final_runner.GT_LEVEL = 0.95
        gates = final_runner.compute_gates_from_metrics(prereg, metrics_dir, completed_cells=completed_cells)
        recomp = recompute.recompute_all(tmp, tmp / "PREREG.json")
        diffs = recompute.compare_gates(recomp, gates)
        assert any("level" in (str(d['gate']) + '.' + str(d['field'])) for d in diffs), "Mutation 2 was NOT caught!"
        print("Mutation 2 (Bonferroni 95% level) CAUGHT! Detected diffs count:", len(diffs))
    finally:
        final_runner.GT_LEVEL = orig_level

def test_mutation_3_gt3_margin():
    tmp = Path("/tmp/s5_gate_test_m3")
    if tmp.exists(): os.system(f"rm -rf {tmp}")
    prereg, metrics_dir, completed_cells = setup_synthetic_data(tmp)
    
    orig_code = final_runner.compute_gates_from_metrics
    def bad_compute_gates(*args, **kwargs):
        res = orig_code(*args, **kwargs)
        res["gates"]["GT3"]["ci_upper"] = res["gates"]["GT3"]["ci_lower"]
        return res
    gates = bad_compute_gates(prereg, metrics_dir, completed_cells=completed_cells)
    recomp = recompute.recompute_all(tmp, tmp / "PREREG.json")
    diffs = recompute.compare_gates(recomp, gates)
    assert any("GT3" in (str(d['gate']) + '.' + str(d['field'])) for d in diffs), "Mutation 3 was NOT caught!"
    print("Mutation 3 (GT3 margin / upper CI tampered) CAUGHT! Detected diffs count:", len(diffs))

def test_mutation_4_ga_stair():
    tmp = Path("/tmp/s5_gate_test_m4")
    if tmp.exists(): os.system(f"rm -rf {tmp}")
    prereg, metrics_dir, completed_cells = setup_synthetic_data(tmp)
    
    orig_code = final_runner.compute_gates_from_metrics
    res = orig_code(prereg, metrics_dir, completed_cells=completed_cells)
    res["gates"]["GA"]["point_estimate"] += 0.05
    res["gates"]["GA"]["passed"] = False
    recomp = recompute.recompute_all(tmp, tmp / "PREREG.json")
    diffs = recompute.compare_gates(recomp, res)
    assert any("GA" in (str(d['gate']) + '.' + str(d['field'])) for d in diffs), "Mutation 4 was NOT caught!"
    print("Mutation 4 (GA ratio tampered) CAUGHT! Detected diffs count:", len(diffs))

def test_mutation_5_gr_wall_ref():
    tmp = Path("/tmp/s5_gate_test_m5")
    if tmp.exists(): os.system(f"rm -rf {tmp}")
    prereg, metrics_dir, completed_cells = setup_synthetic_data(tmp)
    
    orig_code = final_runner.compute_gates_from_metrics
    res = orig_code(prereg, metrics_dir, completed_cells=completed_cells)
    res["gates"]["GR"]["wall_drop"] = 0.05
    res["gates"]["GR"]["passed"] = False
    recomp = recompute.recompute_all(tmp, tmp / "PREREG.json")
    diffs = recompute.compare_gates(recomp, res)
    assert any("GR" in (str(d['gate']) + '.' + str(d['field'])) for d in diffs), "Mutation 5 was NOT caught!"
    print("Mutation 5 (GR wall drop tampered) CAUGHT! Detected diffs count:", len(diffs))

if __name__ == "__main__":
    print("=== S5 Final Runner Gates Adversarial Mutation Suite ===")
    test_baseline()
    test_mutation_1_seed_order()
    test_mutation_2_bonferroni_95()
    test_mutation_3_gt3_margin()
    test_mutation_4_ga_stair()
    test_mutation_5_gr_wall_ref()
    print("\nALL 5 GATE MUTATIONS VERIFIED AND CAUGHT SUCCESSFULLY!")
