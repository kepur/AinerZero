"""生成 S6 一期预登记（reports/V9-S6-DESIGN/DESIGN-r2.md）。探针跑完、代码提交后运行一次，生成后提交，再启动 final 的训练。

用法：python make_prereg.py --design <定稿设计稿> --probe <探针评测报告> --out PREREG-r1.json

- 探针报告必须是正式运行器 eval --set probe 的输出：重放与复训校验通过、门算完，且用的是要冻结的已提交代码。
- 按探针每格的训练耗时与评测耗时外推 final：训练要在登记上限内（留 15% 余量），评测加校验要在评测上限内（留 30% 余量），否则拒绝。
"""
import argparse  # noqa: E401
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
from ainerzero.v9.experiments.s6 import analysis as AN  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prereg_evidence as PE  # noqa: E402

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
    code = GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=[VERIFY])
    versions = PE.cpu_versions(REPO)
    pr, evidence = PE.validate_probe(REPO, probe, code, versions)
    code_sha = PE.manifest_sha(code)
    est_train, est_eval = PE.estimate_budget(pr)
    final = pr["sets"]["final"]
    reps_final = final["reps"]
    train_cap_s, eval_limit_s = final["train_cap_s"], final["eval_limit_s"]
    doc = {
        "schema": "s6.phase1.prereg.v1",
        "design": str(design.relative_to(REPO)),
        "design_sha256": hashlib.sha256(design.read_bytes()).hexdigest(),
        "manifest": GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=[design, VERIFY, Path(__file__).resolve(), Path(PE.__file__).resolve()]),
        "third_party": versions,
        "probe_evidence": evidence,
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
    # Serialize and recheck before the only write. Refusals leave no output file.
    serialized = json.dumps(doc, ensure_ascii=False, indent=1, allow_nan=False)
    PE.require(not GD.check_manifest(REPO, evidence["files_sha256"]), "evidence changed before output")
    PE.require(not GD.check_manifest(REPO, doc["manifest"]), "source changed before output")
    with out.open("x", encoding="utf-8") as fh:
        fh.write(serialized)
    print("written", out, "files frozen:", len(doc["manifest"]), "est train", round(est_train), "est eval", round(est_eval))


if __name__ == "__main__":
    main()
