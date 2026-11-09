"""生成 S3 第二阶段预登记。冻结前运行一次，生成后提交，再启动 dev。

用法：python make_prereg.py --capacity <16|64|256> --probe <probe 报告> --out PREREG-r1.json
"""
import argparse, hashlib, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import analysis_p2 as G, run_guard as GD

RUNNER = REPO / "reports/V9-S3-PHASE2/run_phase2.py"
DESIGN = REPO / "reports/V9-S3-PHASE2-DESIGN/DESIGN-r2.md"
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
    selected = json.loads(probe.read_text(encoding="utf-8")).get("selected_capacity")
    if selected != a.capacity:
        raise SystemExit(f"容量 {a.capacity} 与探针按规则选出的 {selected} 不一致")
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
        "optimizer": "Adam；梯度全局范数裁剪 1.0；F1 到 F2 优化器状态延续",
        "batch_seeds": {"F1": "seed", "F2": "seed + 1000", "J": "seed"},
        "sampling_key": "mx.random.key(批次种子)，每步 split",
        "perm_seed": "base + w * 100 + e；base 为 train F1 0、train F2 10000000、eval F1 20000000、eval F2 30000000",
        "seed_offsets": {"buffer": "7000000 + seed", "CN": "7100000 + seed", "N": "7200000 + perm_seed"},
        "utility_temperature": 0.5,
        "cue_lambda": 1.0,
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
