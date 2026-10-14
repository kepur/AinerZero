"""M2n-M4 (m2m_n_mixed_history_onestep_v1) CPU tests.

No MLX, no model, no worker, no RunStore write, no training. The numeric
gradient semantics are checked against a minimal pure-numpy reverse-mode tape
that is installed *as* ``mlx`` for the duration of a test, so
``memory_sequence_loss`` runs its real production code path while the real MLX
is never imported. Everything else (condition/plan identity, worker wiring,
identity gate, real mutations of production code) is checked statically or in a
temporary copy of the sources.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ainerzero import cli
from ainerzero.learning import action_preservation_closure as apc
from ainerzero.learning.one_step_memory import memory_sequence_loss
from ainerzero.runtime import memory_worker as mw

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "artifacts/reports/E27-onestep/onestep-identity.json"
REGISTRATION = ROOT / "artifacts/reports/relay-claude-20261014/M2NM4-onestep-registration.json"
CONFIG = ROOT / "configs" / "pilot.yaml"
MUTATION_TEST_FILE = "tests/test_action_preservation_onestep.py"


# --------------------------------------------------------------------------
# minimal numpy reverse-mode tape, installed as a fake ``mlx`` package
# --------------------------------------------------------------------------
class _T:
    __slots__ = ("v", "parents", "backward")

    def __init__(self, v, parents=(), backward=None):
        self.v = np.asarray(v, dtype=np.float32)
        self.parents = tuple(parents)
        self.backward = backward

    @property
    def shape(self):
        return self.v.shape

    def reshape(self, *shape):
        shape = shape[0] if len(shape) == 1 and isinstance(shape[0], (tuple, list)) else shape
        return _reshape(self, tuple(int(s) for s in shape))

    def astype(self, _dtype):
        return _T(self.v)

    def item(self):
        return float(self.v)

    def __getitem__(self, item):
        return _getitem(self, item)

    def __add__(self, other):
        return _add(self, other)

    def __radd__(self, other):
        return _add(other, self)

    def __mul__(self, other):
        return _mul(self, other)

    def __rmul__(self, other):
        return _mul(other, self)

    def __sub__(self, other):
        return _add(self, _mul(other, -1.0))

    def __truediv__(self, other):
        return _div(self, other)


def _wrap(x):
    return x if isinstance(x, _T) else _T(x)


def _val(x):
    return x.v if isinstance(x, _T) else np.asarray(x, dtype=np.float32)


def _unbroadcast(g, shape):
    g = np.asarray(g)
    while g.ndim > len(shape):
        g = g.sum(axis=0)
    for axis, size in enumerate(shape):
        if size == 1 and g.shape[axis] != 1:
            g = g.sum(axis=axis, keepdims=True)
    return g.reshape(shape)


def _add(a, b):
    a, b = _wrap(a), _wrap(b)
    out = a.v + b.v

    def back(g):
        return [_unbroadcast(g, a.v.shape), _unbroadcast(g, b.v.shape)]

    return _T(out, (a, b), back)


def _mul(a, b):
    a, b = _wrap(a), _wrap(b)
    out = a.v * b.v

    def back(g):
        return [_unbroadcast(g * b.v, a.v.shape), _unbroadcast(g * a.v, b.v.shape)]

    return _T(out, (a, b), back)


def _div(a, b):
    a, b = _wrap(a), _wrap(b)
    out = a.v / b.v

    def back(g):
        return [_unbroadcast(g / b.v, a.v.shape),
                _unbroadcast(-g * a.v / (b.v ** 2), b.v.shape)]

    return _T(out, (a, b), back)


def _exp(a):
    a = _wrap(a)
    out = np.exp(a.v)
    return _T(out, (a,), lambda g: [g * out])


def _log(a):
    a = _wrap(a)
    return _T(np.log(a.v), (a,), lambda g: [g / a.v])


def _sum(a, axis=None, keepdims=False):
    a = _wrap(a)
    out = a.v.sum(axis=axis, keepdims=keepdims)

    def back(g):
        g = np.asarray(g)
        if axis is None:
            return [np.broadcast_to(g, a.v.shape).copy()]
        if not keepdims:
            g = np.expand_dims(g, axis)
        return [np.broadcast_to(g, a.v.shape).copy()]

    return _T(out, (a,), back)


def _maximum(a, other):
    a = _wrap(a)
    out = np.maximum(a.v, _val(other))
    mask = (a.v >= _val(other)).astype(np.float32)
    return _T(out, (a,), lambda g: [g * mask])


def _reshape(a, shape):
    a = _wrap(a)
    return _T(a.v.reshape(shape), (a,), lambda g: [g.reshape(a.v.shape)])


def _getitem(a, item):
    a = _wrap(a)
    return _T(a.v[item], (a,), lambda g: [_scatter(a.v.shape, item, g)])


def _scatter(shape, item, g):
    out = np.zeros(shape, dtype=np.float32)
    out[item] = g
    return out


def _stack(items, axis=0):
    items = [_wrap(i) for i in items]
    out = np.stack([i.v for i in items], axis=axis)

    def back(g):
        return [np.take(g, index, axis=axis) for index in range(len(items))]

    return _T(out, items, back)


def _where(cond, a, b):
    cond = np.asarray(cond)
    a, b = _wrap(a), _wrap(b)
    out = np.where(cond, a.v, b.v)
    mask = cond.astype(np.float32)

    def back(g):
        return [_unbroadcast(g * mask, a.v.shape), _unbroadcast(g * (1.0 - mask), b.v.shape)]

    return _T(out, (a, b), back)


def _zeros_like(a):
    a = _wrap(a)
    return _T(np.zeros_like(a.v))


def _take_along_axis(a, index, axis):
    a = _wrap(a)
    index = np.asarray(index)
    out = np.take_along_axis(a.v, index, axis=axis)

    def back(g):
        grad = np.zeros_like(a.v)
        np.put_along_axis(grad, index, g, axis=axis)
        return [grad]

    return _T(out, (a,), back)


def _cross_entropy(logits, labels):
    """nn.losses.cross_entropy: per-cell CE with a numerically stable shift."""
    logits = _wrap(logits)
    labels = np.asarray(_val(labels)).astype(np.int64)
    shift = logits.v.max(axis=-1, keepdims=True)
    shifted = _add(logits, -shift)
    logsumexp = _add(shift, _log(_sum(_exp(shifted), axis=-1, keepdims=True)))
    picked = _take_along_axis(logits, labels[..., None], -1)
    return _add(logsumexp, _mul(picked, -1.0)).reshape(labels.shape)


def _backward(loss, params):
    order, seen = [], set()

    def visit(node):
        if id(node) in seen:
            return
        seen.add(id(node))
        for parent in node.parents:
            visit(parent)
        order.append(node)

    visit(loss)
    grads = {id(loss): np.ones_like(loss.v)}
    for node in reversed(order):
        grad = grads.get(id(node))
        if grad is None or node.backward is None:
            continue
        for parent, contribution in zip(node.parents, node.backward(grad)):
            if contribution is None:
                continue
            grads[id(parent)] = grads.get(id(parent), 0.0) + contribution
    return {name: np.asarray(grads.get(id(node), np.zeros_like(node.v)), dtype=np.float64)
            for name, node in params.items()}


class _FakeRandom:
    @staticmethod
    def split(key, num):
        return [key] * num

    @staticmethod
    def key(seed):
        return seed


class _FakeMX:
    float32 = np.float32
    bool_ = np.bool_

    random = _FakeRandom()

    @staticmethod
    def array(value):
        return _wrap(value)

    @staticmethod
    def ones(shape, dtype=None):
        return np.ones(shape, dtype=dtype or np.float32)

    @staticmethod
    def zeros_like(value):
        return _zeros_like(value)

    @staticmethod
    def where(cond, a, b):
        return _where(cond, a, b)

    @staticmethod
    def stack(items, axis=0):
        return _stack(list(items), axis=axis)

    @staticmethod
    def sum(value, axis=None, keepdims=False):
        return _sum(value, axis=axis, keepdims=keepdims)

    @staticmethod
    def maximum(value, other):
        return _maximum(value, other)

    @staticmethod
    def stop_gradient(value):
        value = _wrap(value)
        return _T(value.v)  # identity forward, no parents: the gradient path is cut


class _FakeNN:
    class losses:
        cross_entropy = staticmethod(_cross_entropy)


class fake_mlx:  # noqa: N801 - stands in for the ``mlx`` package
    """Context manager that installs a numpy tape as ``mlx`` (and restores it)."""

    def __enter__(self):
        import types

        self._saved = {name: sys.modules.get(name) for name in ("mlx", "mlx.core", "mlx.nn")}
        core = types.ModuleType("mlx.core")
        core.__dict__.update({name: getattr(_FakeMX, name) for name in dir(_FakeMX)
                              if not name.startswith("_")})
        core.float32, core.bool_ = np.float32, np.bool_
        nn = types.ModuleType("mlx.nn")
        nn.losses = _FakeNN.losses
        package = types.ModuleType("mlx")
        package.core, package.nn = core, nn
        sys.modules["mlx"], sys.modules["mlx.core"], sys.modules["mlx.nn"] = package, core, nn
        return core

    def __exit__(self, *_exc):
        for name, module in self._saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        return False


class _StepModel:
    """Deterministic fake student: step t's transition uses its own scalar parameter.

    ``imagine`` at step t uses ``p_t``; ``observe`` carries the state forward without
    parameters. The readout of a loss step therefore depends on p_0..p_t, so the
    gradient of one loss term to an earlier step's parameter is only reachable
    through the recurrent chain -- exactly what the truncation must cut.
    """

    def __init__(self, steps, size=1):
        self.steps = steps
        self.size = size
        self.step = 0
        self.p = {t: _T(np.full((size, 256), 0.05 * (t + 1), dtype=np.float32)) for t in range(steps)}

    def params(self):
        return {f"p{t}": node for t, node in self.p.items()}

    def initial(self, size):
        return (_T(np.full((size, 256), 0.02, dtype=np.float32)),
                _T(np.full((size, 256), 0.01, dtype=np.float32)))

    def observe(self, h, symbols, visible_mask, cursor, *, key=None):
        h = _wrap(h)
        drive = np.asarray(symbols, dtype=np.float32).sum(axis=1, keepdims=True)
        moved = _mul(h, 0.5)
        return {"h": _add(moved, drive / 10.0), "z": _mul(moved, 0.25)}

    def imagine(self, h, z, action, *, key=None):
        h = _wrap(h)
        out = _add(_mul(h, 0.5), self.p[self.step])
        self.step += 1
        return {"h": out, "z": _mul(out, 0.25)}

    def symbol_readout(self, x):
        x = _wrap(x)  # (size, 8, 16)
        weights = np.arange(1, 17, dtype=np.float32).reshape(1, 1, 16)
        base = _sum(_mul(x, weights), axis=-1, keepdims=True)  # (size, 8, 1)
        classes = np.arange(256, dtype=np.float32).reshape(1, 1, 256)
        return _add(_mul(base, 1.0), _mul(classes, 1e-3))


def _batch(steps=12, burn_in=4, size=1, only_step=None):
    rng = np.random.default_rng(4)
    symbols = rng.integers(0, 8, size=(size, steps + 1, 8)).astype(np.int32)
    visible = np.ones((size, steps + 1, 8), dtype=bool)
    if only_step is not None:
        visible[:, :only_step] = False
        visible[:, only_step + 1 :] = False
        visible[:, only_step] = True
    return {
        "symbols": symbols,
        "visible_mask": visible,
        "cursor": np.ones((size, steps + 1), dtype=np.int32),
        "actions": np.zeros((size, steps), dtype=np.int32),
        "episode_start": np.zeros((size, steps + 1), dtype=np.int32),
    }


def _loss_grads(*, truncate, only_step=None, steps=12, burn_in=4):
    model = _StepModel(steps)
    batch = _batch(steps=steps, burn_in=burn_in, only_step=only_step)
    with fake_mlx():
        loss, metrics = memory_sequence_loss(
            model, batch, burn_in=burn_in, key=0, truncate_each_step=truncate
        )
        grads = _backward(loss, model.params())
    return float(loss.v), float(metrics["visible_targets"].v), grads


# --------------------------------------------------------------------------
# 1. numeric semantics of the truncation
# --------------------------------------------------------------------------
def test_truncation_stops_gradient_to_earlier_loss_steps():
    steps, burn_in = 12, 4
    for step in range(burn_in + 1, steps):
        _loss, _targets, grads = _loss_grads(truncate=True, only_step=step)
        for name, grad in grads.items():
            index = int(name[1:])
            norm = float(np.abs(grad).sum())
            if index == step:
                assert norm > 0.0, f"loss step {step} must keep its own gradient"
            else:
                assert norm == 0.0, (
                    f"truncated history half: loss step {step} leaked {norm} into {name}"
                )


def test_untruncated_default_keeps_multi_step_gradients():
    steps = 12
    step = steps - 1
    _loss, _targets, grads = _loss_grads(truncate=False, only_step=step)
    earlier = [name for name in grads if int(name[1:]) < step]
    assert earlier, "the untruncated baseline must see earlier steps"
    assert any(float(np.abs(grads[name]).sum()) > 0.0 for name in earlier), (
        "the default path must propagate the last loss term into earlier transitions"
    )


def test_truncation_leaves_the_forward_pass_bitwise_identical():
    truncated_loss, truncated_targets, truncated_grads = _loss_grads(truncate=True)
    default_loss, default_targets, default_grads = _loss_grads(truncate=False)
    assert truncated_loss == default_loss
    assert truncated_targets == default_targets
    for step in range(5, 12):
        t_loss, _, _ = _loss_grads(truncate=True, only_step=step)
        d_loss, _, _ = _loss_grads(truncate=False, only_step=step)
        assert t_loss == d_loss, f"forward value of loss step {step} changed"
    # The backward graph must differ, or the flag would be a no-op.
    assert any(float(np.abs(truncated_grads[k] - default_grads[k]).sum()) > 0.0
               for k in truncated_grads)


def test_default_is_bitwise_identical_to_the_previous_implementation():
    steps, burn_in = 12, 4
    model = _StepModel(steps)
    batch = _batch(steps=steps, burn_in=burn_in)
    with fake_mlx():
        new_loss, _ = memory_sequence_loss(model, batch, burn_in=burn_in, key=0)
        new_grads = _backward(new_loss, model.params())
    legacy_model = _StepModel(steps)
    with fake_mlx():
        legacy_loss = _legacy_memory_sequence_loss(legacy_model, batch, burn_in=burn_in, key=0)
        legacy_grads = _backward(legacy_loss, legacy_model.params())
    assert float(new_loss.v) == float(legacy_loss.v)
    for name in new_grads:
        assert np.array_equal(new_grads[name], legacy_grads[name]), name


def _legacy_memory_sequence_loss(model, batch, *, burn_in, key):
    """The pre-M2n-M4 body: detach once, exactly at ``t == burn_in``."""
    import mlx.core as mx
    import mlx.nn as nn

    actions = batch["actions"]
    size, steps = actions.shape
    valid = batch.get("valid_mask")
    if valid is None:
        valid = mx.ones(actions.shape, dtype=mx.bool_)
    keys = mx.random.split(key, num=2 * steps + 1)
    h, _ = model.initial(size)
    state = model.observe(h, batch["symbols"][:, 0], batch["visible_mask"][:, 0],
                          batch["cursor"][:, 0], key=keys[0])
    errors, masks = [], []
    for t in range(steps):
        h, z = state["h"], state["z"]
        if t == burn_in:
            h, z = mx.stop_gradient(h), mx.stop_gradient(z)
        imagined = model.imagine(h, z, actions[:, t], key=keys[2 * t + 1])
        starts = batch["episode_start"][:, t + 1]
        next_h = mx.where(valid[:, t, None], imagined["h"], h)
        next_h = mx.where(starts[:, None], mx.zeros_like(h), next_h)
        posterior = model.observe(next_h, batch["symbols"][:, t + 1],
                                  batch["visible_mask"][:, t + 1],
                                  batch["cursor"][:, t + 1], key=keys[2 * t + 2])
        if t >= burn_in:
            logits = model.symbol_readout(posterior["h"][:, 128:].reshape(size, 8, 16))
            path_valid = valid[:, t] & ~starts
            visible = batch["visible_mask"][:, t] & path_valid[:, None]
            labels = mx.where(visible, batch["symbols"][:, t], 0)
            errors.append(nn.losses.cross_entropy(logits, labels))
            masks.append(visible.astype(mx.float32))
        state = posterior
    weights = mx.stack(masks, axis=1)
    count = mx.sum(weights)
    return mx.sum(mx.stack(errors, axis=1) * weights) / mx.maximum(count, 1)


def test_flag_rejects_truthy_non_bool():
    model = _StepModel(12)
    with fake_mlx():
        for bad in (1, 0, "yes", None):
            with pytest.raises(ValueError, match="truncate_each_step must be a bool"):
                memory_sequence_loss(model, _batch(), burn_in=4, key=0, truncate_each_step=bad)


def test_production_modules_do_not_import_mlx_at_import_time():
    """The CPU test run must not pull in MLX; the numeric tests use the numpy tape only."""
    program = (
        "import sys; sys.path.insert(0, 'src');"
        "import ainerzero.cli, ainerzero.runtime.memory_worker,"
        " ainerzero.learning.action_preservation_closure, ainerzero.learning.one_step_memory;"
        "print(sorted(m for m in sys.modules if m == 'mlx' or m.startswith('mlx.')))"
    )
    result = subprocess.run([sys.executable, "-c", program], cwd=ROOT,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "[]", result.stdout


# --------------------------------------------------------------------------
# 2. condition plan: only protocol/digest/registration/factor fields differ
# --------------------------------------------------------------------------
ONESTEP_ALLOWED_CONDITION_DIFF = {
    "protocol", "mixed_protocol", "condition_sha256", "mixed_condition_sha256",
    "design_registration_sha256", "single_factor", "history_weight",
    "renormalize_after_scaling", "truncate_each_step", "backward", "start",
}


def test_onestep_condition_differs_from_e24_only_in_the_registered_fields():
    plan = apc.mixed_onestep_condition_plan()
    base = apc.mixed_condition_plan()
    changed = {key for key in set(plan) | set(base) if plan.get(key) != base.get(key)}
    assert changed <= ONESTEP_ALLOWED_CONDITION_DIFF, changed - ONESTEP_ALLOWED_CONDITION_DIFF
    assert changed >= {"protocol", "condition_sha256", "design_registration_sha256", "single_factor"}
    # The objective itself is E24's, untouched.
    assert plan["normalization"] == base["normalization"]
    assert plan["units"] == base["units"]
    assert plan["seconds"] == base["seconds"]
    assert plan["windows"] == base["windows"]
    assert plan["batch"] == base["batch"]
    assert plan["keep_branch"] == base["keep_branch"]
    assert plan["history_weight"] == 1.0
    assert plan["truncate_each_step"] is True
    assert plan["mixed_protocol"] == apc.MIXED_PROTOCOL
    assert plan["mixed_condition_sha256"] == base["condition_sha256"] == (
        "dd02c4fe58059d5c505705e35afa97042bbde2af3923239ca7b7caa6f470a4f2")


def test_design_digest_is_bound_to_the_registration_bytes():
    plan = apc.mixed_onestep_condition_plan()
    assert plan["design_registration_sha256"] == hashlib.sha256(REGISTRATION.read_bytes()).hexdigest()
    assert plan["design_registration_sha256"] == apc.ONESTEP_DESIGN_REGISTRATION_SHA256
    assert plan["design_registration_sha256"].startswith("fa3a37e2")


def test_earlier_conditions_and_digests_are_unchanged():
    assert apc.mixed_condition_plan()["condition_sha256"] == (
        "dd02c4fe58059d5c505705e35afa97042bbde2af3923239ca7b7caa6f470a4f2")
    assert apc.mixed_weight025_condition_plan()["condition_sha256"] == (
        "6e98299668221d0ba970198b1af662ba5c2a1b4c9dd0f29ccb56ce0ed06041d0")
    assert apc.mixed_weight0_control_condition_plan()["condition_sha256"] == (
        "e7666014e8e2fe0299491f7c8611a20018d306866d9294c6aa2bd18c2cedae6d")
    assert "truncate_each_step" not in apc.mixed_condition_plan()
    assert "truncate_each_step" not in apc.mixed_weight025_condition_plan()
    assert "truncate_each_step" not in apc.mixed_weight0_control_condition_plan()


def test_worker_plan_keeps_the_registered_budget_and_geometry():
    plan = mw.action_preservation_mixed_onestep_memory_plan()
    e24 = mw.action_preservation_mixed_memory_plan()
    assert plan["protocol"] == apc.ONESTEP_PROTOCOL
    assert plan["truncate_each_step"] is True
    assert plan["history_weight"] == 1.0
    assert (plan["single_edge_rows"], plan["history_rows"]) == (12, 4)
    assert plan["training_model_units_per_update"] == 152
    assert plan["expected_total_model_units"] == 202_304
    assert (plan["total_reserved_seconds_if_complete"], plan["supervised_deadline_seconds"],
            plan["supervisor_deadline_seconds"]) == (1_740, 1_760, 1_780)
    changed = {k for k in set(plan) | set(e24) if plan.get(k) != e24.get(k)}
    assert changed <= {"protocol", "history_weight", "renormalize_after_scaling",
                       "truncate_each_step", "action_preservation_condition"}, changed
    assert plan["seeds"] == e24["seeds"]
    assert plan["sampler_geometry"] == e24["sampler_geometry"]


# --------------------------------------------------------------------------
# 3. worker wiring: only the history half may be truncated
# --------------------------------------------------------------------------
def _worker_ast():
    return ast.parse((ROOT / "src/ainerzero/runtime/memory_worker.py").read_text())


def test_worker_truncates_only_the_history_half():
    calls = [node for node in ast.walk(_worker_ast())
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "value_grad"
             and any(kw.arg == "truncate_each_step" for kw in node.keywords)]
    assert len(calls) == 1, f"expected exactly one truncated value_grad call, found {len(calls)}"
    keyword = {kw.arg: kw.value for kw in calls[0].keywords}.get("truncate_each_step")
    assert keyword is not None, "the training call must pass truncate_each_step explicitly"
    assert isinstance(keyword, ast.BoolOp) and isinstance(keyword.op, ast.And), ast.dump(keyword)
    comparisons = [value for value in keyword.values if isinstance(value, ast.Compare)]
    assert len(comparisons) == 1, "the history half must be selected explicitly"
    compare = comparisons[0]
    assert isinstance(compare.comparators[0], ast.Constant) and compare.comparators[0].value == "history"
    assert isinstance(compare.left, ast.Name) and compare.left.id == "name"
    assert any(isinstance(value, ast.Name) and value.id == "truncate_history"
               for value in keyword.values)


def test_worker_truncate_flag_requires_the_onestep_entry_and_the_plan_key():
    assignments = [node for node in ast.walk(_worker_ast())
                   if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "truncate_history" for t in node.targets)]
    assert len(assignments) == 1, "truncate_history must be assigned exactly once"
    value = assignments[0].value
    assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "bool"
    argument = value.args[0]
    assert isinstance(argument, ast.BoolOp) and isinstance(argument.op, ast.And), ast.dump(argument)
    names = {node.id for node in ast.walk(argument) if isinstance(node, ast.Name)}
    assert "action_preservation_mixed_onestep" in names
    literals = {node.value for node in ast.walk(argument) if isinstance(node, ast.Constant)}
    assert "truncate_each_step" in literals and False in literals
    signature = [node for node in ast.walk(_worker_ast()) if isinstance(node, ast.arguments)]
    declared = [argument.arg for node in signature for argument in node.args + node.kwonlyargs]
    assert "action_preservation_mixed_onestep" in declared


def test_mlx_wrapper_forwards_the_flag_to_both_passes():
    source = (ROOT / "src/ainerzero/learning/action_preservation_mlx.py").read_text()
    assert source.count("truncate_each_step=truncate_each_step") == 2
    assert "def memory_distill_sequence_loss(student, teacher, batch: Mapping, *, burn_in: int, key, lam: float," in source
    assert "if type(truncate_each_step) is not bool:" in source


def test_one_step_memory_keeps_one_detach_at_the_boundary_by_default():
    source = (ROOT / "src/ainerzero/learning/one_step_memory.py").read_text()
    assert "if t == burn_in or (truncate_each_step and t > burn_in):" in source
    assert "def memory_sequence_loss(model, batch: dict, *, burn_in: int = 4, key,\n" in source
    assert "truncate_each_step: bool = False)" in source


# --------------------------------------------------------------------------
# 4. CLI entry: exclusive, no scientific knobs, fail-closed identity gate
# --------------------------------------------------------------------------
COMMAND = "train-action-preserved-mixed-onestep-memory"
REQUIRED = ["--dataset", "d", "--checkpoint", "c", "--comparison-report", "r", "--m2l-report", "m",
            "--m2l-checkpoint", "k", "--m2mc-report", "x", "--experiment-id", "e"]


def test_cli_entry_is_separate_and_takes_no_scientific_knobs(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "train_pilot_command", lambda args: seen.update(vars(args)) or {"status": "completed"})
    assert cli.main([COMMAND, *REQUIRED]) == 0
    assert seen["action_preserved_mixed_onestep_training"] is True
    assert seen.get("action_preserved_mixed_training", False) is False
    assert seen.get("action_preserved_mixed_weight025_training", False) is False
    assert seen.get("action_preserved_mixed_weight0_control_training", False) is False
    assert not any(key in seen for key in ("learning_rate", "history_weight", "history_rows", "keep_lambda"))
    for flag in ("--learning-rate", "--history-weight", "--lambda", "--updates"):
        with pytest.raises(SystemExit):
            cli.main([COMMAND, *REQUIRED, flag, "1.0"])


def test_dispatch_uses_the_new_flag_and_the_registered_timeout(monkeypatch, tmp_path):
    captured = {}

    class Done:
        returncode, stdout, stderr = 1, "", ""

    monkeypatch.setattr(cli, "verify_onestep_identity", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "project_root", lambda _path: tmp_path)
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda cmd, **kwargs: captured.update(cmd=cmd, timeout=kwargs["timeout"]) or Done())
    cli.train_pilot_command(_args(tmp_path))
    assert "--action-preservation-mixed-onestep" in captured["cmd"]
    assert "--action-preservation-mixed" not in captured["cmd"]
    assert captured["timeout"] == min(1780, cli.load_pilot_config(CONFIG).budget.max_wall_seconds)


def _args(tmp_path, **flags):
    from types import SimpleNamespace

    base = dict(
        config=CONFIG, output_dir=tmp_path, experiment_id="e", dataset=tmp_path / "d",
        checkpoint=tmp_path / "c", comparison_report=tmp_path / "r", m2l_report=tmp_path / "m",
        m2l_checkpoint=tmp_path / "k", m2mc_report=tmp_path / "x",
        action_preserved_mixed_onestep_training=True,
        action_preserved_mixed_training=False,
        action_preserved_memory_training=False,
        action_preservation_probe=False,
        action_preserved_lambda10_training=False,
        action_preserved_distill_training=False,
        action_preserved_history_training=False,
        action_preserved_mixed_weight025_training=False,
        action_preserved_mixed_weight0_control_training=False,
    )
    base.update(flags)
    return SimpleNamespace(**base)


def test_entry_is_exclusive_with_every_other_action_command(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("worker launched")

    monkeypatch.setattr(cli.subprocess, "run", boom)
    for conflict in ({"action_preserved_mixed_training": True},
                     {"action_preserved_mixed_weight025_training": True},
                     {"action_preserved_mixed_weight0_control_training": True},
                     {"action_preserved_distill_training": True}):
        report = cli.train_pilot_command(_args(tmp_path, **conflict))
        assert report["status"] == "failed" and report["fail_closed"] is True


def _live_record(root=ROOT):
    plan = apc.mixed_onestep_condition_plan()
    return {
        "protocol": apc.ONESTEP_PROTOCOL,
        "condition_sha256": plan["condition_sha256"],
        "design_registration_sha256": plan["design_registration_sha256"],
        "config_hash": cli.pilot_config_hash(cli.load_pilot_config(root / "configs/pilot.yaml")),
        "files": {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest()
                  for rel in sorted(cli.ONESTEP_REQUIRED_FILES)},
    }


def test_identity_gate_accepts_the_live_record_and_has_no_exemption():
    record = _live_record()
    cli.verify_onestep_identity(ROOT, record, config_path=CONFIG)
    for rel in sorted(cli.ONESTEP_REQUIRED_FILES):
        bad = json.loads(json.dumps(record))
        bad["files"][rel] = "ab" * 32
        with pytest.raises(RuntimeError, match="identity mismatch") as excinfo:
            cli.verify_onestep_identity(ROOT, bad, config_path=CONFIG)
        assert rel in str(excinfo.value)
    empty = json.loads(json.dumps(record))
    empty["files"] = {}
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_onestep_identity(ROOT, empty, config_path=CONFIG)
    dropped = json.loads(json.dumps(record))
    dropped["files"].pop("src/ainerzero/learning/one_step_memory.py")
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_onestep_identity(ROOT, dropped, config_path=CONFIG)
    for field in ("protocol", "condition_sha256", "design_registration_sha256", "config_hash", "files"):
        missing = json.loads(json.dumps(record))
        missing.pop(field)
        with pytest.raises(RuntimeError, match=f"missing {field}"):
            cli.verify_onestep_identity(ROOT, missing, config_path=CONFIG)
    wrong = json.loads(json.dumps(record))
    wrong["protocol"] = apc.MIXED_PROTOCOL
    with pytest.raises(RuntimeError, match="protocol"):
        cli.verify_onestep_identity(ROOT, wrong, config_path=CONFIG)
    drifted = json.loads(json.dumps(record))
    drifted["condition_sha256"] = "cd" * 32
    with pytest.raises(RuntimeError, match="condition_sha256"):
        cli.verify_onestep_identity(ROOT, drifted, config_path=CONFIG)


def test_identity_gate_rejects_the_live_protocol_when_the_sources_drift(monkeypatch, tmp_path):
    """The shipped identity file is a freeze for the M2n-M4 sources: it must accept the
    live tree while they agree, and fail closed for the worker launch path."""
    cli.verify_onestep_identity(ROOT, config_path=CONFIG)

    def boom(*args, **kwargs):
        raise AssertionError("worker launched")

    monkeypatch.setattr(cli.subprocess, "run", boom)
    monkeypatch.setattr(cli, "verify_onestep_identity",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            RuntimeError("onestep identity mismatch: src/ainerzero/cli.py")))
    report = cli.train_pilot_command(_args(tmp_path))
    assert report["status"] == "failed" and report["fail_closed"] is True
    assert "identity mismatch" in report["error"]


def test_identity_file_is_frozen_and_not_authorized():
    record = json.loads(IDENTITY.read_text())
    assert record["protocol"] == apc.ONESTEP_PROTOCOL
    assert record["status"] == "identity_frozen_run_not_authorized"
    assert record["run_authorized"] is False
    assert set(record["files"]) == set(cli.ONESTEP_REQUIRED_FILES)
    assert record["files"] == _live_record()["files"]
    assert record["condition_sha256"] == apc.mixed_onestep_condition_plan()["condition_sha256"]
    assert record["design_registration_sha256"] == hashlib.sha256(REGISTRATION.read_bytes()).hexdigest()


def test_old_identity_files_are_untouched():
    for rel, expected in (("artifacts/reports/E25-weighted/weight025-identity.json", "e30504d25b711f0d"),
                          ("artifacts/reports/E26-weight0/weight0-identity.json", "bea2df343d5d0f9d")):
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest().startswith(expected), rel


# --------------------------------------------------------------------------
# 5. real mutations of production code, in a throwaway copy, must be caught
# --------------------------------------------------------------------------
MUTATIONS = {
    "truncate_only_once": (
        "src/ainerzero/learning/one_step_memory.py",
        "        if t == burn_in or (truncate_each_step and t > burn_in):",
        "        if t == burn_in:",
        "test_truncation_stops_gradient_to_earlier_loss_steps",
    ),
    "skip_forward_after_burn_in": (
        "src/ainerzero/learning/one_step_memory.py",
        "        imagined = model.imagine(h, z, actions[:, t], key=keys[2 * t + 1])",
        "        if truncate_each_step and t > burn_in:\n"
        "            state = posterior if False else state\n"
        "            continue\n"
        "        imagined = model.imagine(h, z, actions[:, t], key=keys[2 * t + 1])",
        "test_truncation_leaves_the_forward_pass_bitwise_identical",
    ),
    "truncate_both_halves": (
        "src/ainerzero/runtime/memory_worker.py",
        "                            truncate_each_step=(truncate_history and name == \"history\"),",
        "                            truncate_each_step=truncate_history,",
        "test_worker_truncates_only_the_history_half",
    ),
    "identity_gate_exemption": (
        "src/ainerzero/cli.py",
        "    if not isinstance(files, dict) or set(files) != set(ONESTEP_REQUIRED_FILES):",
        "    if not isinstance(files, dict) or not set(files) <= set(ONESTEP_REQUIRED_FILES):",
        "test_identity_gate_accepts_the_live_record_and_has_no_exemption",
    ),
}

COPY_PATHS = ("src", "configs", "pyproject.toml",
              "artifacts/reports/relay-claude-20261014/M2NM4-onestep-registration.json")


def _copy_tree(destination: Path) -> Path:
    for rel in COPY_PATHS:
        source = ROOT / rel
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    (destination / "artifacts/reports/E27-onestep").mkdir(parents=True, exist_ok=True)
    shutil.copy2(IDENTITY, destination / "artifacts/reports/E27-onestep/onestep-identity.json")
    (destination / "tests").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / MUTATION_TEST_FILE, destination / MUTATION_TEST_FILE)
    return destination


def _run_copy_test(destination: Path, test_name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", f"{MUTATION_TEST_FILE}::{test_name}", "-q",
         "-p", "no:cacheprovider", "--no-header"],
        cwd=destination,
        env={"PYTHONPATH": str(destination / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=600,
    )


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_real_mutation_of_production_code_is_caught(name, tmp_path):
    relative, original, mutated, test_name = MUTATIONS[name]
    destination = _copy_tree(tmp_path / "repo")
    path = destination / relative
    text = path.read_text()
    assert text.count(original) == 1, f"mutation anchor drifted in {relative}"
    path.write_text(text.replace(original, mutated))

    baseline = _run_copy_test(destination, test_name)
    assert baseline.returncode != 0, f"mutation {name} was not caught:\n{baseline.stdout[-2000:]}"


def test_unmutated_copy_passes_the_same_tests(tmp_path):
    destination = _copy_tree(tmp_path / "repo")
    for name in sorted(MUTATIONS):
        result = _run_copy_test(destination, MUTATIONS[name][3])
        assert result.returncode == 0, f"{name}: {result.stdout[-2000:]}"
