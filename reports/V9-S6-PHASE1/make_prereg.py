"""生成 S6 一期预登记（reports/V9-S6-DESIGN/DESIGN-r2.md）。探针跑完、代码提交后运行一次，生成后提交，再启动 final 的训练。

用法：python make_prereg.py --design <定稿设计稿> --probe <探针评测报告> --out PREREG-r1.json

- 探针报告必须是正式运行器 eval --set probe 的输出：重放与复训校验通过、门算完，且用的是要冻结的已提交代码。
- 按探针每格的训练耗时与评测耗时外推 final：训练要在登记上限内（留 15% 余量），评测加校验要在评测上限内（留 30% 余量），否则拒绝。
"""
import argparse, hashlib, json, sys  # noqa: E401
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
from ainerzero.v9.experiments.s6 import analysis as AN  # noqa: E402

HERE = REPO / "reports/V9-S6-PHASE1"
RUNNER = HERE / "run_s6p1.py"
VERIFY = HERE / "verify_s6p1.py"
APPROVAL = "S6-P1-FINAL-READ-APPROVED-TIER1-20261115"


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
    if pr.get("set") != "probe" or not pr.get("verify", {}).get("passed") or "gates" not in pr.get("result", {}):
        raise SystemExit("探针报告不是一次校验通过、门已算完的 probe 运行")
    code = GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=[VERIFY])
    code_sha = hashlib.sha256(json.dumps(code, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if pr.get("code_manifest_sha256") != code_sha or pr.get("code_dirty") != []:
        raise SystemExit("探针不是用要冻结的、已提交的代码跑出来的")
    if pr.get("config") != pr.get("sets", {}).get("probe"):
        raise SystemExit("探针报告的配置与它记录的 probe 集不一致")
    final = pr["sets"]["final"]                 # set_summary("final") of the very runner that ran the probe
    reps_final = final["reps"]
    worlds_final, worlds_probe = tuple(final["worlds"]), tuple(pr["config"]["worlds"])
    train_cap_s, eval_limit_s = float(final["train_cap_s"]), float(final["eval_limit_s"])
    if final["test_ns"] != "s6p1-final" or final["cand_ns"] != "s6p1-cand":
        raise SystemExit(f"final 集的命名空间不对：{final['cand_ns']}, {final['test_ns']}")
    # Wall clock extrapolated from the probe (one replicate per arm).
    per_arm = {}
    for cell, sec in pr["train_seconds"].items():
        per_arm.setdefault(cell.split("-r")[0], []).append(sec)
    est_train = 1.15 * (sum(max(per_arm[arm]) * k for arm, k in reps_final.items()) + 5 * 90)
    n_cells_probe, n_cells_final = len(pr["train_seconds"]), sum(reps_final.values())
    est_eval = 1.30 * (pr["verify_seconds"] * n_cells_final / n_cells_probe
                       + pr["eval_seconds"] * n_cells_final / n_cells_probe * sum(worlds_final) / sum(worlds_probe))
    if est_train > train_cap_s or est_eval > eval_limit_s:
        raise SystemExit(f"预计超出上限：训练 {est_train:.0f} 秒（上限 {train_cap_s:.0f}），评测 {est_eval:.0f} 秒（上限 {eval_limit_s:.0f}）")
    doc = {
        "schema": "s6.phase1.prereg.v1",
        "design": str(design.relative_to(REPO)),
        "design_sha256": hashlib.sha256(design.read_bytes()).hexdigest(),
        "manifest": GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=[design, VERIFY]),
        "third_party": GD.third_party_versions(REPO, ("numpy", "mlx")),
        "probe_report": str(probe.relative_to(REPO)),
        "probe_report_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
        "code_manifest_sha256": code_sha,
        "sets": {"final": final},
        "arms": {"replicates": reps_final, "learners_per_cell": 3, "pick_seed_T_equals_R": True},
        "gates": {g: {k: (list(v) if isinstance(v, tuple) else v) for k, v in spec.items()} for g, spec in AN.GATES.items()},
        "statistics": {"alpha": AN.ALPHA, "bonferroni_m": AN.M, "world_bootstrap": {"n": AN.N_BOOT, "seed": AN.SEED},
                       "interval": "theta_hat -/+ t(K-1, 1-alpha/(2m)) * sqrt(s_rep^2/K + se_w^2); ratio gates on the log scale"},
        "expectations_from_exploration": {"GK-F": "expected to fail (round G E/Z free 1.177)", "GZ-D": "borderline (round G -0.014)"},
        "final_approval_line": APPROVAL,
        "budget": {"train_cap_s": train_cap_s, "eval_limit_s": eval_limit_s, "estimated_train_s": round(est_train),
                   "estimated_eval_s": round(est_eval), "device": "local MLX (GPU training, CPU scoring and evaluation)",
                   "cloud": False, "paid": False},
    }
    with out.open("x", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("written", out, "files frozen:", len(doc["manifest"]), "est train", round(est_train), "est eval", round(est_eval))


if __name__ == "__main__":
    main()
