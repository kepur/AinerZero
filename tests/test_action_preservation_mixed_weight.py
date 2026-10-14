"""M2n-M2 (A3/A4) tests: E24 mixed batch with the history half's CE+KL scaled by lambda_h=0.25.

CPU only (no MLX). Covers the isolated condition/protocol, the registered objective
0.75*(CE_s+KL_s)+0.0625*(CE_h+KL_h) with the 16-row denominator, the gradient-share
telemetry, worker wiring/exclusivity, and source-level mutation tests: each registered
mutant (no scaling, single-half scaling, renormalization, double scaling) must be caught.
"""

import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ainerzero.learning import action_preservation as ap
from ainerzero.learning import action_preservation_closure as apc
from ainerzero.runtime import memory_worker as mw

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "src" / "ainerzero" / "runtime" / "memory_worker.py"
APC = ROOT / "src" / "ainerzero" / "learning" / "action_preservation_closure.py"
E24_MIXED_CONDITION_SHA256 = "dd02c4fe58059d5c505705e35afa97042bbde2af3923239ca7b7caa6f470a4f2"


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _dict_map(fn, *trees):
    return {k: fn(*(t[k] for t in trees)) for k in trees[0]}


def check_objective(module):
    """The registered objective; raises AssertionError on any deviation."""
    weights, denom = module.mixed_half_weights(12, 4, 0.25)
    rng = np.random.default_rng(7)
    g = {h: {"w": rng.normal(size=(3, 2)), "b": rng.normal(size=4)} for h in ("single_edge", "history")}
    got = module.combine_mixed_halves(g, weights, denom, _dict_map)
    for k in ("w", "b"):
        want = 0.75 * g["single_edge"][k] + 0.0625 * g["history"][k]
        assert np.allclose(got[k], want, rtol=0, atol=1e-12), k
    ce = {"single_edge": 1.3, "history": 2.9}
    kl = {"single_edge": 0.2, "history": 0.7}
    loss = sum(weights[h] * (ce[h] + kl[h]) for h in weights) / denom
    assert loss == pytest.approx(0.75 * 1.5 + 0.0625 * 3.6, abs=1e-12)
    assert denom == 16.0
    # lambda_h = 1 reproduces the E24 12:4 row weighting exactly
    w1, d1 = module.mixed_half_weights(12, 4, 1.0)
    got1 = module.combine_mixed_halves(g, w1, d1, _dict_map)
    assert all(np.allclose(got1[k], (12 * g["single_edge"][k] + 4 * g["history"][k]) / 16) for k in got1)


