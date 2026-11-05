"""T28 r2 构建脚本（作者 claude-az，2026-10-27）。

做法：读入 r1 的 proposal.json（先核对它与 proposal.sha256 一致），只施加 CHANGES 里枚举的修改，每处断言旧值；
所以"没列出的字段与 r1 逐字节一致"可以被机器证明（见 diff_r1_r2.json 与 check_r2.py）。
r1 的任何文件都不被改写。用户批准：2026-10-27 选项 A（见 AMENDMENT.md）；2026-10-28 第二次批准（删除 half_parity，cpu_parity 保持现状）。
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
T28 = HERE.parent
REPO = T28.parents[1]
DA3_SRC = REPO / "envs/teachers/t6/Depth-Anything-3/src/depth_anything_3"

USER_APPROVAL = {
    "date": "2026-10-27",
    "where": "一级 claude-az 会话",
    "verbatim": ("按选项 A 修订 T28：known_intrinsics 改为 false（模型自估内参），去掉内参逆向控制，保留逆序控制和 CPU 边界守卫；"
                 "请起草 T28 r2 并新建独立数学复核卡，配额口径我另行告知"),
}


USER_APPROVAL_2 = {
    "date": "2026-10-28",
    "where": "一级 claude-az 会话",
    "verbatim": ("选 A：从 T28 r2 删除 half_parity（每型号 9 次/25 视图，合计 18 次/50 视图），你修订 r2 并做差异复核；"
                 "cpu_parity 保持现状。配额口径我另行告知。"),
}


USER_DECISION_3 = {
    "date": "2026-10-28",
    "where": "一级 claude-az 会话",
    "verbatim": "配额口径用前向视图（诚实口径，每次记 50）。具体数字我随后告知；你先不要动账本。",
}


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: Path) -> str:
    return sha_bytes(p.read_bytes())


def canon(v) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def expect(actual, expected, what):
    assert actual == expected, f"r1 value mismatch at {what}: {actual!r} != {expected!r}"


def line_of(path: Path, needle: str) -> int:
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not found in {path}")


def amend(p1: dict, r1_sha: str) -> dict:
    p = copy.deepcopy(p1)

    # E1 身份与溯源
    expect(p["protocol_id"], "codex-da3-known-k-anchored-diagnostic-20261026-r1", "protocol_id")
    p["protocol_id"] = "da3-model-k-anchored-diagnostic-20261027-r2"
    expect(p["supersedes"], None, "supersedes")
    p["supersedes"] = {"protocol_id": "codex-da3-known-k-anchored-diagnostic-20261026-r1", "proposal_sha256": r1_sha,
                       "reason": "r1 的已知 K 条件化与内参逆向控制在这版 DA3 上不可满足，见 amendment.evidence"}
    expect(p["author"], "codex", "author")
    p["author"] = "claude-az"
    expect(p["review_task"], "ainerzero.V9.T29", "review_task")
    p["review_task"] = "ainerzero.V9.T39"      # T39 复核后补入（初稿曾置 null，被复核人指出与 amendment.changes 自相矛盾）
    expect(p["status"], "proposal_unapproved", "status")
    expect(p["execution_permitted"], False, "execution_permitted")

    # E2 profile：模型自估内参
    prof = p["profile"]
    expect(prof["known_intrinsics"], True, "profile.known_intrinsics")
    prof["known_intrinsics"] = False
    expect(prof["assumption"], "known-K synthetic input, not blind intrinsic recovery, metric scale or Blender generalization",
           "profile.assumption")
    prof["assumption"] = ("no camera parameters are supplied to the teacher (neither intrinsics nor extrinsics); the teacher's own focal "
                          "readout is descriptive only and is not a conditioning; not known-K conditioned, not blind intrinsic recovery, "
                          "not metric scale, not Blender generalization")
    prof["intrinsics_policy"] = {
        "conditioning": "none",
        "ground_truth_K": "recorded for the descriptive comparison only; never supplied to the teacher",
        "predicted_vs_ground_truth_K": ("report per view: predicted fx and fy and their ratios to the ground-truth fx and fy at the same "
                                        "resolution (process_res=280 gives 210x280, no rescale or crop); descriptive only, not part of the "
                                        "7-vector, the score, the fit statistics or any threshold"),
        "principal_point_excluded": ("DA3's camera decoder hard-codes the predicted principal point at (W/2, H/2); it is not estimated. The "
                                     "ground truth uses the pixel-centre convention ((W-1)/2, (H-1)/2), so the two differ by a constant 0.5 px "
                                     "convention offset that is not a model error. cx and cy are therefore excluded from the comparison."),
    }

    # E3 原始指标里的"已知 K"条目改为描述性
    raw = p["residual_vector"]["raw_metrics"]
    expect(raw[-1], "predicted_intrinsics_and_source_known_K", "raw_metrics[-1]")
    raw[-1] = "predicted_intrinsics_vs_ground_truth_K_descriptive_only"

    # E4 数值对拍引用
    par = p["numerical_parity"]
    expect(par["reference"], "world00 known-K MPS-F32 calibration output", "numerical_parity.reference")
    par["reference"] = "world00 MPS-F32 calibration output (model-estimated K)"

    par["known_risks"] = [
        ("reference-view selection is discrete: with no cam_token DA3 picks the reference view by an argmin over 3 views and reorders. "
         "A flip of that argmin between CPU and MPS changes the output frame and fails the elementwise gate by O(1) regardless of tolerance; "
         "the user decided on 2026-10-28 to keep the cpu_parity rule as written, so a red cpu_parity is reported as is (exit 5, evidence retained)"),
    ]
    # E15（2026-10-28，用户批准选项 A）：half_parity 阶段退役。容差键保持原值不动（runner 的 load_plan 仍读取它），但没有任何阶段使用。
    par["retired_stages"] = [{
        "stage": "half_parity",
        "tolerance_key": "mps_float16",
        "tolerance_kept_unchanged_and_unused": True,
        "reason": ("it cannot complete in this build: pipeline.py ExplicitPrecisionDA3 disables autocast and casts the whole network to float16, "
                   "while upstream CameraDec.forward hard-codes self.fc_t(feat.float()). The fp32 input meets an fp16 Linear and CPU raises "
                   "'mat1 and mat2 must have the same dtype, but got Float and Half'; this was reproduced independently by V9.T46 (.venv, "
                   "torch 2.3.1) and by the lead in envs/teachers/.venv-t6 (torch 2.14.1), CPU only, no DA3 weights. "
                   "On MPS the lead reported a Metal assertion that aborts the process (SIGABRT, exit 134); no crash log was kept, so this "
                   "is a report, not an independently reproduced fact, and the removal does not depend on it. "
                   "It is the last stage of DA3-SMALL, so it would fail before DA3-BASE starts, and the authorization is already "
                   "reserved and not refunded"),
        "evidence": {"cam_dec": {"file": "envs/teachers/t6/Depth-Anything-3/src/depth_anything_3/model/cam_dec.py",
                                 "line": line_of(DA3_SRC / "model/cam_dec.py", "out_t = self.fc_t(feat.float())"),
                                 "sha256": sha_file(DA3_SRC / "model/cam_dec.py")},
                     "pipeline": {"file": "envs/teachers/t6/pipeline.py",
                                  "line": line_of(REPO / "envs/teachers/t6/pipeline.py", "class ExplicitPrecisionDA3(DepthAnything3):"),
                                  "sha256": sha_file(REPO / "envs/teachers/t6/pipeline.py")},
                     "reproduction": "reports/V9-T40/DECISIONS_FOR_USER.md section 1 (no DA3 weights involved)"},
        "not_replaced": ("no substitute fp16 control is introduced; option B (autocast-based fp16 in pipeline.py) was not chosen, "
                         "so pipeline.py is unchanged and its SHA bindings remain valid. If an fp16 consistency gate is wanted later: "
                         "torch.autocast(device_type='mps') constructs in envs/teachers/.venv-t6 (torch 2.14.1), but model/da3.py:139 wraps the "
                         "depth head and the camera estimation in autocast(enabled=False), so an outer autocast leaves those parts outside "
                         "fp16. That would be a partial-fp16 gate and needs its own pre-registration stating what it covers"),
    }]

    # E5 负对照：去掉内参逆向控制，保留逆序控制
    nc = p["negative_controls"]
    expect(nc["intrinsics"], "multiply only focal_x by1.5 and focal_y by0.75 for all3views; retain positive focal and principal point",
           "negative_controls.intrinsics")
    del nc["intrinsics"]
    expect(nc["same_clean_profile"],
           "all positive calls conditioned on exact frozen K; adverse K uses predeclared changed K", "negative_controls.same_clean_profile")
    nc["same_clean_profile"] = "all positive calls use the same model-estimated-K profile; no K is supplied to any call"
    nc["real_forward_controls"] = ["frame_order_adverse"]
    nc["frame_order_adverse_meaning"] = ("association-reversal control: it checks that the scoring pipeline is sensitive to a wrong RGB-to-label "
                                         "association (the anchor and scale slots receive different physical cameras). It does NOT test temporal "
                                         "or cross-view reasoning of the teacher")
    nc["removed_controls"] = [{
        "name": "intrinsics_adverse",
        "reason": ("unsatisfiable by construction in this DA3 build: intrinsics are ignored unless extrinsics are supplied, so the "
                   "prediction cannot depend on K and S_bad == S_clean < S_clean + max(0.0001, 0.1*S_clean)"),
        "evidence": "see amendment.evidence",
        "not_replaced": "no substitute control is introduced by this amendment; a K-sensitive control needs its own pre-registration",
    }]

    # E6 预算：去掉 intrinsics_adverse 阶段；E15（2026-10-28）再去掉 half_parity 阶段，重算
    models = p["budget"]["models"]
    for m in models:
        names = [s["stage"] for s in m["stages"]]
        expect(names, ["first_frame", "calibration", "frame_order_adverse", "intrinsics_adverse", "cpu_parity", "half_parity"],
               f"budget.models[{m['variant']}].stages")
        expect((m["forward_calls"], m["forward_views"]), (11, 31), f"{m['variant']} totals")
        m["stages"] = [s for s in m["stages"] if s["stage"] not in ("intrinsics_adverse", "half_parity")]
        assert [s["stage"] for s in m["stages"]] == ["first_frame", "calibration", "frame_order_adverse", "cpu_parity"]
        m["forward_calls"] = sum(s["calls"] for s in m["stages"])
        m["forward_views"] = sum(s["calls"] * s["frames_per_call"] for s in m["stages"])
        assert (m["forward_calls"], m["forward_views"]) == (9, 25)
    b = p["budget"]
    expect((b["total_planned_forward_calls"], b["total_planned_forward_views"], b["unallocated_views"]), (22, 62, 2), "budget totals")
    b["total_planned_forward_calls"] = sum(m["forward_calls"] for m in models)
    b["total_planned_forward_views"] = sum(m["forward_views"] for m in models)
    assert (b["total_planned_forward_calls"], b["total_planned_forward_views"]) == (18, 50)
    b["unallocated_views"] = b["reserve_before_model_import_views"] - b["total_planned_forward_views"]   # 64 - 50 = 14
    b["view_accounting"] = {
        "status": "BASIS_DECIDED_NUMBERS_PENDING",
        "basis": "forward_views",
        "charge_per_complete_run": b["total_planned_forward_views"],
        "decided_by_user": USER_DECISION_3,
        "numbers_pending": ("the cumulative view cap and any change to reserve_before_model_import_views (64, the r1 per-job convention) "
                            "are the user's to state; unallocated_views is the headroom under that per-job convention only. Nothing here "
                            "is a quota approval. The ledger must not be touched before the user states the numbers"),
        "downstream_consequence": ("da3_worker.REGISTERED_CALIBRATION_VIEWS (currently 18, shared by the worker and the controlled CLI) must "
                                   "become the registered charge (50), ideally derived from this bound proposal rather than a literal; "
                                   "otherwise the worker refuses a run charged at 50 (refused_no_calibration). Separate card, after the "
                                   "final SHA is registered"),
    }

    expect(b["cumulative_wall_seconds_max"], 1200, "budget.cumulative_wall_seconds_max")
    b["cumulative_wall_seconds_max"] = None
    b["wall_accounting"] = {
        "status": "OPEN_pending_user_decision",
        "r1_cap_s": 1200,
        "ledger_reserved_s": 1170,
        "ledger_note": "2026-10-27 the failed V9.T35 run (407dae53dfe943c19f48e60b02830b21) reserved 60 s although it ran 7 s",
        "next_run_minimum_cap_s": 1230,
        "note": ("The r1 cap of 1200 s is unsatisfiable for a further run (1170 s already reserved, a run needs at least ~60 s). "
                 "cumulative_wall_seconds_max is deliberately null until the user states the quota; a consumer that reads null must fail loudly."),
    }

    # E7 执行前提
    pre = p["execution_prerequisites"]
    expect(pre[3], "known-K adapter accepts frozen K and records exact preprocessing and source SHA, different-author CPU review before execution",
           "execution_prerequisites[3]")
    pre[3] = ("teacher adapter records exact preprocessing (process_res=280), source SHA and the predicted intrinsics; supplies no K and no "
              "extrinsics; calibration runner reviewed by a different author (ainerzero.V9.T37 / T38) and bound by SHA")
    expect(pre[1], "T29 independent math review and lead immutable SHA registration", "execution_prerequisites[1]")
    pre[1] = "T39 independent math review of r2 (different author) and lead immutable SHA registration of the final r2 SHA"
    pre.append("da3_calibration_runner.py --preflight-only exits 0 against the real teacher (zero model, zero ledger) BEFORE any central "
               "reservation of views or wall time; the central CLI reserves before the worker starts")
    pre.append("user states the view-accounting basis and approves the specific view/wall quota numbers for the run")

    # E8 禁止宣称
    cf = p["claims_forbidden"]
    expect("blind intrinsic recovery" in cf, True, "claims_forbidden")
    cf.append("any statement that the teacher was conditioned on ground-truth or known intrinsics")

    # E9 修订记录
    p["amendment"] = {
        "from": {"protocol_id": "codex-da3-known-k-anchored-diagnostic-20261026-r1", "proposal_sha256": r1_sha},
        "approved_by_user": USER_APPROVAL,
        "option": "A",
        "reason": ("r1 requires known-K conditioning without extrinsics and an intrinsics-adverse control that must turn red. "
                   "This DA3 build ignores intrinsics unless extrinsics are supplied."),
        "evidence": {
            "da3_forward_gate": {
                "file": "envs/teachers/t6/Depth-Anything-3/src/depth_anything_3/model/da3.py",
                "line": line_of(DA3_SRC / "model/da3.py", "if extrinsics is not None:"),
                "sha256": sha_file(DA3_SRC / "model/da3.py"),
                "text": "if extrinsics is not None: cam_token = self.cam_enc(extrinsics, intrinsics, x.shape[-2:]) else: cam_token = None",
            },
            "api_early_return": {
                "file": "envs/teachers/t6/Depth-Anything-3/src/depth_anything_3/api.py",
                "line": line_of(DA3_SRC / "api.py", "if extrinsics is None:"),
                "sha256": sha_file(DA3_SRC / "api.py"),
                "text": "_align_to_input_extrinsics_intrinsics returns the prediction unchanged when extrinsics is None",
            },
            "pipeline_has_no_k_parameter": "envs/teachers/t6/pipeline.py process_keyframes(images, timestamps_s, world_key, partition, output_dir, process_res)",
        },
        "changes": ["E1 identity/supersedes/author/review_task", "E2 profile.known_intrinsics=false + intrinsics_policy",
                    "E3 raw_metrics last entry", "E4 numerical_parity.reference text", "E5 negative_controls: remove intrinsics, add removed_controls",
                    "E6 budget: drop intrinsics_adverse stage (and, by E15, half_parity)",
                    "E7 execution_prerequisites[1] and [3] replaced, two appended", "E8 claims_forbidden appended", "E9 this block", "E10 open_items",
                    "E11 (post-T39) budget.cumulative_wall_seconds_max null + wall_accounting", "E12 (post-T39) numerical_parity.known_risks",
                    "E13 (post-T39) negative_controls.frame_order_adverse_meaning", "E14 (post-T39) profile K-block wording",
                    "E15 (2026-10-28, user option A) remove half_parity stage: 9 calls/25 views per variant, 18/50 total; "
                    "numerical_parity.retired_stages added, known_risks reduced to the argmin risk; mps_float16 tolerance key kept unchanged and unused",
                    "E16 (2026-10-28, user: forward views, 50 per run; T46 required changes) budget.view_accounting basis decided, numbers pending; "
                    "retired_stages.reason/not_replaced corrected; open_items updated"],
        "unchanged_by_construction": ["alignment", "residual_vector.order/depth_component", "estimation", "numerical_parity tolerances/fields/rule",
                                      "negative_controls score/required_red/frames/boundary_rejection/unrelated_error", "split",
                                      "budget wall/RSS/resident-model limits", "failure_policy", "inputs and their SHAs"],
    }
    p["open_items"] = [
        "specific view and wall quota numbers for the next run: user approval pending (basis decided: forward views, 50 per complete run; cumulative reserved wall already 1170/1200)",
        "code follow-up after registration: da3_worker.REGISTERED_CALIBRATION_VIEWS 18 -> the registered charge 50 (ideally derived from the bound proposal), else the worker refuses a run charged at 50",
        "independent review: T39 reviewed r2 before E15; V9.T46 reviewed the E15 delta (accept_with_changes, applied in E16); a different-author confirmation of E16 and of the final numbers is still needed before the lead's immutable SHA registration of the final r2 SHA",
        "runner: ainerzero.V9.T40 (reviewed by T41) already reads this r2 through --proposal; its default PROPOSAL_PATH still points at r1 and is switched only after registration; ainerzero.V9.T42 follow-ups (pre-consume rejection of non-calibration views) pending",
    ]
    p["amendment"]["approved_by_user_third"] = {**USER_DECISION_3, "decisions": [
        "view accounting basis = forward views, 50 per complete run", "specific numbers: still to be stated by the user",
        "do not touch the ledger until then"]}
    p["amendment"]["approved_by_user_second"] = {
        **USER_APPROVAL_2, "option": "A",
        "decisions": ["remove half_parity (E15)", "keep cpu_parity rule unchanged (known_risks discloses the structural argmin risk)",
                      "view/wall quota basis and numbers: still to be stated by the user"],
    }
    p["amendment"]["previous_revisions"] = [
        {"sha256": "0e15033a8b55c978f3f97318e5d1978e54b406afe8d28120aebd40a8e0db9db1", "note": "draft reviewed by ainerzero.V9.T39",
         "kept_at": "reports/V9-T28/r2/reviewed-0e15033a/"},
        {"sha256": "76f4c9fbbf8b0889736904c8408dec11f62c2b9c7a3d60a2210c969ef2a922b4", "note": "after applying T39; before E15",
         "kept_at": "reports/V9-T28/r2/pre-half-parity-removal-76f4c9fb/"},
        {"sha256": "86f5ece6d5127fedbce79015a4fbc0b7f83fa9001b61058b6566141e7ed8608a", "note": "after E15; reviewed by V9.T46 (accept_with_changes); before E16",
         "kept_at": "reports/V9-T28/r2/pre-E16-86f5ece6/"},
    ]
    p["amendment"]["review_history"] = [{
        "reviewed_sha256": "0e15033a8b55c978f3f97318e5d1978e54b406afe8d28120aebd40a8e0db9db1",
        "review_task": "ainerzero.V9.T39", "reviewer": "deepseek-v41f-t3k9", "verdict": "accept_with_changes",
        "applied": ["review_task -> T39", "execution_prerequisites[1] T29 -> T39", "budget.cumulative_wall_seconds_max -> null + wall_accounting OPEN",
                    "descriptive K block compares fx/fy only; principal point excluded (hard-coded W/2,H/2)",
                    "profile.assumption no longer claims a model-estimated-intrinsics conditioning",
                    "numerical_parity.known_risks (disclosure only, no tolerance changed)",
                    "negative_controls.frame_order_adverse_meaning (association reversal, not temporal reasoning)"],
        "reviewer_says_new_math_review_needed": False,
    }]
    p["amendment"]["review_history"].append({
        "reviewed_sha256": "86f5ece6d5127fedbce79015a4fbc0b7f83fa9001b61058b6566141e7ed8608a",
        "review_task": "ainerzero.V9.T46", "reviewer": "deepseek-q7m2", "verdict": "accept_with_changes",
        "applied": ["PROTOCOL.md: 'before any run' -> 'before any run that produced calibration results'",
                    "PROTOCOL.md: unclear authorization sentence rewritten",
                    "retired_stages.reason: the MPS outcome is marked as the lead's report; the CPU reproduction is credited",
                    "open_items: REGISTERED_CALIBRATION_VIEWS downstream consequence",
                    "AMENDMENT.md: reviewed-0e15033a/ keeps deliverables only; the three scripts reviewed by T39 were not retained"],
        "not_applied_as_written": [{"item": "PROTOCOL.md: autocast on MPS is a no-op in torch 2.3.1",
                                    "why": ("checked in envs/teachers/.venv-t6, the real teacher runtime (torch 2.14.1): autocast(device_type='mps') "
                                            "constructs and is enabled; the claim holds only for .venv (torch 2.3.1), which is not the teacher's "
                                            "environment. Replaced by the verified statement about model/da3.py:139")}],
        "reviewer_says_new_math_review_needed": False,
    })
    return p


def structured_diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            sub = f"{path}/{k}"
            if k not in a:
                out.append({"path": sub, "r1": "<absent>", "r2": b[k]})
            elif k not in b:
                out.append({"path": sub, "r1": a[k], "r2": "<absent>"})
            else:
                out += structured_diff(a[k], b[k], sub)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += structured_diff(x, y, f"{path}[{i}]")
    elif a != b:
        out.append({"path": path, "r1": a, "r2": b})
    return out


def main():
    r1_path = T28 / "proposal.json"
    r1_sha = sha_file(r1_path)
    side = (T28 / "proposal.sha256").read_text().split()[0]
    assert r1_sha == side == "af3131a51bf93ff12b43c08b4ca564124c1b1542cf9f9e196316cfa6e391cb4a", "r1 proposal does not match its registered SHA"
    p1 = json.loads(r1_path.read_text())
    p2 = amend(p1, r1_sha)
    (HERE / "proposal.json").write_bytes(canon(p2) + b"\n")
    r2_sha = sha_file(HERE / "proposal.json")
    (HERE / "proposal.sha256").write_text(f"{r2_sha}  proposal.json\n")
    diff = structured_diff(p1, p2)
    (HERE / "diff_r1_r2.json").write_text(json.dumps({"r1_sha256": r1_sha, "r2_sha256": r2_sha, "changed_paths": diff}, ensure_ascii=False, indent=1))
    print(json.dumps({"r1_sha256": r1_sha, "r2_sha256": r2_sha, "changed_paths": len(diff),
                      "forward_calls": p2["budget"]["total_planned_forward_calls"], "forward_views": p2["budget"]["total_planned_forward_views"],
                      "execution_permitted": p2["execution_permitted"], "status": p2["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
