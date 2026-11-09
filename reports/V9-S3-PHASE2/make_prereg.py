"""生成 S3 第二阶段预登记。冻结前运行一次，生成后提交，再启动 dev。

用法：python make_prereg.py --capacity <16|64|256> --probe <probe 报告> --out PREREG-r1.json
"""
import argparse, hashlib, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import analysis_p2 as G, run_guard as GD

RUNNER = REPO / "reports/V9-S3-PHASE2/run_phase2.py"
DESIGN = REPO / "reports/V9-S3-PHASE2-DESIGN/DESIGN-r1.md"
APPROVAL = "S3-P2-FINAL-READ-APPROVED-TIER1-20261109"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capacity", type=int, required=True, choices=G.CAPACITIES)
    ap.add_argument("--probe", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        raise SystemExit(f"预登记已存在，不覆盖：{out}")
    probe = Path(a.probe)
    doc = {
        "schema": "s3.phase2.prereg.v1",
        "design": str(DESIGN.relative_to(REPO)),
        "manifest": GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=[DESIGN]),
        "third_party": GD.third_party_versions(REPO, ("numpy", "mlx.core")),
        "probe_report": str(probe.resolve().relative_to(REPO)),
        "probe_report_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
        "namespaces": G.NAMESPACES,
        "seeds": [1, 2, 3],
        "steps": {"F1": 2000, "F2": 1000},
        "batch": 16,
        "replay_mix": [8, 8],
        "lr": 1e-3,
        "h3_capacity": a.capacity,
        "gates": {
            "chance": G.CHANCE,
            "floor": G.FLOOR,
            "upper_O": G.UPPER_MIN,
            "unswapped_min": G.UNSWAPPED_MIN,
            "H1_min_delta": G.H1_MIN_DELTA,
            "H2_min_delta": G.H2_MIN_DELTA,
            "H2b_min_delta": G.H2B_MIN_DELTA,
            "H3_margin_upper_bound": G.H3_MARGIN,
            "interference_min_8class": G.INTERFERENCE_MIN,
            "content_min_8class": G.CONTENT_MIN,
            "min_events_per_seed": G.MIN_EVENTS_PER_SEED,
            "min_episodes_per_seed": G.MIN_EPISODES_PER_SEED,
        },
        "dev_max_uses": 2,
        "final_approval_line": APPROVAL,
        "budget": {"hard_limit_hours_per_run": 1.5, "device": "MLX CPU", "cloud": False, "paid": False},
    }
    with out.open("x", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("written", out, "files frozen:", len(doc["manifest"]))


if __name__ == "__main__":
    main()
