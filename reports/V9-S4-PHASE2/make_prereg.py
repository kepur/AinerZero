"""生成 S4 第二阶段预登记。冻结前运行一次，生成后提交，再启动 final。

用法：python make_prereg.py --design <定稿设计稿> --probe <探针报告> --out PREREG-r1.json
探针报告必须是正式运行器在 s4p2-probe 上、用要冻结的已提交代码跑出的有效结果。
"""
import argparse, hashlib, json, math, sys  # noqa: E401
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis_p2 as P2  # noqa: E402
from ainerzero.v9.experiments.s4 import filter as F  # noqa: E402
from ainerzero.v9.experiments.s4 import metrics as Me  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

HERE = REPO / "reports/V9-S4-PHASE2"
RUNNER = HERE / "run_s4p2.py"
VERIFY = [HERE / "verify_labels_p2.py", HERE / "verify_replay_p2.py"]
APPROVAL = "S4-P2-FINAL-READ-APPROVED-TIER1-20261111"
HARD_LIMIT_S = 2 * 3600


def runner_weights():
    """The runner's registered weight SHAs, read from its source (the runner imports MLX)."""
    import ast
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "WEIGHTS_SHA256" for t in node.targets):
            return ast.literal_eval(node.value)
    raise SystemExit("运行器里没有 WEIGHTS_SHA256")


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
    if pr.get("stage") != "probe" or pr.get("namespace") != P2.NAMESPACES["probe"] or not pr.get("result", {}).get("valid"):
        raise SystemExit("探针报告不是 s4p2-probe 上的有效正式运行")
    code = GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=VERIFY)
    code_sha = hashlib.sha256(json.dumps(code, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if pr.get("code_manifest_sha256") != code_sha or pr.get("code_dirty") != []:
        raise SystemExit("探针不是用要冻结的、已提交的代码跑出来的")
    weights = runner_weights()
    if pr.get("weights_sha256") != weights:
        raise SystemExit("探针用的权重与运行器登记的不一致")
    # Wall clock: the final evaluates 4x the probe's worlds; 1.5x margin on everything after the marker.
    scale = sum(P2.SIZES["final"]) / sum(P2.SIZES["probe"])
    eval_reserve = math.ceil(1.5 * scale * pr["post_marker_seconds"])
    if 1.2 * pr["pre_eval_seconds"] + eval_reserve > HARD_LIMIT_S:
        raise SystemExit(f"预计超出硬上限：评测预留 {eval_reserve} 秒")
    cfg = F.FilterConfig()
    doc = {
        "schema": "s4.phase2.prereg.v1",
        "design": str(design.relative_to(REPO)),
        "manifest": GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=[design, *VERIFY]),
        "third_party": GD.third_party_versions(REPO, ("numpy", "mlx")),
        "probe_report": str(probe.relative_to(REPO)),
        "probe_report_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
        "namespaces": P2.NAMESPACES,
        "world": {"arena": W.ARENA, "radius": W.RADIUS, "dt": W.DT, "substeps": W.SUBSTEPS, "speed": list(W.SPEED), "pillars": W.N_PILLARS,
                  "steps": W.STEPS, "fov_deg": 180, "view_range": W.VIEW_RANGE, "sigma": W.SIGMA, "p_miss": W.P_MISS,
                  "main": {"disks": 6, "worlds": P2.SIZES["final"][0]}, "extrapolation": {"disks": 10, "worlds": P2.SIZES["final"][1], "first_index": 1000}},
        "filter": {"members": cfg.members, "q_pos": cfg.q_pos, "q_vel": cfg.q_vel, "obs_sigma": cfg.obs_sigma, "gate_base": cfg.gate_base,
                   "gate_grow": cfg.gate_grow, "new_track_speed": list(cfg.speed), "filter_seed": "derive_seed(ns, 'filter', world, seed, 'base')"},
        "arms": {"hand": list(P2.HAND), "learned": list(P2.LEARNED), "gates": P2.GATES, "base_model": P2.BASE_MODEL,
                 "main": P2.MAIN_ARM, "negative_control": P2.NEG_ARM, "seeds": list(P2.SEEDS)},
        "weights_sha256": weights,
        "weights_dir": "artifacts/v9/s4/phase1/final-final/weights",
        "gates": P2.THRESHOLDS,
        "legality": {"expected_collision_events_per_40": P2.EXPECTED_COLL_EVENTS_PER_40, "sample_band": P2.SAMPLE_BAND,
                     "expected_collision_disk_steps_per_40": P2.EXPECTED_COLL_DISK_STEPS_PER_40, "dyn_floor": P2.DYN_FLOOR},
        "statistics": {"bootstrap": {"n": Me.BOOT_N, "seed": P2.BOOT_SEED, "unit": "world", "level": Me.LEVEL}, "bonferroni_m": P2.N_COMPARISONS,
                       "seed_average": "correctness and reappearance coverage per event over seeds 1-3; one-step rows of the three seeds pooled",
                       "graze_margin": Me.GRAZE_MARGIN, "gap_bins": list(P2.GAP_BINS)},
        "code_manifest_sha256": code_sha,
        "final_approval_line": APPROVAL,
        "budget": {"hard_limit_minutes": HARD_LIMIT_S // 60, "eval_reserve_s": eval_reserve, "probe_post_marker_seconds": pr["post_marker_seconds"],
                   "device": "local CPU (MLX CPU device)", "cloud": False, "paid": False, "training": False},
    }
    with out.open("x", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("written", out, "files frozen:", len(doc["manifest"]))


if __name__ == "__main__":
    main()
