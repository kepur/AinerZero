"""C07 tests: the registered keep-lambda 1.0 -> 10.0 single-factor condition.

CPU only: no MLX, no run, no writes outside tmp. Covers the single-factor claim,
bitwise equivalence of the lambda=1 path, the lambda=10 arithmetic, rejection of
invalid lambdas, and the CLI/worker wiring.
"""

import ast
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ainerzero import cli
from ainerzero.learning import action_preservation as ap
from ainerzero.learning import action_preservation_closure as apc
from ainerzero.runtime import memory_worker as mw

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "src" / "ainerzero" / "runtime" / "memory_worker.py"
REQUIRED = ["--dataset", "d", "--checkpoint", "c", "--comparison-report", "r", "--m2l-report", "m",
            "--m2l-checkpoint", "k", "--m2mc-report", "x", "--experiment-id", "e"]


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _tree(seed=0, width=64):
    rng = np.random.default_rng(seed)
    return {
        "Wx": rng.standard_normal((768, width)),
        "Wh": rng.standard_normal((768, width)),
        "b": rng.standard_normal(768),
        "bhn": rng.standard_normal(768),
    }


def _keep_rows(seed=1, width=64):
    rng = np.random.default_rng(seed)
    return [{k: rng.standard_normal(v.shape) for k, v in _tree(seed=0, width=width).items()}
            for _ in range(ap.ROWS_PER_UPDATE)]


def test_no_mlx_imported():
    code = ("import sys, ainerzero.runtime.memory_worker, "
            "ainerzero.learning.action_preservation_closure; "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    import subprocess
    subprocess.run([sys.executable, "-c", code], check=True)


# ------------------------------------------------------------ single factor


def test_c07_is_the_registered_single_factor_condition():
    base = mw.action_preservation_memory_plan()
    c07 = mw.action_preservation_lambda10_memory_plan()
    assert c07["protocol"] == apc.C07_PROTOCOL == "m2m_d_lambda10_action_preservation_v1"
    assert c07["keep_lambda"] == apc.LAMBDA_KEEP_V2 == 10.0
    assert base["keep_lambda"] == ap.LAMBDA_KEEP == 1.0
    # everything that defines cost, data, seeds and gates is identical
    for key in ("updates", "learning_rate", "batch_size", "micro_batch_size", "burn_in",
                "sequence_steps", "expected_total_model_units",
                "total_reserved_seconds_if_complete", "supervised_deadline_seconds",
                "supervisor_deadline_seconds", "student_model_units_per_update",
                "first_update_keep_loss_max", "seeds", "resource_seconds", "local_checks",
                "paired_evaluation", "relabel_evaluation", "screen", "local_screen",
                "regression", "transfer_levels", "trainable_parameter_count",
                "frozen_parameter_count"):
        assert c07[key] == base[key], key
    assert c07["expected_total_model_units"] == 208_546
    assert c07["total_reserved_seconds_if_complete"] == 1_610
    assert (c07["supervised_deadline_seconds"], c07["supervisor_deadline_seconds"]) == (1_660, 1_710)
    # the frozen base plan is carried untouched, with the modified copy beside it
    assert ap.verify_frozen_plan(c07["action_preservation"]) == ap.FROZEN_PLAN_SHA256
    assert c07["action_preservation"]["keep_branch"]["lambda"] == 1.0
    condition = c07["action_preservation_condition"]
    assert condition["keep_branch"]["lambda"] == 10.0
    assert condition["base_plan_sha256"] == ap.FROZEN_PLAN_SHA256
    assert condition["protocol"] == apc.C07_PROTOCOL and condition["protocol"] != ap.PROTOCOL
    body = {k: v for k, v in condition.items() if k != "condition_sha256"}
    assert condition["condition_sha256"] == _digest(body)
    # the base plan itself really changed for this condition, and only in lambda/protocol
    modified = {k: v for k, v in condition.items() if k not in ("base_plan_sha256", "condition_sha256",
                                                               "single_factor")}
    original = ap.action_preservation_plan()
    assert modified != original
    diffs = {k for k in set(modified) | set(original) if modified.get(k) != original.get(k)}
    assert diffs == {"protocol", "keep_branch", "base_protocol"} or diffs == {"protocol", "keep_branch"}


# ------------------------------------------------- lambda arithmetic / safety


def test_v2_with_lambda_one_is_bitwise_identical_to_the_frozen_reference():
    for seed in range(5):
        memory, keep = _tree(seed=seed), _keep_rows(seed=seed + 10)
        reference = ap.combine_branch_gradients(memory, 2.5, keep)
        candidate = apc.combine_branch_gradients_v2(memory, 2.5, keep, lam=ap.LAMBDA_KEEP)
        assert set(reference) == set(candidate)
        for key in reference:
            assert np.array_equal(reference[key], candidate[key]), key


def test_v2_lambda_ten_scales_only_the_keep_branch():
    memory, keep = _tree(seed=7), _keep_rows(seed=8)
    out = apc.combine_branch_gradients_v2(memory, 4.0, keep, lam=10.0)
    for key in memory:
        expected = (np.asarray(memory[key], dtype=np.float64) / 4.0
                    + 10.0 * sum(np.asarray(row[key], dtype=np.float64) for row in keep) / 16)
        assert np.allclose(out[key], expected, rtol=0, atol=0)
    one = apc.combine_branch_gradients_v2(memory, 4.0, keep, lam=1.0)
    ten = apc.combine_branch_gradients_v2(memory, 4.0, keep, lam=10.0)
    for key in memory:
        memory_part = np.asarray(memory[key], dtype=np.float64) / 4.0
        keep_part = one[key] - memory_part
        assert np.allclose(ten[key] - memory_part, 10.0 * keep_part, rtol=0, atol=1e-12)


@pytest.mark.parametrize("bad", [0, 0.0, -1.0, float("nan"), float("inf"), -float("inf"),
                                 True, False, "10", None])
def test_invalid_lambda_rejected(bad):
    with pytest.raises(ValueError):
        apc.combine_branch_gradients_v2(_tree(), 2.0, _keep_rows(), lam=bad)


def test_v2_keeps_the_frozen_validation_semantics():
    memory, keep = _tree(), _keep_rows()
    with pytest.raises(ValueError):
        apc.combine_branch_gradients_v2(memory, 0, keep, lam=10.0)
    with pytest.raises(ValueError):
        apc.combine_branch_gradients_v2(memory, float("nan"), keep, lam=10.0)
    with pytest.raises(ValueError):
        apc.combine_branch_gradients_v2(memory, 2.0, keep[:15], lam=10.0)
    with pytest.raises(ValueError):
        apc.combine_branch_gradients_v2(memory, 2.0, [{**keep[0], "extra": np.zeros(3)}] * 16, lam=10.0)
    broken = list(keep)
    broken[3] = {**broken[3], "b": np.full(768, np.nan)}
    with pytest.raises(ValueError):
        apc.combine_branch_gradients_v2(memory, 2.0, broken, lam=10.0)


def test_training_branch_selects_the_combiner_by_registered_lambda():
    tree = ast.parse(WORKER.read_text())
    keep_update = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_keep_update")
    shared = ast.unparse(keep_update)
    # the shared keep-update helper selects the combiner by the registered lambda,
    # keeping the already-verified M2m-d path on the frozen CPU reference
    assert "combine_branch_gradients_v2" in shared
    assert "ap.combine_branch_gradients(memory_np, memory_targets, keep_trees)" in shared
    assert "if keep_lambda == ap.LAMBDA_KEEP" in shared
    assert "keep_lambda" in shared
    run_memory_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    training = ast.unparse(run_memory_node)
    assert "keep_lambda=plan[" in training          # call site passes the registered value
    # F1: the log update must NOT repeat a keyword that `keep_details` supplies
    assert "entry.update(memory_loss=total, **keep_details)" in training
    probe = ast.unparse(next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                             and n.name == "run_action_preservation_probe"))
    assert "keep_lambda=plan[" in probe


