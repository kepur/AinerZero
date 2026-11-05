"""D tests: in-batch teacher distillation (same batch / same forward / relabelled).

CPU only: no MLX, no run, no writes outside tmp. Covers the condition plan, the
cost arithmetic, the old conditions, and the static wiring of the new loss route.
"""

import ast
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ainerzero import cli
from ainerzero.learning import action_preservation as ap
from ainerzero.learning import action_preservation_closure as apc
from ainerzero.runtime import memory_worker as mw

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "src" / "ainerzero" / "runtime" / "memory_worker.py"
MLX = ROOT / "src" / "ainerzero" / "learning" / "action_preservation_mlx.py"
REQUIRED = ["--dataset", "d", "--checkpoint", "c", "--comparison-report", "r", "--m2l-report", "m",
            "--m2l-checkpoint", "k", "--m2mc-report", "x", "--experiment-id", "e"]


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _worker_tree():
    return ast.parse(WORKER.read_text())


def test_no_mlx_imported():
    code = ("import sys, ainerzero.runtime.memory_worker, "
            "ainerzero.learning.action_preservation_closure; "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    import subprocess
    subprocess.run([sys.executable, "-c", code], check=True)


# ------------------------------------------------------------- condition plan


def test_d_condition_is_loss_routing_only():
    condition = apc.d_condition_plan()
    base = ap.action_preservation_plan()
    assert condition["protocol"] == apc.D_PROTOCOL == "m2m_d1_inbatch_teacher_distillation_v1"
    assert condition["base_plan_sha256"] == ap.FROZEN_PLAN_SHA256
    assert condition["base_protocol"] == ap.PROTOCOL
    assert condition["keep_branch"]["lambda"] == 1.0          # lambda unchanged
    assert condition["keep_branch"]["rows"] == 0              # no separate keep rows
    assert condition["teacher_cache"].startswith("none")
    assert condition["units"] == {"retained": 178_304, "teacher_online": 6_400,
                                 "keep_branch": 0, "total": 184_704}
    assert condition["seconds"]["prepaid"] == 1_540
    assert condition["single_factor"] == "loss_routing_only_same_batch_same_forward"
    body = {k: v for k, v in condition.items() if k != "condition_sha256"}
    assert condition["condition_sha256"] == _digest(body)
    # the only scientific differences versus the frozen base plan are the loss route
    # and the bookkeeping that follows from it
    changed = {k for k in set(condition) | set(base) if condition.get(k) != base.get(k)}
    assert changed == {"protocol", "base_protocol", "base_plan_sha256", "single_factor", "loss",
                       "keep_branch", "teacher_cache", "units", "seconds", "condition_sha256"}


def test_d_plan_arithmetic_and_cost():
    plan = mw.action_preservation_distill_memory_plan()
    assert plan["protocol"] == apc.D_PROTOCOL
    assert (plan["updates"], plan["learning_rate"], plan["batch_size"], plan["micro_batch_size"]) == (200, 0.003, 16, 4)
    assert plan["training_model_units_per_update"] == 64 == 2 * 32
    assert plan["expected_total_model_units"] == 178_304 + 200 * 32 == 184_704
    assert plan["conditional_total_model_units"] == 184_704
    assert plan["expected_total_model_units"] == plan["action_preservation_condition"]["units"]["total"]
    assert plan["total_reserved_seconds_if_complete"] == 940 + 200 * 3 == 1_540
    assert (plan["supervised_deadline_seconds"], plan["supervisor_deadline_seconds"]) == (1_590, 1_640)
    assert plan["supervisor_deadline_seconds"] <= ap.SINGLE_RUN_LIMIT_SECONDS
    assert "teacher_cache" not in plan["resource_seconds"]
    assert "cache_protocol_checks" not in plan["resource_seconds"]
    assert set(plan["resource_seconds"]) == {
        "compatibility", "initialization", "training_update", "local_check",
        "before_memory_train", "before_memory_development", "before_action", "before_reconstruction",
        "after_memory_train", "after_memory_development", "after_action", "after_reconstruction",
        "after_paired", "after_relabel_pool", "checkpoint", "verification"}
    assert plan["keep_lambda"] == 1.0 and plan["distill"] == "in_batch_same_forward_relabelled_teacher"
    assert plan["student_model_units_per_update"] == "none_no_separate_keep_branch"
    assert ap.verify_frozen_plan(plan["action_preservation"]) == ap.FROZEN_PLAN_SHA256
    assert plan["action_preservation"]["keep_branch"]["lambda"] == 1.0


def test_other_conditions_unchanged():
    assert mw.action_preservation_memory_plan()["expected_total_model_units"] == 208_546
    c07 = mw.action_preservation_lambda10_memory_plan()
    assert c07["keep_lambda"] == 10.0 and c07["expected_total_model_units"] == 208_546
    probe = mw.action_preservation_probe_plan()
    assert probe["expected_total_model_units"] == 5_025 and probe["updates"] == 3
    digests = {name: _digest(fn()) for name, fn in {
        "memory": mw.memory_plan, "micro": mw.micro_memory_plan, "diverse": mw.diverse_memory_plan,
    }.items()}
    digests["relabel_0.001"] = _digest(mw.relabel_memory_plan(0.001))
    digests["relabel_0.003"] = _digest(mw.relabel_memory_plan(0.003))
    assert digests == {
        "memory": "ec73cfdab0ffe3dec4992aba80dcc86dc8a526a1fd9c1ee4ce817ce991d7d51d",
        "micro": "2407e358866f79877da7abb4e15325bb6eff92e0c25dfe48f49dc4250396ab5d",
        "diverse": "535a726d00496bb9fb1572337a49cad8ba86c6bd1ec70fd54e111d2254dec797",
        "relabel_0.001": "45d4c0a39baaad61aff55120387f143eb9491e8e870fe126f1f604015d4658c4",
        "relabel_0.003": "249adc8596041098093cab8a124e27c11df0edd6b8e44ddc16cca71ecb4374a7",
    }


# ----------------------------------------------------------- static wiring


def test_distill_route_uses_the_same_batch_and_forward():
    tree = _worker_tree()
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    src = ast.unparse(run_memory).replace('"', "'")
    # one objective, defined from the frozen teacher and the registered lambda
    assert "memory_distill_sequence_loss" in src
    assert "distill_teacher = teacher" in src and "distill_lambda = plan['keep_lambda']" in src
    assert "nn.value_and_grad(model, distill_objective)" in src
    # the objective is called exactly like the memory loss (same data/keys), so the
    # teacher sees the same relabelled batch in the same forward pass
    assert "(loss, metrics), grads = value_grad(" in src
    assert 'key=keys[part]' in src
    # no separate keep branch runs under this condition
    assert "if action_preservation_fit and (not action_preservation_distill):" in src
    assert "elif action_preservation_fit:\n                gradients, keep_details = keep_update" in src
    # the teacher cache stages are skipped and the frozen teacher is never in the optimizer
    assert "if action_preservation_fit and (not action_preservation_distill):" in src
    assert "raise RuntimeError('frozen M2d teacher did not load exactly')" in src
    assert "teacher.freeze()" in src
    assert "optimizer.update(model, gradients)" in src and "optimizer.update(teacher" not in src
    # first-update guard reuses the registered bound; teacher is released after training
    assert "check_first_update_keep_loss(distill_kls)" in src
    assert "del teacher, distill_teacher" in src


def test_distill_loss_module_math_and_safety():
    source = MLX.read_text()
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "memory_distill_sequence_loss")
    body = ast.unparse(fn).replace('"', "'")
    assert "memory_sequence_loss(student_recorder" in body
    assert "memory_sequence_loss(teacher_recorder" in body
    assert "mx.stop_gradient(teacher_recorder.logits[offset])" in body
    assert "memory_loss + float(lam) * kl" in body
    assert "valid[:, step] & ~starts[:, step + 1]" in body          # same mask rule
    assert "metrics['visible_targets']" in body                       # same denominator
    assert "mx.logsumexp" in body                                     # stable log-softmax
    # the recorder performs no extra model work
    recorder = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_ReadoutRecorder")
    assert "self._model.symbol_readout" in ast.unparse(recorder)


