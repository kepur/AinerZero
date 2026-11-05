"""M2n tests: nonzero-history memory windows with D's in-batch teacher distillation.

CPU only: no MLX, no run. Covers the condition plan, the cost arithmetic, the
entry wiring (with the same flag-set reachability audit used for D), and the
existence of every registered condition after the new flag was added.
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
REQUIRED = ["--dataset", "d", "--checkpoint", "c", "--comparison-report", "r", "--m2l-report", "m",
            "--m2l-checkpoint", "k", "--m2mc-report", "x", "--experiment-id", "e"]


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _worker_tree():
    return ast.parse(WORKER.read_text())


def test_no_mlx_imported():
    code = ("import sys, ainerzero.runtime.memory_worker; "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    import subprocess
    subprocess.run([sys.executable, "-c", code], check=True)


def test_m2n_condition_plan():
    condition = apc.m2n_condition_plan()
    base = ap.action_preservation_plan()
    assert condition["protocol"] == apc.M2N_PROTOCOL == "m2m_n_nonzero_history_one_step_v1"
    assert condition["base_plan_sha256"] == ap.FROZEN_PLAN_SHA256
    assert condition["keep_branch"]["lambda"] == 1.0 and condition["keep_branch"]["rows"] == 0
    assert condition["teacher_cache"].startswith("none")
    assert condition["units"]["total"] == 255_104 == 171_904 + 2 * 41_600
    assert condition["windows"] == {"burn_in": 4, "loss_steps": 8, "transitions_per_window": 12,
                                    "frames_per_sample": 13, "units_per_update": 416}
    assert condition["seconds"] == {"retained_fixed": 940, "updates": 800, "prepaid": 1_740,
                                    "work_deadline": 1_760, "supervisor_deadline": 1_790}
    assert "history" in condition["memory_windows"]
    body = {k: v for k, v in condition.items() if k != "condition_sha256"}
    assert condition["condition_sha256"] == _digest(body)
    changed = {k for k in set(condition) | set(base) if condition.get(k) != base.get(k)}
    assert changed == {"protocol", "base_protocol", "base_plan_sha256", "single_factor", "loss",
                       "keep_branch", "teacher_cache", "units", "seconds", "condition_sha256",
                       "memory_windows", "windows"}


def test_m2n_plan_arithmetic_and_cost():
    plan = mw.action_preservation_history_memory_plan()
    assert plan["protocol"] == apc.M2N_PROTOCOL
    assert (plan["updates"], plan["learning_rate"], plan["batch_size"], plan["micro_batch_size"]) == (200, 0.003, 16, 4)
    assert (plan["burn_in"], plan["sequence_steps"]) == (4, 8)
    assert plan["transitions_per_window"] == 12 == plan["burn_in"] + plan["sequence_steps"]
    assert plan["training_model_units_per_update"] == 416 == 2 * 16 * 13
    assert plan["expected_total_model_units"] == 171_904 + 200 * 416 == 255_104
    assert plan["seeds"]["windows"] == 2101
    assert plan["total_reserved_seconds_if_complete"] == 940 + 200 * 4 == 1_740
    assert (plan["supervised_deadline_seconds"], plan["supervisor_deadline_seconds"]) == (1_760, 1_790)
    assert plan["supervisor_deadline_seconds"] <= ap.SINGLE_RUN_LIMIT_SECONDS
    assert {"teacher_cache", "cache_protocol_checks"}.isdisjoint(plan["resource_seconds"])
    assert plan["keep_lambda"] == 1.0
    assert plan["distill"] == "in_batch_same_forward_relabelled_teacher"
    assert ap.verify_frozen_plan(plan["action_preservation"]) == ap.FROZEN_PLAN_SHA256
    assert plan["expected_total_model_units"] == plan["action_preservation_condition"]["units"]["total"]
    # every earlier condition still hashes to its registered numbers
    assert mw.action_preservation_memory_plan()["expected_total_model_units"] == 208_546
    assert mw.action_preservation_lambda10_memory_plan()["keep_lambda"] == 10.0
    assert mw.action_preservation_distill_memory_plan()["expected_total_model_units"] == 184_704
    assert mw.action_preservation_probe_plan()["expected_total_model_units"] == 5_025


FLAGS_M2N = {"action_preservation_history": True, "action_preservation_mixed": False,
             "action_preservation_distill": True,
             "action_preservation_fit": True, "action_preservation_lambda10": False,
             "action_preservation_probe": False, "relabel_fit": True, "diverse_fit": True,
             "local_fit": True}


def _eval_guard(test, flags):
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
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    out, containers = [], []

    def walk(stmts):
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                verdict = _eval_guard(stmt.test, flags)
                if verdict is not False:
                    walk(stmt.body)
                if verdict is not True:
                    walk(stmt.orelse)
            elif isinstance(stmt, (ast.For, ast.While, ast.With, ast.Try)):
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


def test_m2n_reachable_stages_are_covered_by_the_m2n_plan():
    tree = _worker_tree()
    reserved = set(mw.action_preservation_history_memory_plan()["resource_seconds"])
    reached = set()
    for stmt in _reachable(tree, FLAGS_M2N)[0]:
        for call in ast.walk(stmt):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "stage" \
                    and call.args and isinstance(call.args[0], ast.Constant):
                reached.add(call.args[0].value)
    dynamic = {f"{phase}_memory_{part}" for phase in ("before", "after") for part in ("train", "development")}
    dynamic |= {f"{phase}_{suffix}" for phase in ("before", "after") for suffix in ("action", "reconstruction")}
    reached |= {name for name in dynamic if name in reserved}
    assert reached and reached <= reserved, sorted(reached - reserved)
    assert {"teacher_cache", "cache_protocol_checks"}.isdisjoint(reached)


def test_m2n_reads_no_name_that_is_only_bound_outside_the_m2n_path():
    """General unbound-name audit (the class of defect that failed D twice)."""
    import builtins

    tree = _worker_tree()
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    leaves, containers = _reachable(tree, FLAGS_M2N)
    bound = {n.id for stmt in leaves for n in ast.walk(stmt)
             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    # nested function/lambda parameters bind names too (e.g. `lambda a, b: a + b`)
    for stmt in leaves:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                args = node.args
                bound |= {a.arg for a in list(args.args) + list(args.kwonlyargs)
                          + list(getattr(args, "posonlyargs", []))}
                if args.vararg:
                    bound.add(args.vararg.arg)
                if args.kwarg:
                    bound.add(args.kwarg.arg)
    for node in containers:
        if isinstance(node, ast.For):
            bound |= {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
        if isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    bound |= {n.id for n in ast.walk(item.optional_vars) if isinstance(n, ast.Name)}
    assigned = {n.id for n in ast.walk(run_memory)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    imported = {a.asname or a.name.split(".")[0] for n in ast.walk(run_memory)
                if isinstance(n, ast.Import) for a in n.names}
    imported |= {a.asname or a.name for n in ast.walk(run_memory)
                 if isinstance(n, ast.ImportFrom) for a in n.names}
    params = {a.arg for a in run_memory.args.args + run_memory.args.kwonlyargs}
    loaded = {n.id for stmt in leaves for n in ast.walk(stmt)
              if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    suspicious = (loaded & assigned) - bound - imported - params - set(dir(builtins))
    assert suspicious == set(), sorted(suspicious)


def test_m2n_entry_validation_and_cli(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="choose one action-preservation condition"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_history=True, action_preservation_distill=True,
                      m2mc_report_path=tmp_path / "x")
    with pytest.raises(ValueError, match="choose one action-preservation condition"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_history=True, action_preservation_fit=True,
                      m2mc_report_path=tmp_path / "x")
    with pytest.raises(ValueError, match="exactly its M2m-c report"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e", action_preservation_history=True)

    seen = {}
    original = cli.train_pilot_command
    monkeypatch.setattr(cli, "train_pilot_command", lambda a: seen.update(vars(a)) or {"status": "completed"})
    assert cli.main(["train-action-preserved-history-memory", *REQUIRED]) == 0
    assert seen["action_preserved_history_training"] is True
    assert not any(k in seen for k in ("learning_rate", "sequence_steps", "burn_in", "keep_lambda"))
    for flag in ("--learning-rate", "--sequence-steps", "--burn-in"):
        with pytest.raises(SystemExit):
            cli.main(["train-action-preserved-history-memory", *REQUIRED, flag, "4"])
    monkeypatch.setattr(cli, "train_pilot_command", original)

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
        action_preserved_history_training=True,
    )
    cli.train_pilot_command(args)
    assert captured["cmd"][2] == "ainerzero.runtime.memory_worker"
    assert "--action-preservation-history" in captured["cmd"]
    assert captured["timeout"] == min(1790, cli.load_pilot_config(args.config).budget.max_wall_seconds)
    parsed = {}
    monkeypatch.setattr(mw, "run_memory", lambda *a, **k: parsed.update(k) or {"status": "failed"})
    monkeypatch.setattr(sys, "argv", ["worker", *captured["cmd"][3:]])
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert mw.main() == 1
    assert parsed["action_preservation_history"] is True


def test_worker_flag_is_exclusive(monkeypatch):
    base = ["w", "--config", "c", "--dataset", "d", "--checkpoint", "k", "--output-dir", "o",
            "--control-db", "b", "--experiment-id", "e", "--action-preservation-history",
            "--comparison-report", "r", "--m2l-report", "m", "--m2l-checkpoint", "mk",
            "--m2mc-report", "x"]
    for extra in (["--action-preservation-fit"], ["--action-preservation-probe"],
                  ["--action-preservation-lambda10"], ["--action-preservation-distill"],
                  ["--local-fit"], ["--diverse-fit"], ["--relabel-fit"]):
        monkeypatch.setattr(sys, "argv", [*base, *extra])
        with pytest.raises(SystemExit):
            mw.main()


def test_units_follow_the_registered_sampler_window_contract():
    """Review F2: units must cover burn_in + sequence_steps transitions per sample.

    The registered M2h plan is the reference: 4 + 16 = 20 transitions, 336 units
    for 16 samples (21 frames each). M2n must satisfy the same identity, and it
    must count the online teacher as a second pass.
    """
    m2h = mw.memory_plan()
    assert m2h["transitions_per_window"] == m2h["burn_in"] + m2h["sequence_steps"] == 20
    assert m2h["training_model_units_per_update"] == m2h["batch_size"] * (20 + 1) == 336
    m2n = mw.action_preservation_history_memory_plan()
    frames = m2n["burn_in"] + m2n["sequence_steps"] + 1
    assert frames == 13
    assert m2n["transitions_per_window"] == frames - 1
    assert m2n["training_model_units_per_update"] == 2 * m2n["batch_size"] * frames == 416
    assert m2n["expected_total_model_units"] == 171_904 + 200 * 416 == 255_104
    assert m2n["action_preservation_condition"]["units"]["total"] == 255_104


def _seed_keys_read(tree, flags):
    """plan["seeds"][X] keys read on the statements reachable under `flags`.

    Nested functions that open with `if not <flag>: return` (the local-check helper)
    are skipped when that flag is False, because they cannot reach their body.
    """
    keys = set()

    def scan(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.IfExp):
                verdict = _eval_guard(child.test, flags)
                if verdict is not False:
                    scan(child.body)
                if verdict is not True:
                    scan(child.orelse)
            else:
                inner = child
                if (isinstance(inner, ast.Subscript) and isinstance(inner.value, ast.Subscript)):
                    base, outer = inner.value, inner.slice
                    if (isinstance(base.value, ast.Name) and base.value.id == "plan"
                            and isinstance(base.slice, ast.Constant) and base.slice.value == "seeds"
                            and isinstance(outer, ast.Constant) and isinstance(outer.value, str)):
                        keys.add(outer.value)
                scan(child)

    leaves, containers = _reachable(tree, flags)
    for container in containers:  # loop/with headers bind and read names too
        if isinstance(container, ast.For):
            scan(container.iter)
        elif isinstance(container, ast.While):
            scan(container.test)
        elif isinstance(container, ast.With):
            for item in container.items:
                scan(item.context_expr)
    for stmt in leaves:
        if isinstance(stmt, ast.FunctionDef):
            head = [n for n in stmt.body[:4] if not (isinstance(n, ast.Expr)
                                                     and isinstance(n.value, ast.Constant))]
            guard = next((n for n in head if isinstance(n, ast.If)), None)
            if guard is not None and isinstance(guard.body[0], ast.Return):
                test = guard.test
                if (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
                        and isinstance(test.operand, ast.Name)
                        and flags.get(test.operand.id) is False):
                    continue  # helper returns before its body under this condition
        scan(stmt)
    return keys


def test_every_seed_key_read_in_the_worker_exists_in_every_condition():
    """Review F1 (value level): each condition must carry every seed key its path reads.

    M2n reads `plan["seeds"]["windows"]`, but the plan inherited micro_memory_plan's
    seeds dict (no 'windows') -> a guaranteed KeyError on the real path that every
    name-level audit and the CPU tests missed. The check is per-condition reachability:
    conditions whose guard is False never read the key and must not be forced to add it
    (their plan digests are frozen).
    """
    tree = _worker_tree()
    off = {"local_fit": False, "relabel_fit": False, "diverse_fit": False,
           "action_preservation_fit": False, "action_preservation_distill": False,
           "action_preservation_lambda10": False, "action_preservation_probe": False,
           "action_preservation_history": False, "action_preservation_mixed": False}
    on = {**off, "local_fit": True, "relabel_fit": True, "diverse_fit": True}
    cases = [
        ("memory(M2h)", mw.memory_plan(), dict(off)),
        ("micro", mw.micro_memory_plan(), {**on, "relabel_fit": False, "diverse_fit": False}),
        ("relabel", mw.relabel_memory_plan(0.003), dict(on)),
        ("m2m-d", mw.action_preservation_memory_plan(), {**on, "action_preservation_fit": True}),
        ("c07", mw.action_preservation_lambda10_memory_plan(), {**on, "action_preservation_fit": True}),
        ("d", mw.action_preservation_distill_memory_plan(),
         {**on, "action_preservation_fit": True, "action_preservation_distill": True}),
        ("m2n", mw.action_preservation_history_memory_plan(), dict(FLAGS_M2N)),
        ("mixed", mw.action_preservation_mixed_memory_plan(),
         {**FLAGS_M2N, "action_preservation_history": False, "action_preservation_mixed": True}),
    ]
    for name, plan, flags in cases:
        read = _seed_keys_read(tree, flags)
        assert read, name
        assert read <= set(plan["seeds"]), (name, sorted(read - set(plan["seeds"])))
    # the sampler paths are the only ones that need the registered window seed
    assert "windows" in _seed_keys_read(tree, dict(off))
    assert "windows" in _seed_keys_read(tree, dict(FLAGS_M2N))
    assert "windows" not in _seed_keys_read(tree, {**on, "action_preservation_fit": True})
    assert "windows" not in _seed_keys_read(tree, dict(on))
    assert "augmentation" not in _seed_keys_read(
        tree, {**on, "relabel_fit": False, "action_preservation_fit": False})


def test_front_row_gradient_invariant_is_scoped_to_single_edge_plans():
    """The M2n failure: a single-edge structural invariant fired on history windows.

    `single-edge memory unexpectedly has front-output gradients` guards the
    registered M2m-d/C07/D/probe formulations, where the loss cannot reach the GRU
    front rows. M2n's multi-step windows reach them through earlier steps, so the
    invariant must be scoped by the plan's registered window length -- and the
    applied gradient must stay masked in both cases (tail-only scope).
    """
    tree = _worker_tree()
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    raises = [n for n in ast.walk(run_memory)
              if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
              and isinstance(n.exc.func, ast.Name) and n.exc.func.id == "RuntimeError"
              and n.exc.args and isinstance(n.exc.args[0], ast.Constant)
              and n.exc.args[0].value == "single-edge memory unexpectedly has front-output gradients"]
    assert len(raises) >= 1, "the invariant must exist"
    scoped = []
    for raise_node in raises:
        guards = [ast.unparse(n.test) for n in ast.walk(run_memory)
                  if isinstance(n, ast.If) and n.lineno < raise_node.lineno
                  and any(stmt is raise_node for stmt in n.body)]
        assert guards, f"raise at line {raise_node.lineno} must sit inside a guard"
        # accepted forms: the plan-level single-edge window, or the mixed condition's
        # per-half scope (the single-edge half keeps it, the history half does not)
        accepted = [n for n in ast.walk(run_memory)
                    if isinstance(n, ast.If) and n.lineno < raise_node.lineno
                    and any(stmt is raise_node for stmt in n.body)
                    and (("transitions_per_window" in ast.unparse(n.test) and "== 1" in ast.unparse(n.test))
                         or ('name == "single_edge"' in ast.unparse(n.test).replace("'", '"')))]
        assert accepted, guards
        # the guard body must actually stop the run: downgrading the raise to a log
        # (mutant N04) has to fail here, not just the expression text
        for node in accepted:
            assert any(isinstance(stmt, ast.Raise) for stmt in node.body), ast.unparse(node)
        scoped.append(guards)
    assert len(scoped) == len(raises)
    forms = set()
    for _, guards in zip(raises, scoped):
        for g in guards:
            text = g.replace("'", '"')
            if "transitions_per_window" in g and "== 1" in g:
                forms.add("plan_single_edge_window")
            if 'name == "single_edge"' in text:
                forms.add("mixed_per_half_scope")
    # both scope forms must exist: removing either one (mutant N04) fails here
    assert forms == {"plan_single_edge_window", "mixed_per_half_scope"}, forms
    # the registered single-edge conditions keep the strict invariant
    for name, plan in (("m2m-d", mw.action_preservation_memory_plan()),
                       ("c07", mw.action_preservation_lambda10_memory_plan()),
                       ("d", mw.action_preservation_distill_memory_plan()),
                       ("probe", mw.action_preservation_probe_plan())):
        assert plan["transitions_per_window"] == 1, name
    assert mw.action_preservation_history_memory_plan()["transitions_per_window"] == 12
    # the mixed condition declares the single-edge window for its invariant and
    # exempts only its history half through the per-half `name == "single_edge"` scope
    mixed = mw.action_preservation_mixed_memory_plan()
    assert mixed["transitions_per_window"] == 1 and mixed["history_rows"] == 4
    # the applied gradient is still the masked one on both paths
    source = WORKER.read_text()
    assert source.count("                gradients = masked") == 1