# ------------------------------------------------------------ entry wiring


def test_log_update_cannot_duplicate_a_keep_details_keyword():
    """C07 review F1: `dict.update(x=1, **{"x": 2})` raises TypeError.

    The production log update must therefore never repeat a keyword that
    `_keep_update`'s details already provide (keep_lambda in particular).
    """
    tree = ast.parse(WORKER.read_text())
    run_memory_node = next(n for n in tree.body
                           if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    keep_update_node = next(n for n in tree.body
                            if isinstance(n, ast.FunctionDef) and n.name == "_keep_update")
    detail_keys = set()
    for node in ast.walk(keep_update_node):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "details" for t in node.targets
        ) and isinstance(node.value, ast.Dict):
            detail_keys = {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    assert "keep_lambda" in detail_keys, "keep_lambda must still be logged from details"
    updates = [n for n in ast.walk(run_memory_node) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute) and n.func.attr == "update"
               and isinstance(n.func.value, ast.Name) and n.func.value.id == "entry"]
    assert updates, "no entry.update call found"
    for call in updates:
        spread = [k for k in call.keywords if k.arg is None]
        explicit = {k.arg for k in call.keywords if k.arg is not None}
        if spread:  # `**keep_details` present: no explicit key may collide with it
            assert not (explicit & detail_keys), (explicit & detail_keys)
            assert not ({"keep_lambda"} & explicit)
    # and the chosen form really is safe when the mapping carries keep_lambda
    entry = {"loss": 1.0}
    details = {"keep_lambda": 10.0, "keep_loss": 0.0, "combined_raw_front_gradient_l2": 0.0}
    entry.update(memory_loss=0.5, **details)
    assert entry["keep_lambda"] == 10.0 and entry["memory_loss"] == 0.5


def test_worker_flag_validation_and_exclusion(tmp_path):
    with pytest.raises(ValueError, match="choose one action-preservation condition"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_fit=True, m2mc_report_path=tmp_path / "x",
                      action_preservation_lambda10=True)
    with pytest.raises(ValueError, match="exactly its M2m-c report"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_lambda10=True)
    with pytest.raises(ValueError, match="no manual combination"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_lambda10=True, m2mc_report_path=tmp_path / "x",
                      local_fit=True)


