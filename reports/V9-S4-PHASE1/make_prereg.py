"""生成 S4 第一阶段预登记。冻结前运行一次，生成后提交，再启动 final。

用法：python make_prereg.py --design <定稿设计稿> --probe <探针报告> --out PREREG-r1.json
探针报告必须是正式运行器在 s4p1-probe 上、用要冻结的已提交代码跑出的有效结果；final 的训练步数与批大小
取自这份探针报告。
"""
import argparse, hashlib, json, math, sys  # noqa: E401
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import filter as F  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import metrics as Me  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

HERE = REPO / "reports/V9-S4-PHASE1"
RUNNER = HERE / "run_s4p1.py"
VERIFY = [HERE / "verify_labels.py", HERE / "verify_replay.py"]
APPROVAL = "S4-P1-FINAL-READ-APPROVED-TIER1-20261110"
HARD_LIMIT_S = 4 * 3600


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True)
    ap.add_argument("--probe", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out, probe, design = Path(a.out), Path(a.probe).resolve(), Path(a.design).resolve()
    if out.exists():
        raise SystemExit(f"预登记已存在，不覆盖：{out}")
    pr = json.loads(probe.read_text(encoding="utf-8"))
    if pr.get("stage") != "probe" or pr.get("namespaces", {}).get("eval") != A.NAMESPACES["probe"] or not pr.get("result", {}).get("valid"):
        raise SystemExit("探针报告不是 s4p1-probe 上的有效正式运行")
    code = GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=VERIFY)
    code_sha = hashlib.sha256(json.dumps(code, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if pr.get("code_manifest_sha256") != code_sha or pr.get("code_dirty") != []:
        raise SystemExit("探针不是用要冻结的、已提交的代码跑出来的")
    # Wall clock: the final evaluates 4x the probe's worlds; 1.5x margin on the probe's evaluation and checks.
    scale = sum(A.SIZES["final"]) / sum(A.SIZES["probe"])
    eval_reserve = math.ceil(1.5 * scale * (pr["eval_seconds"] + pr["check_seconds"]))
    train_s = pr["training"]["pool_seconds"] + sum(c["seconds"] for c in pr["training"]["cells"].values())
    if 1.2 * train_s + eval_reserve > HARD_LIMIT_S:
        raise SystemExit(f"预计超出硬上限：训练约 {train_s:.0f} 秒，评测预留 {eval_reserve} 秒")
    cfg = F.FilterConfig()
    doc = {
        "schema": "s4.phase1.prereg.v1",
        "design": str(design.relative_to(REPO)),
        "manifest": GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=[design, *VERIFY]),
        "third_party": GD.third_party_versions(REPO, ("numpy", "mlx")),
        "probe_report": str(probe.relative_to(REPO)),
        "probe_report_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
        "namespaces": A.NAMESPACES,
        "world": {"arena": W.ARENA, "radius": W.RADIUS, "dt": W.DT, "substeps": W.SUBSTEPS, "speed": list(W.SPEED), "pillars": W.N_PILLARS,
                  "steps": W.STEPS, "fov_deg": 180, "view_range": W.VIEW_RANGE, "sigma": W.SIGMA, "p_miss": W.P_MISS,
                  "train_worlds": A.N_TRAIN, "train_disks": list(A.TRAIN_DISKS), "main": {"disks": A.MAIN_DISKS, "worlds": A.SIZES["final"][0]},
                  "extrapolation": {"disks": A.EXTRAP_DISKS, "worlds": A.SIZES["final"][1], "first_index": A.EXTRAP_OFFSET}},
        "filter": {"members": cfg.members, "q_pos": cfg.q_pos, "q_vel": cfg.q_vel, "obs_sigma": cfg.obs_sigma, "gate_base": cfg.gate_base,
                   "gate_grow": cfg.gate_grow, "new_track_speed": list(cfg.speed), "noise_scales": [1.0, *A.NOISE_SCALES], "gate_variants": A.GATE_VARIANTS},
        "training": {"steps": pr["steps"], "batch": pr["batch"], "lr": 1e-3, "seeds": list(A.SEEDS), "pool": pr["training"]["pools"],
                     "perturbation": {"p_hidden": L.P_HIDDEN, "visible_sigma": list(L.VISIBLE_SIGMA), "hidden_sigma": list(L.HIDDEN_SIGMA),
                                      "p_drop": L.P_DROP, "ghosts": L.GHOSTS, "ghost_sigma": L.GHOST_SIGMA, "exact_frac": L.EXACT_FRAC},
                     "rollout": list(L.ROLLOUT), "contact_weight": L.CONTACT_WEIGHT, "msg_radius": L.MSG_RADIUS, "hidden": L.HID, "message": L.MSG,
                     "collision_share_per_batch": L.COLL_SHARE, "near_miss_share_per_batch": L.NEAR_SHARE, "near_miss_gap": L.NEAR_GAP,
                     "grad_clip_norm": L.CLIP, "direction_softening": L.EPS_DIR, "lr_end": L.LR_END, "rollout_weights": list(L.ROLLOUT_WEIGHTS),
                     "position_loss_scale": L.P_SCALE, "logvar_range": list(L.LOGVAR_RANGE),
                     "device": "MLX GPU (local)", "cell_limit_s": 600},
        "gates": A.THRESHOLDS,
        "legality": {"expected_collision_events_per_40": A.EXPECTED_COLL_EVENTS_PER_40, "sample_band": A.SAMPLE_BAND,
                     "expected_collision_disk_steps_per_40": A.EXPECTED_COLL_DISK_STEPS_PER_40, "dyn_floor": A.DYN_FLOOR},
        "statistics": {"bootstrap": {"n": Me.BOOT_N, "seed": Me.BOOT_SEED, "unit": "world", "level": Me.LEVEL}, "bonferroni_m": A.N_COMPARISONS,
                       "seed_average": "per event over seeds 1-3", "graze_margin": Me.GRAZE_MARGIN},
        "code_manifest_sha256": code_sha,
        "final_approval_line": APPROVAL,
        "budget": {"hard_limit_minutes": HARD_LIMIT_S // 60, "eval_reserve_s": eval_reserve, "probe_train_seconds": round(train_s, 1),
                   "device": "local MLX GPU for training, CPU for evaluation", "cloud": False, "paid": False},
    }
    with out.open("x", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("written", out, "files frozen:", len(doc["manifest"]))


if __name__ == "__main__":
    main()
