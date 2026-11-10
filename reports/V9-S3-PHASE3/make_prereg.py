"""生成 S3 第三阶段预登记。冻结前运行一次，生成后提交，再启动 dev。

用法：python make_prereg.py --design <定稿设计稿> --probe <探针报告> --out PREREG-r1.json
探针报告必须是正式运行器在 s3p3-probe 上的有效结果。
"""
import argparse, hashlib, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import analysis_p3 as A, persist as PS, promotion as PR, run_guard as GD

RUNNER = REPO / "reports/V9-S3-PHASE3/run_phase3.py"
VERIFY = REPO / "reports/V9-S3-PHASE3/verify_worlds.py"
VERIFY_GEN = REPO / "reports/V9-S3-PHASE3/verify_generation.py"
APPROVAL = "S3-P3-FINAL-READ-APPROVED-TIER1-20261110"


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
    if pr.get("stage") != "probe" or pr.get("namespace") != A.NAMESPACES["probe"] or not pr.get("result", {}).get("valid"):
        raise SystemExit("探针报告不是 s3p3-probe 上的有效正式运行")
    code = GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=[VERIFY, VERIFY_GEN])
    code_sha = hashlib.sha256(json.dumps(code, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if pr.get("code_manifest_sha256") != code_sha or pr.get("code_dirty") != []:
        raise SystemExit("探针不是用要冻结的、已提交的代码跑出来的")
    doc = {
        "schema": "s3.phase3.prereg.v1",
        "design": str(design.relative_to(REPO)),
        "manifest": GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=[design, VERIFY, VERIFY_GEN]),
        "third_party": GD.third_party_versions(REPO, ("numpy",)),
        "probe_report": str(probe.relative_to(REPO)),
        "probe_report_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
        "namespaces": A.NAMESPACES,
        "world": {
            "persistent": PS.N_PERSISTENT, "volatile": PS.N_VOLATILE, "episodes": PS.N_EPISODES, "steps": 360,
            "p_decoy": PS.P_DECOY, "relocation_episode": PS.RELOCATION_EPISODE, "p_relocate": PS.P_RELOCATE,
            "min_cell_dist": PS.MIN_CELL_DIST, "swap_window": list(PS.SWAP_WINDOW), "tokens": "F1",
            "seeds": "derive_seed(ns, 'world', w)、(ns, 'persist', w)、(ns, 'ep', w, e)",
        },
        "memory": {"d_max": PR.D_MAX, "sim_min": PR.SIM_MIN, "cue_lambda": PR.LAM, "min_votes": PR.MIN_VOTES, "rule": "R2", "fast_gap": A.GAP, "tie": A.TIE},
        "contract": {"expected_per_100_worlds": A.EXPECTED_PER_100, "sample_band": A.SAMPLE_BAND, "code_manifest_sha256": code_sha},
        "descriptive": {"comparisons": [list(c) for c in A.COMPARISONS], "offset_comparisons": [list(c) for c in A.OFFSET_COMPARISONS],
                        "alphas": A.ALPHAS, "offsets": list(A.OFFSETS), "bootstrap": {"n": A.BOOT_N, "seed": A.BOOT_SEED, "unit": "world", "level": A.LEVEL},
                        "bonferroni_m": A.N_COMPARISONS, "perm_seed": "derive_seed(ns, 'perm', w)", "offset_seed": "derive_seed(ns, 'offset', w, e, k)"},
        "sizes": {"probe": 100, "final": 200},
        "dev_max_uses": 0,
        "final_approval_line": APPROVAL,
        "budget": {"hard_limit_minutes_per_run": 30, "device": "CPU", "cloud": False, "paid": False},
    }
    with out.open("x", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("written", out, "files frozen:", len(doc["manifest"]))


if __name__ == "__main__":
    main()