# ------------------------------------------------------------- entry wiring


def test_entry_validation_and_exclusions(tmp_path):
    with pytest.raises(ValueError, match="choose one action-preservation condition"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_distill=True, action_preservation_lambda10=True,
                      m2mc_report_path=tmp_path / "x")
    with pytest.raises(ValueError, match="choose one action-preservation condition"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_distill=True, action_preservation_fit=True,
                      m2mc_report_path=tmp_path / "x")
    with pytest.raises(ValueError, match="exactly its M2m-c report"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e", action_preservation_distill=True)
    with pytest.raises(ValueError, match="no manual combination"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_distill=True, m2mc_report_path=tmp_path / "x", local_fit=True)


def test_worker_argparse_exclusion_and_pass_through(monkeypatch):
    base = ["w", "--config", "c", "--dataset", "d", "--checkpoint", "k", "--output-dir", "o",
            "--control-db", "b", "--experiment-id", "e", "--action-preservation-distill",
            "--comparison-report", "r", "--m2l-report", "m", "--m2l-checkpoint", "mk",
            "--m2mc-report", "x"]
    for extra in (["--action-preservation-fit"], ["--action-preservation-probe"],
                  ["--action-preservation-lambda10"], ["--local-fit"], ["--diverse-fit"],
                  ["--relabel-fit"], ["--relabel-learning-rate", "0.003"]):
        monkeypatch.setattr(sys, "argv", [*base, *extra])
        with pytest.raises(SystemExit):
            mw.main()
    captured = {}
    monkeypatch.setattr(mw, "run_memory", lambda *a, **k: captured.update(k) or {"status": "failed"})
    monkeypatch.setattr(sys, "argv", base)
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert mw.main() == 1
    assert captured["action_preservation_distill"] is True
    assert captured["action_preservation_fit"] is False
    assert captured["action_preservation_lambda10"] is False


def test_cli_subcommand_and_dispatch(monkeypatch, tmp_path):
    seen = {}
    original_train = cli.train_pilot_command
    monkeypatch.setattr(cli, "train_pilot_command", lambda a: seen.update(vars(a)) or {"status": "completed"})
    assert cli.main(["train-action-preserved-distill-memory", *REQUIRED]) == 0
    assert seen["action_preserved_distill_training"] is True
    assert not any(k in seen for k in ("learning_rate", "keep_lambda", "lambda"))
    for flag in ("--learning-rate", "--keep-lambda"):
        with pytest.raises(SystemExit):
            cli.main(["train-action-preserved-distill-memory", *REQUIRED, flag, "1"])

    monkeypatch.setattr(cli, "train_pilot_command", original_train)
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
        action_preserved_distill_training=True,
    )
    cli.train_pilot_command(args)
    assert captured["cmd"][2] == "ainerzero.runtime.memory_worker"
    assert "--action-preservation-distill" in captured["cmd"]
    assert captured["timeout"] == min(1640, cli.load_pilot_config(args.config).budget.max_wall_seconds)
    parsed = {}
    monkeypatch.setattr(mw, "run_memory", lambda *a, **k: parsed.update(k) or {"status": "failed"})
    monkeypatch.setattr(sys, "argv", ["worker", *captured["cmd"][3:]])
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert mw.main() == 1
    assert parsed["action_preservation_distill"] is True


