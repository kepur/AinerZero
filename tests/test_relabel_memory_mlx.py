"""Tiny CPU MLX smoke check that relabeled pool rows feed the real student shapes."""

import mlx.core as mx
import mlx.nn as nn
import numpy as np
import pytest
from test_coverage_diagnostic import make_pool

from ainerzero.core.pilot import PilotConfig
from ainerzero.learning.diverse_memory import get_diverse_batch
from ainerzero.learning.one_step_memory import memory_sequence_loss
from ainerzero.learning.paired_memory import evaluate_zero_context_inputs
from ainerzero.learning.pilot_model import SharedSymbolPredictor
from ainerzero.learning.relabel_memory import relabel_batch

pytestmark = pytest.mark.native_mlx(reason="module-level real MLX import (A39)")


@pytest.fixture(autouse=True)
def cpu_only():
    previous = mx.default_device()
    mx.set_default_device(mx.cpu)
    yield
    mx.set_default_device(previous)


def test_relabeled_batch_trains_and_scores_with_real_student_shapes():
    model = SharedSymbolPredictor(PilotConfig().model, key=mx.random.key(0))
    model.freeze()
    model.gru.unfreeze()
    batch, _ = relabel_batch(get_diverse_batch(make_pool(), 0), np.random.default_rng(2307))
    data = {name: mx.array(values[:4]) for name, values in batch.items()}
    (loss, metrics), grads = nn.value_and_grad(model, memory_sequence_loss)(
        model, data, burn_in=0, key=mx.random.key(2203)
    )
    mx.eval(loss, metrics, grads)
    assert np.isfinite(float(loss.item()))
    assert float(metrics["visible_targets"].item()) == 32
    calls = []
    scored = evaluate_zero_context_inputs(
        model,
        {name: values[:2] for name, values in batch.items()},
        [[1, 2, 3], [4, 5, 6]],
        before_work=calls.append,
    )
    assert calls == [8] * 4 and scored["logical_model_transitions"] == 32
    assert scored["argmax"].shape == (2, 8) and np.isfinite(scored["nll"]).all()
