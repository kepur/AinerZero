"""M2n-M tests: 12 registered single-edge rows plus 4 history windows per batch.

CPU only. Covers the condition plan, the cost identity, the two-half wiring
(separate normalization, per-half invariants, row-weighted combination), the
registered seed keys, the P3 telemetry fix, the entry surface, and the flag-set
reachability/unbound-name audits used for the earlier conditions.
"""

import ast
import hashlib
import json
import subprocess
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
DATASET = ROOT / "artifacts/pilot/pilot-b27a34514fe74ba2a969bad3c24d3ee3/dataset.json"
REQUIRED = ["--dataset", "d", "--checkpoint", "c", "--comparison-report", "r", "--m2l-report", "m",
            "--m2l-checkpoint", "k", "--m2mc-report", "x", "--experiment-id", "e"]


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def test_no_mlx_imported():
    code = ("import sys, ainerzero.runtime.memory_worker; "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    subprocess.run([sys.executable, "-c", code], check=True)


def test_mixed_condition_plan_values():
    condition = apc.mixed_condition_plan()
    base = ap.action_preservation_plan()
    assert condition["protocol"] == apc.MIXED_PROTOCOL == "m2m_n_mixed_single_edge_history_v1"
    assert condition["base_plan_sha256"] == ap.FROZEN_PLAN_SHA256
    assert condition["batch"]["single_edge_rows"] == 12
    assert condition["batch"]["history_rows"] == 4
    assert condition["keep_branch"]["lambda"] == 1.0 and condition["keep_branch"]["rows"] == 0
    assert condition["units"]["total"] == 202_304 == 171_904 + 4_800 + 10_400 + 15_200
    seconds = {k: v for k, v in condition["seconds"].items() if k != "amendment"}
    assert seconds == {"retained_fixed": 1_140, "updates": 600, "prepaid": 1_740,
                       "work_deadline": 1_760, "supervisor_deadline": 1_780}
    assert "evaluation windows" in condition["seconds"]["amendment"]
    windows = condition["windows"]
    assert windows["history_burn_in"] == 4 and windows["history_loss_steps"] == 8
    assert windows["history_transitions"] == 12 and windows["history_frames"] == 13
    assert windows["units_per_update"] == 152
    assert windows["units_per_update_breakdown"] == {"student_single_edge": 24,
                                                     "student_history": 52,
                                                     "teacher_both_halves": 76}
    assert sum(windows["units_per_update_breakdown"].values()) == windows["units_per_update"]
    assert "row_weighted_mean" in condition["normalization"]
    assert "12*CE_single+4*CE_history" in condition["normalization"].replace(" ", "")
    body = {k: v for k, v in condition.items() if k != "condition_sha256"}
    assert condition["condition_sha256"] == _digest(body)
    changed = {k for k in set(condition) | set(base) if condition.get(k) != base.get(k)}
    assert {"protocol", "base_plan_sha256", "base_protocol", "batch", "normalization", "loss",
            "keep_branch", "teacher_cache", "units", "seconds", "windows", "single_factor",
            "condition_sha256"} <= changed


def test_mixed_plan_cost_identity_and_seeds():
    plan = mw.action_preservation_mixed_memory_plan()
    frames = plan["history_burn_in"] + plan["history_sequence_steps"] + 1
    assert frames == 13
    student = plan["single_edge_rows"] * 2 + plan["history_rows"] * frames
    assert student == 76
    assert plan["training_model_units_per_update"] == 2 * student == 152
    assert plan["expected_total_model_units"] == 171_904 + 200 * 152 == 202_304
    assert plan["expected_total_model_units"] == plan["action_preservation_condition"]["units"]["total"]
    assert plan["total_reserved_seconds_if_complete"] == 1_140 + 200 * 3 == 1_740
    assert (plan["supervised_deadline_seconds"], plan["supervisor_deadline_seconds"]) == (1_760, 1_780)
    assert plan["resource_seconds"]["before_memory_train"] == 150
    assert plan["resource_seconds"]["after_memory_train"] == 150
    assert plan["supervisor_deadline_seconds"] <= ap.SINGLE_RUN_LIMIT_SECONDS
    assert plan["seeds"]["windows"] == 2101 and plan["seeds"]["augmentation"] == 2307
    assert plan["keep_lambda"] == 1.0 and plan["transitions_per_window"] == 1
    assert plan["distill"] == "in_batch_same_forward_teacher_on_each_half"
    assert {"teacher_cache", "cache_protocol_checks"}.isdisjoint(plan["resource_seconds"])
    assert ap.verify_frozen_plan(plan["action_preservation"]) == ap.FROZEN_PLAN_SHA256
    # every earlier condition is untouched
    assert mw.action_preservation_memory_plan()["expected_total_model_units"] == 208_546
    assert mw.action_preservation_lambda10_memory_plan()["keep_lambda"] == 10.0
    assert mw.action_preservation_distill_memory_plan()["expected_total_model_units"] == 184_704
    assert mw.action_preservation_history_memory_plan()["expected_total_model_units"] == 255_104
    assert mw.action_preservation_probe_plan()["expected_total_model_units"] == 5_025


def test_mixed_halves_have_the_registered_shapes():
    """Value/shape audit: the two halves are built from real registered data."""
    if not DATASET.exists():
        pytest.skip("registered dataset is not present in this checkout")
    from ainerzero.core.experience import TrainingPolicy
    from ainerzero.core.pilot import load_pilot_config
    from ainerzero.data.pilot_dataset import load_pilot_dataset
    from ainerzero.data.sequences import SequenceSampler
    from ainerzero.learning.diverse_memory import get_diverse_batch, select_diverse_memory_samples
    from ainerzero.runtime.c0_collection import RANDOM_ACTOR

    config = load_pilot_config(ROOT / "configs/pilot.yaml")
    paths, episodes, _ = load_pilot_dataset(
        str(DATASET), TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    )
    pool, _ = select_diverse_memory_samples(episodes["train"])
    plan = mw.action_preservation_mixed_memory_plan()
    single = get_diverse_batch(pool, 0)
    single = {k: v[: plan["single_edge_rows"]] for k, v in single.items()}
    assert single["symbols"].shape == (12, 2, 8) and single["actions"].shape == (12, 1)
    # same source as production: the sampler geometry field, not the plan-level
    # burn_in/sequence_steps (which describe the single-edge half -- the B-F1 defect)
    geometry = plan["sampler_geometry"]
    assert geometry == {"burn_in": plan["history_burn_in"],
                        "sequence_steps": plan["history_sequence_steps"]}
    sampler = SequenceSampler(paths["train"], TrainingPolicy(allowed_actors=(RANDOM_ACTOR,)),
                              burn_in=geometry["burn_in"],
                              sequence_steps=geometry["sequence_steps"])
    history = sampler.sample(plan["history_rows"], np.random.default_rng(plan["seeds"]["windows"]))
    assert history["symbols"].shape == (4, 13, 8)
    assert history["actions"].shape == (4, 12)
    assert history["episode_start"].shape == (4, 13)
    assert plan["history_sequence_steps"] == history["actions"].shape[1] - plan["history_burn_in"]
    assert config.training.gradient_clip_norm == 1.0  # unchanged registered clipping


def test_mixed_wiring_is_two_half_and_scoped():
    tree = ast.parse(WORKER.read_text())
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    source = ast.unparse(run_memory).replace("'", '"')
    # both halves are built and accumulated separately
    assert "single_batch" in source and "history_batch" in source
    assert "mixed_details" in source
    assert 'mask_gru_tail_gradients(mean_grads)' in source
    # the single-edge half keeps the strict invariant, the history half does not
    assert 'if name == "single_edge" and half_front > 1e-08' in source
    # the combined-gradient masking block must skip the mixed condition
    assert "if local_fit and (not action_preservation_mixed)" in source
    # row-weighted combination by the registered row counts (A4: via apc.mixed_half_weights;
    # E24 mixed keeps lambda_h = 1, i.e. exactly the 12:4 row weights over 16)
    assert ('weights, total_weight = apc.mixed_half_weights(plan["single_edge_rows"], '
            'plan["history_rows"], history_weight)') in source
    assert 'history_weight = plan["history_weight"] if action_preservation_mixed_weight025 else 1.0' in source
    assert "gradients = apc.combine_mixed_halves(half_grads, weights, total_weight, tree_map)" in source
    assert apc.mixed_half_weights(12, 4, 1.0) == ({"single_edge": 12.0, "history": 4.0}, 16.0)
    # P3: the log records the real forms, not the pool schedule
    assert '"unused_schedule_rows"' in source and '"window_sha256"' in source
    assert '"bijection_digests"' in source and '"sampler_sequence_steps"' in source
    raw = WORKER.read_text()
    assert raw.count("if diverse_fit and not action_preservation_mixed:") == 1


FLAGS_MIXED = {"action_preservation_mixed": True, "action_preservation_distill": True,
               "action_preservation_fit": True, "action_preservation_lambda10": False,
               "action_preservation_probe": False, "action_preservation_history": False,
               "relabel_fit": True, "diverse_fit": True, "local_fit": True}


def _eval_guard(test, flags):
    try:
        tree = ast.parse(ast.unparse(test), mode="eval")
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


def test_mixed_reachable_stages_and_names():
    tree = ast.parse(WORKER.read_text())
    reserved = set(mw.action_preservation_mixed_memory_plan()["resource_seconds"])
    leaves, containers = _reachable(tree, FLAGS_MIXED)
    stages = set()
    for stmt in leaves:
        for call in ast.walk(stmt):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "stage" \
                    and call.args and isinstance(call.args[0], ast.Constant):
                stages.add(call.args[0].value)
    dynamic = {f"{phase}_memory_{part}" for phase in ("before", "after") for part in ("train", "development")}
    dynamic |= {f"{phase}_{suffix}" for phase in ("before", "after") for suffix in ("action", "reconstruction")}
    stages |= {name for name in dynamic if name in reserved}
    assert stages and stages <= reserved, sorted(stages - reserved)
    assert {"teacher_cache", "cache_protocol_checks"}.isdisjoint(stages)

    import builtins
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
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


def test_mixed_entry_exclusivity_and_cli(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="choose one action-preservation condition"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_mixed=True, action_preservation_history=True,
                      m2mc_report_path=tmp_path / "x")
    with pytest.raises(ValueError, match="choose one action-preservation condition"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_mixed=True, action_preservation_distill=True,
                      m2mc_report_path=tmp_path / "x")
    with pytest.raises(ValueError, match="exactly its M2m-c report"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e", action_preservation_mixed=True)

    seen = {}
    original = cli.train_pilot_command
    monkeypatch.setattr(cli, "train_pilot_command",
                        lambda a: seen.update(vars(a)) or {"status": "completed"})
    assert cli.main(["train-action-preserved-mixed-memory", *REQUIRED]) == 0
    assert seen["action_preserved_mixed_training"] is True
    assert not any(k in seen for k in ("learning_rate", "history_rows", "keep_lambda"))
    for flag in ("--learning-rate", "--history-rows", "--burn-in"):
        with pytest.raises(SystemExit):
            cli.main(["train-action-preserved-mixed-memory", *REQUIRED, flag, "4"])
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
        action_preserved_mixed_training=True,
    )
    cli.train_pilot_command(args)
    assert "--action-preservation-mixed" in captured["cmd"]
    assert captured["timeout"] == min(1780, cli.load_pilot_config(args.config).budget.max_wall_seconds)


def test_worker_flag_is_exclusive(monkeypatch):
    base = ["w", "--config", "c", "--dataset", "d", "--checkpoint", "k", "--output-dir", "o",
            "--control-db", "b", "--experiment-id", "e", "--action-preservation-mixed",
            "--comparison-report", "r", "--m2l-report", "m", "--m2l-checkpoint", "mk",
            "--m2mc-report", "x"]
    for extra in (["--action-preservation-fit"], ["--action-preservation-probe"],
                  ["--action-preservation-lambda10"], ["--action-preservation-distill"],
                  ["--action-preservation-history"], ["--local-fit"], ["--diverse-fit"],
                  ["--relabel-fit"]):
        monkeypatch.setattr(sys, "argv", [*base, *extra])
        with pytest.raises(SystemExit):
            mw.main()


# --------------------- production-source audits for review findings B-F1/B-F3/B-F7


def test_production_sampler_uses_the_plan_sampler_geometry():
    """Review B-F1: the production sampler must not borrow the single-edge geometry.

    The mixed plan's plan-level burn_in/sequence_steps describe its single-edge half
    (0/1). A first implementation built the sampler from those fields, so the history
    half received 2-frame batches and died on the `burn_in < steps` guard before the
    first optimizer step; the test fixture had hand-written the right geometry, which
    is why the suite was green. This test pins the plan field and the production
    expression; the real-data shape evidence lives in
    `test_mixed_halves_have_the_registered_shapes`, which now builds its sampler from
    `plan["sampler_geometry"]` (same source as production).
    """
    tree = ast.parse(WORKER.read_text())
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    calls = [n for n in ast.walk(run_memory) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "SequenceSampler"]
    assert len(calls) == 1
    kwargs = {k.arg: ast.unparse(k.value).replace("'", '"') for k in calls[0].keywords}
    assert kwargs["burn_in"] == 'geometry["burn_in"]', kwargs
    assert kwargs["sequence_steps"] == 'geometry["sequence_steps"]', kwargs
    assert 'plan.get("sampler_geometry"' in ast.unparse(run_memory).replace("'", '"')
    plan = mw.action_preservation_mixed_memory_plan()
    assert plan["sampler_geometry"] == {"burn_in": 4, "sequence_steps": 8}
    assert (plan["burn_in"], plan["sequence_steps"]) == (0, 1)
    assert plan["sampler_geometry"] != {"burn_in": plan["burn_in"],
                                        "sequence_steps": plan["sequence_steps"]}


def test_registered_bijection_stream_survives_replay():
    """Review B-F3: replaying the registered stream must reproduce the manifest.

    The single-edge half consumes exactly 16 relabel draws per update from seed 2307.
    The published implementation let the history half draw from the same generator,
    which shifted the stream from update 1 on and would have tripped the manifest
    guard. This replay reproduces the registered stream end to end (its digest equals
    the M2m-c report's `training_permutations_sha256`); the wiring that keeps the two
    generators apart is pinned separately by
    `test_mixed_rng_call_arguments_are_wired`.
    """
    report_path = ROOT / "artifacts/reports/m2mc-lr0003-relabel.json"
    if not (DATASET.exists() and report_path.exists()):
        pytest.skip("registered dataset or M2m-c report is not present in this checkout")
    import json as _json

    from ainerzero.core.experience import TrainingPolicy
    from ainerzero.data.pilot_dataset import load_pilot_dataset
    from ainerzero.learning.diverse_memory import get_diverse_batch, select_diverse_memory_samples
    from ainerzero.learning.relabel_memory import TRAINING_PERMUTATION_COUNT, relabel_batch
    from ainerzero.runtime.c0_collection import RANDOM_ACTOR

    report = _json.loads(report_path.read_bytes())
    registered = report["relabel"]["training_permutations_sha256"]
    plan = mw.action_preservation_mixed_memory_plan()
    _, episodes, _ = load_pilot_dataset(str(DATASET), TrainingPolicy(allowed_actors=(RANDOM_ACTOR,)))
    pool, _ = select_diverse_memory_samples(episodes["train"])
    rng = np.random.default_rng(plan["seeds"]["augmentation"])
    digests = []
    for index in range(200):
        batch = get_diverse_batch(pool, index)
        _, update_digests = relabel_batch(batch, rng)
        assert len(update_digests) == plan["batch_size"] == 16
        digests.extend(update_digests)
    assert len(digests) == TRAINING_PERMUTATION_COUNT == 3_200
    replayed = hashlib.sha256(
        _json.dumps(digests, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert replayed == registered
    # the history half must use its own registered generator, and the plan must say so
    assert plan["seeds"]["mixed_history_augmentation"] == 2407
    assert plan["action_preservation_condition"]["history_permutation"]["seed"] == 2407
    assert plan["seeds"]["mixed_history_augmentation"] != plan["seeds"]["augmentation"]


def _select_ifexp(node, flags):
    """Return (selected branch node, evaluated test texts) for an IfExp chain."""
    tests = []
    while isinstance(node, ast.IfExp):
        verdict = _eval_guard(node.test, flags)
        tests.append((ast.unparse(node.test), verdict))
        if verdict is True:
            return node.body, tests
        if verdict is False:
            node = node.orelse
            continue
        return node, tests
    return node, tests


def _mixed_branch(tree, marker):
    """The mixed `if` branch carrying `marker` (batch construction vs accumulation)."""
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    candidates = [n for n in ast.walk(run_memory)
                  if isinstance(n, ast.If) and ast.unparse(n.test).strip() == "action_preservation_mixed"
                  and marker in ast.unparse(n)]
    assert len(candidates) == 1, (marker, [ast.unparse(n.test) for n in candidates])
    return run_memory, candidates[0]


def test_mixed_rng_call_arguments_are_wired():
    """The two halves must draw from different registered generators (B-F3 wiring).

    `test_registered_bijection_stream_survives_replay` proves the *order* is right; this
    test pins the *wiring*: the single-edge half relabels with `augmentation_rng` while
    the history half permutes with `history_augmentation_rng` (seed 2407), and the
    window sampler uses `window_rng` with the registered row count.
    """
    tree = ast.parse(WORKER.read_text())
    _, branch = _mixed_branch(tree, "relabel_batch(pool_batch")
    source = ast.unparse(branch).replace("'", '"')
    assert 'relabel_batch(pool_batch, augmentation_rng)' in source, source[:400]
    assert 'permute_symbols(sampler.sample(plan["history_rows"], window_rng), history_augmentation_rng)' \
        in source.replace("\n", " ").replace(", ", ", ").replace(" ,", ","), source[:400]
    assert "history_augmentation_rng" in source
    raw = WORKER.read_text()
    assert 'history_augmentation_rng = (' in raw and 'plan["seeds"]["mixed_history_augmentation"]' in raw
    plan = mw.action_preservation_mixed_memory_plan()
    assert plan["seeds"]["mixed_history_augmentation"] == 2407 != plan["seeds"]["augmentation"] == 2307
    # C02: structure of the history generator, not a name match
    assigns = [n for n in ast.walk(ast.parse(raw))
               if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "history_augmentation_rng"]
    assert len(assigns) == 1
    rhs = assigns[0].value
    assert isinstance(rhs, ast.IfExp)
    assert ast.unparse(rhs.test) == "action_preservation_mixed"
    assert ast.unparse(rhs.body).replace("'", '"') == \
        'np.random.default_rng(plan["seeds"]["mixed_history_augmentation"])'
    assert ast.unparse(rhs.orelse) == "None"


def test_mixed_rng_states_branch_is_selected_and_complete():
    """Review B08: the recorded rng_states for the mixed condition must be its own.

    The chain's first branch used to be taken for this condition, so the window and
    history-augmentation states were never recorded. Evaluating the IfExp chain under
    the mixed flag set (rather than matching text) closes the whole mutant family.
    """
    tree = ast.parse(WORKER.read_text())
    run_memory, _ = _mixed_branch(tree, "relabel_batch(pool_batch")
    chain = None
    for node in ast.walk(run_memory):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "rng_states":
                    chain = value
    assert isinstance(chain, ast.IfExp), ast.dump(chain)[:120] if chain else "rng_states missing"
    selected, tests = _select_ifexp(chain, FLAGS_MIXED)
    assert tests, "the chain must be evaluable under the mixed flags"
    keys = {k.value for k in selected.keys if isinstance(k, ast.Constant)}
    assert {"windows", "augmentation", "history_augmentation"} <= keys, sorted(keys)


def test_mixed_normalizes_exactly_once():
    """Review B-F2: the shared tail must not divide the already-normalized gradient.

    The mixed branch combines per-target means by row weight; the generic tail then
    divides by `target_count`. That second division shrank the registered objective,
    the logged `gradient_norm` and the effective `clip_grad_norm(1.0)` by exactly
    `target_count` (352 on real data). Mutant B03 re-introduces it silently.
    """
    tree = ast.parse(WORKER.read_text())
    run_memory, _ = _mixed_branch(tree, "mean_grads")
    tail = [n for n in ast.walk(run_memory)
            if isinstance(n, ast.Assign)
            and ast.unparse(n).startswith("gradients = tree_map(lambda g: g / target_count")]
    assert len(tail) == 1, [ast.unparse(n) for n in tail]
    line = tail[0].lineno
    guards = [n for n in ast.walk(run_memory)
              if isinstance(n, ast.If) and n.lineno < line
              and any(stmt is tail[0] for stmt in n.body)]
    assert len(guards) == 1, [ast.unparse(n.test) for n in guards]
    # exact structure, not a substring: `not action_preservation_mixed and False`
    # would keep the text but never run (reviewer mutant C01)
    assert ast.unparse(guards[0].test) == "not action_preservation_mixed", ast.unparse(guards[0].test)
    # and it must actually evaluate to False under the mixed flags, i.e. the
    # division is skipped for this condition
    assert _eval_guard(guards[0].test, FLAGS_MIXED) is False


def test_mixed_window_digest_and_telemetry_are_recorded():
    """Review B-F4/B06/B07: the window digest must cover both halves of the batch.

    The published telemetry logged only a row count, and a mutant that hashed only
    `symbols` (dropping `actions`) would have gone unnoticed.
    """
    tree = ast.parse(WORKER.read_text())
    run_memory, branch = _mixed_branch(tree, "relabel_batch(pool_batch")
    digest_calls = [n for n in ast.walk(branch)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "sha256"]
    assert digest_calls, "the mixed branch must digest the sampled windows"
    joined = ast.unparse(digest_calls[0])
    assert "symbols" in joined and "actions" in joined, joined
    # the telemetry dictionary must carry the real values, not just the key names
    telemetry = None
    for node in ast.walk(run_memory):
        if isinstance(node, ast.Assign) and "training_sample_rows" in ast.unparse(node.targets[0]) \
                and isinstance(node.value, ast.Dict):
            telemetry = node.value
    assert isinstance(telemetry, ast.Dict), "training_sample_rows dict assignment missing"
    values = {k.value: v for k, v in zip(telemetry.keys, telemetry.values)
              if isinstance(k, ast.Constant)}
    assert set(values) == {"single_edge_rows", "history_windows", "unused_schedule_rows",
                           "bijection_digests"}, sorted(values)
    # C04: the digests must be the produced list, not an empty alias
    assert ast.unparse(values["bijection_digests"]) == "bijection_digests"
    assert "bijection_digests = list(permutation_digests[: plan[\'single_edge_rows\']])" in \
        WORKER.read_text().replace('"', "'").replace("[: plan[", "[: plan[")
    window = values["history_windows"]
    assert isinstance(window, ast.Dict), ast.unparse(window)
    inner = {k.value: ast.unparse(v).replace("'", '"')
             for k, v in zip(window.keys, window.values) if isinstance(k, ast.Constant)}
    # C03: the window digest must be the recorded list, not a truncated slice
    assert inner["window_sha256"] == "window_digests", inner
    assert inner["count"] == 'plan["history_rows"]', inner
    assert inner["sampler_burn_in"] == 'plan["sampler_geometry"]["burn_in"]', inner
    assert inner["sampler_sequence_steps"] == 'plan["sampler_geometry"]["sequence_steps"]', inner