# ------------------------------------------- wiring regression (review F1–F4)


FLAGS_D = {"action_preservation_distill": True, "action_preservation_fit": True,
            "action_preservation_lambda10": False, "action_preservation_probe": False,
            "relabel_fit": True, "diverse_fit": True, "local_fit": True}
FLAGS_KEEP = dict(FLAGS_D, action_preservation_distill=False)


def _eval_guard(test, flags):
    """Three-valued evaluation of a guard expression over the flag set."""
    text = ast.unparse(test)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None
    def ev(node):
        if isinstance(node, ast.BoolOp):
            vals = [ev(v) for v in node.values]
            if any(v is None for v in vals):
                return None
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            v = ev(node.operand)
            return None if v is None else (not v)
        if isinstance(node, ast.Name):
            return flags.get(node.id)
        if isinstance(node, ast.Constant):
            return bool(node.value)
        return None
    return ev(tree.body)


def _reachable(tree, flags):
    """Simple statements reachable under `flags` (guards evaluated, not just scanned)."""
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    out, containers = [], []

    def walk(stmts):
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                verdict = _eval_guard(stmt.test, flags)
                if verdict is not False:      # True or unknown -> conservative
                    walk(stmt.body)
                if verdict is not True:
                    walk(stmt.orelse)
            elif isinstance(stmt, (ast.For, ast.While, ast.With, ast.Try)):
                # container: never scanned wholesale (its guards are evaluated inside)
                containers.append(stmt)
                walk(getattr(stmt, "body", []))
                for handler in getattr(stmt, "handlers", []):
                    walk(handler.body)
                walk(getattr(stmt, "finalbody", []))
                walk(getattr(stmt, "orelse", []))
            else:
                out.append(stmt)
    walk(run_memory.body)
    return out, containers