def test_worker_argparse_excludes_other_protocols(monkeypatch):
    base = ["w", "--config", "c", "--dataset", "d", "--checkpoint", "k", "--output-dir", "o",
            "--control-db", "b", "--experiment-id", "e", "--action-preservation-lambda10",
            "--comparison-report", "r", "--m2l-report", "m", "--m2l-checkpoint", "mk",
            "--m2mc-report", "x"]
    for extra in (["--action-preservation-fit"], ["--action-preservation-probe"], ["--local-fit"],
                  ["--diverse-fit"], ["--relabel-fit"], ["--relabel-learning-rate", "0.003"]):
        monkeypatch.setattr(sys, "argv", [*base, *extra])
        with pytest.raises(SystemExit):
            mw.main()
    captured = {}
    monkeypatch.setattr(mw, "run_memory", lambda *a, **k: captured.update(k) or {"status": "failed"})
    monkeypatch.setattr(sys, "argv", base)
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert mw.main() == 1
    assert captured["action_preservation_lambda10"] is True
    assert captured["action_preservation_fit"] is False


def test_cli_lambda10_subcommand_has_no_scientific_params(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli, "train_pilot_command", lambda a: seen.update(vars(a)) or {"status": "completed"})
    assert cli.main(["train-action-preserved-lambda10-memory", *REQUIRED]) == 0
    assert seen["action_preserved_lambda10_training"] is True
    assert not any(k in seen for k in ("learning_rate", "keep_lambda", "lambda"))
    for flag in ("--learning-rate", "--keep-lambda"):
        with pytest.raises(SystemExit):
            cli.main(["train-action-preserved-lambda10-memory", *REQUIRED, flag, "10"])
    for i in range(0, len(REQUIRED) - 2, 2):
        with pytest.raises(SystemExit):
            cli.main(["train-action-preserved-lambda10-memory", *(REQUIRED[:i] + REQUIRED[i + 2:])])


def test_cli_lambda10_dispatch_and_timeout(monkeypatch, tmp_path):
    captured = {}

    class Done:
        returncode, stdout, stderr = 1, "", ""

    monkeypatch.setattr(cli.subprocess, "run",
                        lambda cmd, **kw: captured.update(cmd=cmd, timeout=kw["timeout"]) or Done())
    monkeypatch.setattr(cli, "project_root", lambda _: tmp_path)
    args = SimpleNamespace(
        config=ROOT / "configs" / "pilot.yaml", output_dir=tmp_path, experiment_id="e",
        dataset=tmp_path / "d", checkpoint=tmp_path / "c", comparison_report=tmp_path / "r",
        m2l_report=tmp_path / "m", m2l_checkpoint=tmp_path / "k", m2mc_report=tmp_path / "x",
        action_preserved_lambda10_training=True,
    )
    cli.train_pilot_command(args)
    assert captured["cmd"][2] == "ainerzero.runtime.memory_worker"
    assert "--action-preservation-lambda10" in captured["cmd"]
    assert "--action-preservation-fit" not in captured["cmd"]
    assert captured["timeout"] == min(1710, cli.load_pilot_config(args.config).budget.max_wall_seconds)
    parsed = {}
    monkeypatch.setattr(mw, "run_memory", lambda *a, **k: parsed.update(k) or {"status": "failed"})
    monkeypatch.setattr(sys, "argv", ["worker", *captured["cmd"][3:]])
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert mw.main() == 1
    assert parsed["action_preservation_lambda10"] is True and parsed["action_preservation_fit"] is False


def test_other_conditions_and_old_entries_are_untouched():
    # M2m-d entry still registers lambda 1.0 and its own protocol
    base = mw.action_preservation_memory_plan()
    assert base["protocol"] == ap.PROTOCOL and base["keep_lambda"] == 1.0
    assert "action_preservation_condition" not in base
    # the probe plan is unchanged by C07
    probe = mw.action_preservation_probe_plan()
    assert probe["expected_total_model_units"] == 5_025 and probe["updates"] == 3
    # pre-E13b old plans still hash to their registered values
    digests = {
        "memory": _digest(mw.memory_plan()),
        "micro": _digest(mw.micro_memory_plan()),
        "diverse": _digest(mw.diverse_memory_plan()),
        "relabel_0.001": _digest(mw.relabel_memory_plan(0.001)),
        "relabel_0.003": _digest(mw.relabel_memory_plan(0.003)),
    }
    assert digests == {
        "memory": "ec73cfdab0ffe3dec4992aba80dcc86dc8a526a1fd9c1ee4ce817ce991d7d51d",
        "micro": "2407e358866f79877da7abb4e15325bb6eff92e0c25dfe48f49dc4250396ab5d",
        "diverse": "535a726d00496bb9fb1572337a49cad8ba86c6bd1ec70fd54e111d2254dec797",
        "relabel_0.001": "45d4c0a39baaad61aff55120387f143eb9491e8e870fe126f1f604015d4658c4",
        "relabel_0.003": "249adc8596041098093cab8a124e27c11df0edd6b8e44ddc16cca71ecb4374a7",
    }