def test_no_mlx_imported():
    code = ("import sys, ainerzero.runtime.memory_worker, ainerzero.learning.action_preservation_closure; "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_condition_is_isolated_and_digested():
    old = apc.mixed_condition_plan()
    new = apc.mixed_weight025_condition_plan()
    assert old["protocol"] == apc.MIXED_PROTOCOL
    assert old["condition_sha256"] == E24_MIXED_CONDITION_SHA256  # E24 condition untouched
    assert new["protocol"] == apc.WEIGHT025_PROTOCOL == "m2m_n_mixed_history_weight025_v1"
    assert new["mixed_condition_sha256"] == E24_MIXED_CONDITION_SHA256
    assert new["condition_sha256"] != old["condition_sha256"]
    body = {k: v for k, v in new.items() if k != "condition_sha256"}
    assert new["condition_sha256"] == _digest(body)
    assert new["base_plan_sha256"] == ap.FROZEN_PLAN_SHA256
    assert new["history_weight"] == 0.25 and new["renormalize_after_scaling"] is False
    assert new["design_registration_sha256"] == apc.A3_DESIGN_REGISTRATION_SHA256
    changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
    assert changed == {"protocol", "single_factor", "normalization", "condition_sha256",
                       "mixed_condition_sha256", "mixed_protocol", "history_weight",
                       "renormalize_after_scaling", "design_registration_sha256", "start"}
    for key in ("batch", "units", "seconds", "seeds", "windows", "sampler_geometry",
                "history_permutation", "keep_branch"):
        assert new.get(key) == old.get(key), key


def test_worker_plan_differs_only_in_the_registered_factor():
    old = mw.action_preservation_mixed_memory_plan()
    new = mw.action_preservation_mixed_weight025_memory_plan()
    changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
    assert changed == {"protocol", "history_weight", "renormalize_after_scaling",
                       "action_preservation_condition"}
    assert "history_weight" not in old  # E24 plan stays byte-identical
    assert new["action_preservation_condition"] == apc.mixed_weight025_condition_plan()
    assert (new["single_edge_rows"], new["history_rows"], new["updates"]) == (12, 4, 200)
    assert new["training_model_units_per_update"] == 152
    assert new["expected_total_model_units"] == 202_304
    assert new["total_reserved_seconds_if_complete"] == 1_740
    assert (new["supervised_deadline_seconds"], new["supervisor_deadline_seconds"]) == (1_760, 1_780)
    assert new["seeds"] == old["seeds"] and new["seeds"]["mixed_history_augmentation"] == 2407
    assert new["keep_lambda"] == 1.0
    assert new["first_update_keep_loss_max"] == old["first_update_keep_loss_max"]
    assert new["resource_seconds"] == old["resource_seconds"]


def test_design_registration_matches_a3_file_bytes():
    path = ROOT / "artifacts/reports/relay-codex-20261013/A3-registration.json"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == apc.A3_DESIGN_REGISTRATION_SHA256
    assert apc.mixed_weight025_condition_plan()["design_registration_sha256"] == actual


def test_registered_objective():
    check_objective(apc)


def test_weights_validation():
    assert apc.mixed_half_weights(12, 4, 0.25) == ({"single_edge": 12.0, "history": 1.0}, 16.0)
    for bad in (0.0, -0.25, 1.5):
        with pytest.raises(ValueError):
            apc.mixed_half_weights(12, 4, bad)
    with pytest.raises(ValueError):
        apc.combine_mixed_halves({"single_edge": {}}, {"single_edge": 1.0, "history": 1.0}, 16.0, _dict_map)


def test_gradient_share_telemetry():
    rng = np.random.default_rng(3)
    halves = {h: {"a": rng.normal(size=5), "b": rng.normal(size=(2, 2))} for h in ("single_edge", "history")}
    rows = {"single_edge": 12.0, "history": 4.0}
    weights, _ = apc.mixed_half_weights(12, 4, 0.25)
    out = apc.mixed_gradient_shares(halves, rows, weights)
    for label in ("before_scaling", "after_scaling"):
        assert sum(v["projection_share"] for v in out[label].values()) == pytest.approx(1.0)
        assert sum(v["norm_share"] for v in out[label].values()) == pytest.approx(1.0)
    before = out["before_scaling"]["history"]["contribution_l2"]
    after = out["after_scaling"]["history"]["contribution_l2"]
    assert after == pytest.approx(0.25 * before)
    assert out["after_scaling"]["single_edge"]["contribution_l2"] == pytest.approx(
        out["before_scaling"]["single_edge"]["contribution_l2"])
    assert out["after_scaling"]["history"]["norm_share"] < out["before_scaling"]["history"]["norm_share"]


MUTANTS = {
    "no_scaling": ('"history": float(history_rows) * float(history_weight)}',
                   '"history": float(history_rows)}'),
    "scale_single_half": ('"single_edge": float(single_rows) * MIXED_KEEP_WEIGHT,\n'
                          '               "history": float(history_rows) * float(history_weight)}',
                          '"single_edge": float(single_rows) * float(history_weight),\n'
                          '               "history": float(history_rows)}'),
    "renormalize_to_weight_sum": ("return weights, float(single_rows + history_rows)",
                                  "return weights, float(sum(weights.values()))"),
    "double_scaling": ('"history": float(history_rows) * float(history_weight)}',
                       '"history": float(history_rows) * float(history_weight) ** 2}'),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_mutants_are_caught(name, tmp_path):
    old, new = MUTANTS[name]
    src = APC.read_text()
    assert src.count(old) == 1, name
    path = tmp_path / f"apc_{name}.py"
    path.write_text(src.replace(old, new))
    spec = importlib.util.spec_from_file_location(f"apc_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(AssertionError):
        check_objective(module)


def _mixed_branch_source():
    src = WORKER.read_text()
    start = src.index("            if action_preservation_mixed:\n                # Two halves")
    end = src.index("            else:\n                for part in range(parts_count):", start)
    return src[start:end]


def test_worker_uses_the_registered_combination_once():
    body = _mixed_branch_source()
    assert body.count("apc.mixed_half_weights(") == 1
    assert body.count("apc.combine_mixed_halves(half_grads, weights, total_weight, tree_map)") == 1
    assert 'plan["history_weight"] if action_preservation_mixed_weight025 else 1.0' in body
    assert "history_weight" not in body.split("apc.combine_mixed_halves(")[1].split("total = sum(")[0]
    # no extra scaling of gradients by the weight anywhere after combination (mask/clip/AdamW)
    tail = WORKER.read_text().split("apc.combine_mixed_halves(")[1]
    tail = tail[: tail.index("optimizer.update(model, gradients)")]
    assert "history_weight" not in tail.split("total = sum(")[1].split("raw_front_gradient_l2 =")[1]
    assert "gradient_shares" in body and "apc.mixed_gradient_shares(" in body
    # E24 per-half normalization and front-row invariant still precede combination
    assert body.index("mean_grads = tree_map(lambda g: g / h_targets, h_grads)") < body.index(
        "apc.combine_mixed_halves(")
    assert 'if name == "single_edge" and half_front > 1e-8:' in body


def test_worker_mutant_dropping_the_weight_is_caught():
    body = _mixed_branch_source()
    mutant = body.replace('plan["history_weight"] if action_preservation_mixed_weight025 else 1.0', "1.0")
    assert mutant != body
    with pytest.raises(AssertionError):
        assert 'plan["history_weight"] if action_preservation_mixed_weight025 else 1.0' in mutant


def test_run_memory_flag_exclusivity():
    for other in ("action_preservation_mixed", "action_preservation_distill",
                  "action_preservation_history", "action_preservation_lambda10"):
        with pytest.raises(ValueError, match="choose one"):
            mw.run_memory("c", "d", "k", "o", "db", "e", action_preservation_mixed_weight025=True,
                          m2mc_report_path="x", **{other: True})


def test_worker_cli_flag_exclusive(monkeypatch):
    required = ["--config", "c", "--dataset", "d", "--checkpoint", "k", "--output-dir", "o",
                "--control-db", "db", "--experiment-id", "e"]
    monkeypatch.setattr(sys, "argv", ["w", *required, "--action-preservation-mixed-weight025",
                                      "--action-preservation-mixed"])
    with pytest.raises(SystemExit, match="lambda_h mixed condition is exclusive"):
        mw.main()


def test_phase_and_plan_dispatch_are_wired():
    tree = ast.parse(WORKER.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    names = {a.arg for a in fn.args.kwonlyargs} | {a.arg for a in fn.args.args}
    assert "action_preservation_mixed_weight025" in names
    raw = ast.get_source_segment(WORKER.read_text(), fn)
    assert "action_preservation_mixed_weight025_memory_plan()\n        if action_preservation_mixed_weight025" in raw
    assert '"action_preserved_mixed_weight025_memory_fit"\n        if action_preservation_mixed_weight025' in raw