def test_d_reachable_stages_are_covered_by_the_d_plan():
    """Review F4: flag-set reachability, so a stage added in ANY reachable branch fails.

    This catches the M5 mutant (`stage("teacher_cache")` inside `if relabel_fit:`),
    which literal block scanning missed.
    """
    tree = _worker_tree()
    reserved = set(mw.action_preservation_distill_memory_plan()["resource_seconds"])
    reached = set()
    for stmt in _reachable(tree, FLAGS_D)[0]:
        for call in ast.walk(stmt):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "stage" \
                    and call.args and isinstance(call.args[0], ast.Constant):
                reached.add(call.args[0].value)
    dynamic = {f"{phase}_memory_{part}" for phase in ("before", "after") for part in ("train", "development")}
    dynamic |= {f"{phase}_{suffix}" for phase in ("before", "after") for suffix in ("action", "reconstruction")}
    reached |= {name for name in dynamic if name in reserved}
    assert reached, "reachability must find the training-path stages"
    assert reached <= reserved, sorted(reached - reserved)
    assert {"teacher_cache", "cache_protocol_checks"}.isdisjoint(reached)


def test_d_reachable_code_never_reads_unbound_cache_bindings():
    """Review F4: no reachable read of the keep-branch cache bindings under D.

    Catches the M4b mutant (an extra unguarded copy of the cache identity check).
    """
    tree = _worker_tree()
    cache_names = {"cache_path", "cache_file", "cache_manifest", "cache_arrays"}
    reads, binds = set(), set()
    for stmt in _reachable(tree, FLAGS_D)[0]:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and node.id in cache_names:
                (binds if isinstance(node.ctx, ast.Store) else reads).add(node.id)
    assert reads <= binds, sorted(reads - binds)
    assert reads == set(), sorted(reads)
    # under the keep-branch condition the same scan does see the cache bindings,
    # so the audit itself has teeth
    keep_reads, keep_binds = set(), set()
    for stmt in _reachable(tree, FLAGS_KEEP)[0]:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and node.id in cache_names:
                (keep_binds if isinstance(node.ctx, ast.Store) else keep_reads).add(node.id)
    assert {"cache_path", "cache_file"} <= keep_binds and keep_reads <= keep_binds


def test_every_stage_constant_in_run_memory_is_reserved_by_some_condition():
    """Plan budgets must cover every stage constant reachable in run_memory.

    The keep-branch conditions reserve everything except the two reused M2l stages;
    D additionally drops the keep-branch cache stages, and its branch must not call
    them (asserted above).
    """
    tree = _worker_tree()
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    constants = set()
    for node in ast.walk(run_memory):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "stage" \
                and node.args and isinstance(node.args[0], ast.Constant):
            constants.add(node.args[0].value)
    dynamic = {f"{phase}_memory_{part}" for phase in ("before", "after") for part in ("train", "development")}
    dynamic |= {f"{phase}_{suffix}" for phase in ("before", "after") for suffix in ("action", "reconstruction")}
    needed = constants | dynamic
    base = set(mw.action_preservation_memory_plan()["resource_seconds"])
    distill = set(mw.action_preservation_distill_memory_plan()["resource_seconds"])
    assert needed - base == {"m2l_paired_cells", "m2l_relabel_pool"}
    assert needed - distill == {"m2l_paired_cells", "m2l_relabel_pool",
                                "teacher_cache", "cache_protocol_checks"}
    # every stage constant is reserved by at least one registered condition plan
    relabel = set(mw.relabel_memory_plan(0.003)["resource_seconds"])
    assert needed <= base | distill | relabel
    assert {"m2l_paired_cells", "m2l_relabel_pool"} <= relabel - distill


def test_d_reads_no_name_that_is_only_bound_outside_the_d_path():
    """General form of review F1/F2/F3 and of the E21 `m2l_cells` failure.

    Any name assigned somewhere in run_memory that is *read* on the D path must be
    bound on the D path too (assignments, for-targets or with-items). This catches
    every "bound only in the keep branch" defect without naming them one by one.
    """
    import builtins

    tree = _worker_tree()
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    leaves, containers = _reachable(tree, FLAGS_D)
    bound = {n.id for stmt in leaves for n in ast.walk(stmt)
             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    for node in containers:
        if isinstance(node, ast.For):
            bound |= {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
        if isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    bound |= {n.id for n in ast.walk(item.optional_vars) if isinstance(n, ast.Name)}
    assigned_anywhere = {n.id for n in ast.walk(run_memory)
                         if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    imported = {a.asname or a.name.split(".")[0] for n in ast.walk(run_memory)
                if isinstance(n, ast.Import) for a in n.names}
    imported |= {a.asname or a.name for n in ast.walk(run_memory)
                 if isinstance(n, ast.ImportFrom) for a in n.names}
    params = {a.arg for a in run_memory.args.args + run_memory.args.kwonlyargs}
    loaded = {n.id for stmt in leaves for n in ast.walk(stmt)
              if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    suspicious = (loaded & assigned_anywhere) - bound - imported - params - set(dir(builtins))
    assert suspicious == set(), sorted(suspicious)
