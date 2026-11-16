"""生成 S6 一期预登记（reports/V9-S6-DESIGN/DESIGN-r3.md）。冻结代码提交后运行一次，生成后提交，再启动 final 的训练。

用法：python make_prereg.py --design <定稿设计稿> --probe <探针评测报告> --out PREREG-r1.json

依次检查（DESIGN-r3 §7 第 5 条），任何一条不过就拒绝，且不写任何文件：
- 没有 MLX_* 环境变量。
- 探针报告的字节与外部记录的 SHA 一致（PROBE_REPORT_SHA256；P262 复核 R1：报告里的计时没有原始文件可对照）。
- 探针的代码从 git 中探针提交的树里重算；当前要冻结的代码已提交，且与它只差运行器的三处登记常数（prereg_identity）。
- 探针的原始产物闭包完整，门与描述量从原始数组重算一致（prereg_evidence）。
- 按探针实测外推 final，在当前运行器的新上限之内（训练 19800 秒、评测 5400 秒）。
- 库版本从安装元数据读取，不为 unknown；final 运行器启动时记录的 {numpy, mlx.core} 与此一致。
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
import prereg_identity as PI  # noqa: E402

HERE = REPO / "reports/V9-S6-PHASE1"
RUNNER = HERE / "run_s6p1.py"
VERIFY = HERE / "verify_s6p1.py"
APPROVAL = "S6-P1-FINAL-READ-APPROVED-TIER1-20261115"
# The probe report as written when the probe eval finished (2026-11-15, codex P258; recorded in P261 metrics.json and the
# relay reports of P260/P261 before any builder ran). Frozen and reviewed with this builder.
PROBE_REPORT_SHA256 = "4a79000a646e8a817bd2916dd0471fb9ca221b2dac9d30fd67d00bc01ac16e9e"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True)
    ap.add_argument("--probe", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out, probe, design = Path(a.out), Path(a.probe).resolve(), Path(a.design).resolve()
    if out.exists():
        raise SystemExit(f"预登记已存在，不覆盖：{out}")
    PE.require(design.is_relative_to(REPO.resolve()) and design.name == "DESIGN-r3.md", "design must be the repository's DESIGN-r3.md")
    environment = PI.mlx_environment()
    data = probe.read_bytes()
    PE.require(hashlib.sha256(data).hexdigest() == PROBE_REPORT_SHA256, "probe report SHA differs from the recorded anchor")
    commit = json.loads(data).get("git_head")
    with PI.probe_tree(REPO, commit) as (probe_root, probe_code, probe_sha):
        current = PI.current_identity(REPO, probe_root, probe_code)
        sets = PE.source_sets(REPO, final_caps=PE.NEW_CAPS)
        pr, evidence = PE.validate_probe(REPO, probe, probe_root, probe_code, commit, PE.cpu_versions(REPO),
                                         expected_sha=PROBE_REPORT_SHA256)
    final = sets["final"]
    est_train, est_eval = PE.estimate_budget(pr, final)
    versions = PI.final_versions()
    dists = PI.distributions()
    mtime, start = dists["mlx"]["dist_info_mtime"], evidence["training_first_start"]
    PE.require(mtime is not None and mtime < start, "the installed MLX is newer than the probe: its version at probe time is unknown")
    doc = {
        "schema": "s6.phase1.prereg.v2",
        "design": str(design.relative_to(REPO)),
        "design_sha256": hashlib.sha256(design.read_bytes()).hexdigest(),
        "manifest": GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src",
                                      extra=[design, VERIFY, Path(__file__).resolve(), Path(PE.__file__).resolve(), Path(PI.__file__).resolve()]),
        "code_manifest_sha256": current["manifest_sha256"],
        "git_head": current["head"],
        "probe_identity": {"commit": commit, "code_manifest_sha256": probe_sha, "report": str(probe.relative_to(REPO)),
                           "report_sha256": PROBE_REPORT_SHA256},
        "runner_difference": {"changed_files": current["changed"], **current["runner_diff"]},
        "probe_evidence": evidence,
        "third_party": versions,
        "distributions": dists,
        "probe_mlx_version_inference": {"version": dists["mlx"]["version"], "dist_info_mtime": mtime, "probe_training_start": start,
                                        "basis": "the installed mlx distribution predates the probe's training start"},
        "mlx_environment": environment,
        "sets": {"final": final},
        "arms": {"replicates": final["reps"], "learners_per_cell": 3, "pick_seed_T_equals_R": True},
        "gates": {g: {k: (list(v) if isinstance(v, tuple) else v) for k, v in spec.items()} for g, spec in AN.GATES.items()},
        "statistics": {"alpha": AN.ALPHA, "bonferroni_m": AN.M, "world_bootstrap": {"n": AN.N_BOOT, "seed": AN.SEED},
                       "interval": "theta_hat -/+ t(K-1, 1-alpha/(2m)) * sqrt(s_rep^2/K + se_w^2); ratio gates on the log scale"},
        "expectations_from_exploration": {"GK-F": "expected to fail (round G E/Z free 1.177)", "GZ-D": "borderline (round G -0.014)"},
        "final_approval_line": APPROVAL,
        "budget": {"train_cap_s": final["train_cap_s"], "eval_limit_s": final["eval_limit_s"], "estimated_train_s": round(est_train),
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
