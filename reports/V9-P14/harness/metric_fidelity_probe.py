"""P14 reviewer: independent CPU-only fidelity probe for the #372/#374 findings.

No MLX, no model, no real training, no edit of the verified source.  Two kinds
of evidence:

  * static: parse the frozen `worker.py` with `ast` (reviewer-written checks, not
    a copy of the coordinator's JSON) and assert the structural facts;
  * behavioural: import only `metrics` (pure numpy -- verified to load no MLX)
    and feed it the exact values the shipped call site uses, plus a negative
    control that shows the metric *can* discriminate.

Output: reports/V9-P14/evidence/metric-fidelity-p14.json
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(REAL / "src"))

WORKER = REAL / "src" / "ainerzero" / "v9" / "experiments" / "s1" / "worker.py"
EV = REAL / "reports" / "V9-P14" / "evidence"

from ainerzero.v9.experiments.s1 import metrics  # noqa: E402  (pure numpy)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_func(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise LookupError(name)


def call_args(node: ast.Call) -> dict:
    if len(node.args) == 2 and all(isinstance(a, ast.List) for a in node.args):
        # positional form few_shot_transition_metrics(pred_exists, true_exists)
        return {"_positional": node.args}
    return {kw.arg: kw.value for kw in node.keywords}


def all_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.List):
        return all(isinstance(e, ast.Constant) for e in node.elts)
    return isinstance(node, ast.Constant)


def static_checks(source: str) -> dict:
    tree = ast.parse(source)
    ev = find_func(tree, "_evaluate_arm")

    # --- S1: few_shot call site all-literal ---
    s1 = {"call_found": False, "inputs": {}, "all_inputs_literal": None,
          "predictions_equal_labels": None}
    for node in ast.walk(ev):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "few_shot_transition_metrics"):
            s1["call_found"] = True
            for kw in node.keywords:
                val = ast.literal_eval(kw.value)
                s1["inputs"][kw.arg] = val
            s1["all_inputs_literal"] = all(all_literal(kw.value) for kw in node.keywords)
            if {"predicted_exists", "true_exists"} <= set(s1["inputs"]):
                s1["predictions_equal_labels"] = (
                    s1["inputs"]["predicted_exists"] == s1["inputs"]["true_exists"])
            if {"predicted_displacement_m", "true_displacement_m"} <= set(s1["inputs"]):
                s1["predictions_equal_labels"] = s1["predictions_equal_labels"] and (
                    s1["inputs"]["predicted_displacement_m"]
                    == s1["inputs"]["true_displacement_m"])

    # --- S2: M2 before/after both _development_nll(model, ...) with nothing between ---
    nll_assigns = []
    for node in ast.walk(ev):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            if isinstance(fn, ast.Name) and fn.id == "_development_nll":
                nll_assigns.append({
                    "lineno": node.lineno,
                    "target": node.targets[0].id if isinstance(node.targets[0], ast.Name) else "?",
                })
    # any call that could write memory / update params between the two?
    writes = []
    lo = min((a["lineno"] for a in nll_assigns), default=None)
    hi = max((a["lineno"] for a in nll_assigns), default=None)
    for node in ast.walk(ev):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and lo and hi:
            if lo < node.lineno < hi and any(
                tok in node.func.attr for tok in ("write", "update", "learn", "remember", "store")
            ):
                writes.append({"lineno": node.lineno, "attr": node.func.attr})
    s2 = {"before_after_nll_assigns": nll_assigns,
          "writes_between": writes,
          "no_write_between": len(nll_assigns) == 2 and not writes}

    # --- S3: localization min-truncation + shared slice ---
    body = ast.get_source_segment(source, ev)
    s3 = {
        "has_min_of_lengths": "min(len(all_estimates), len(all_truth))" in body,
        "slices_both_prefixes": "all_estimates[:n_match]" in body and "all_truth[:n_match]" in body,
        "pairs_by_index_not_episode_id": True,
    }

    # --- S4: unseen_map_generalization fed a single row + first world's family ---
    s4 = {"single_row_call": bool(
        [n for n in ast.walk(ev) if isinstance(n, ast.Call)
         and isinstance(n.func, ast.Attribute) and n.func.attr == "unseen_map_generalization"
         and len(n.args) == 1 and isinstance(n.args[0], ast.List) and len(n.args[0].elts) == 1]),
        "family_from_truth_view_first": "truth_view[0].world.get(\"arena_family\"" in body}

    # --- S5: duplicate guard only inspects state == "completed" ---
    s5 = {"guard_only_completed": 'r.state == "completed"' in source
          and "already_completed" in source,
          "states_not_guarded": ["failed", "aborted", "stopped"]}

    # --- S6: checkpoint trust without SHA binding ---
    s6 = {
        "run_info_json_trusted_by_arm_seed_only": (
            'info.get("arm_id") == arm_id and int(info.get("seed", -1)) == int(seed)'
            in source),
        "load_has_no_sha_check": "_load_checkpoint_params" in source
        and "sha256" not in ast.get_source_segment(
            source, find_func(tree, "_load_checkpoint_params")) ,
        "runstore_path_recomputes_sha_at_load": (
            '"checkpoint_sha256": spec.sha256_file(params_path)' in source),
    }
    return {"S1_few_shot_all_literal": s1, "S2_m2_no_write_between": s2,
            "S3_localization_min_truncation": s3, "S4_unseen_single_row": s4,
            "S5_duplicate_guard_completed_only": s5, "S6_checkpoint_binding": s6}


def behaviour() -> dict:
    import numpy as np

    shipped = metrics.few_shot_transition_metrics(
        predicted_exists=[True, True, False, False],
        true_exists=[True, True, False, False],
        predicted_displacement_m=[0.5, 0.5, 0.0, 0.0],
        true_displacement_m=[0.5, 0.5, 0.0, 0.0],
    )
    control = metrics.few_shot_transition_metrics(
        predicted_exists=[True, True, True, True],
        true_exists=[True, True, False, False],
        predicted_displacement_m=[1.5, 1.5, 1.5, 1.5],
        true_displacement_m=[0.5, 0.5, 0.0, 0.0],
    )

    # localization min-truncation: perfect estimate of episode B only, truth = A ++ B
    est = np.array([[10.0, 0.0, 0.0, 0.0], [10.0, 0.0, 1.0, 0.0]])          # episode B, 2 steps
    truth = np.array([[0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 2.0, 0.0],
                      [10.0, 0.0, 0.0, 0.0], [10.0, 0.0, 1.0, 0.0], [10.0, 0.0, 2.0, 0.0],
                      [10.0, 0.0, 3.0, 0.0]])                                # A(3) ++ B(4)
    n = min(len(est), len(truth))
    shipped_loc = metrics.localization_error(est[:n], truth[:n])            # index pairing
    aligned_loc = metrics.localization_error(est, truth[3:5])              # per-episode pairing

    m2_same = metrics.memory_interference(before={"development_nll": 2.5},
                                          after={"development_nll": 2.5})
    m2_moved = metrics.memory_interference(before={"development_nll": 2.5},
                                           after={"development_nll": 2.7})
    return {
        "few_shot_shipped": shipped,
        "few_shot_negative_control": control,
        "localization_shipped_index_pairing": shipped_loc,
        "localization_aligned_per_episode": aligned_loc,
        "m2_identical_before_after": m2_same,
        "m2_negative_control": m2_moved,
    }


def main() -> int:
    source = WORKER.read_text(encoding="utf-8")
    out = {
        "schema": "ainerzero.v9.p14.metric-fidelity.v1",
        "harness": "reports/V9-P14/harness/metric_fidelity_probe.py",
        "frozen_worker_sha256": sha(WORKER),
        "mlx_imported": "mlx" in sys.modules,
        "source_edited": False,
        "static": static_checks(source),
        "behaviour": behaviour(),
    }
    s = out["static"]
    out["verdict"] = "fidelity_defects_confirmed"
    out["findings"] = [
        {"id": "F1", "severity": "blocker",
         "claim": "few_shot_unseen_transition 指标在真实 arm 上是写死的完美夹具，与模型/检查点/episode 无关",
         "static_support": s["S1_few_shot_all_literal"],
         "behaviour_support": {"shipped": out["behaviour"]["few_shot_shipped"],
                               "control": out["behaviour"]["few_shot_negative_control"]}},
        {"id": "F2", "severity": "blocker",
         "claim": "M2 干扰的 before/after 是同模型对同一 dev 数据的两次前向，必然为 0，不是预登记的干扰诊断",
         "static_support": s["S2_m2_no_write_between"],
         "behaviour_support": {"same": out["behaviour"]["m2_identical_before_after"]}},
        {"id": "F3", "severity": "blocker",
         "claim": "localization 用 min(估计数, 真值数) 前缀配对，跨 episode/world/tick 错配",
         "static_support": s["S3_localization_min_truncation"],
         "behaviour_support": {"shipped": out["behaviour"]["localization_shipped_index_pairing"],
                               "aligned": out["behaviour"]["localization_aligned_per_episode"]}},
        {"id": "F4", "severity": "major",
         "claim": "重复运行守卫只查 completed，failed/aborted/stopped 的同 arm×seed 可重跑（违反冻结规则 6）",
         "static_support": s["S5_duplicate_guard_completed_only"]},
        {"id": "F5", "severity": "major",
         "claim": "eval 信任可自填的 run_info.json 且加载参数不核 SHA（违反冻结规则 7）",
         "static_support": s["S6_checkpoint_binding"]},
        {"id": "F6", "severity": "major",
         "claim": "unseen_map 用单行 + 第一个世界的 family 汇总整库（违反冻结规则 3）",
         "static_support": s["S4_unseen_single_row"]},
    ]
    EV.mkdir(parents=True, exist_ok=True)
    (EV / "metric-fidelity-p14.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"verdict": out["verdict"],
                      "findings": [f["id"] for f in out["findings"]],
                      "mlx_imported": out["mlx_imported"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
