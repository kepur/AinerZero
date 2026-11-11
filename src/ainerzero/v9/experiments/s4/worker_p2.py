"""S4 phase 2 evaluation worker (MLX on CPU). Runs in a spawned process; never generates worlds.

``build_models(weights)`` loads the phase-1 L-int and L-ind of each seed and builds every tracked
model: the hand arms, ungated L-int and the gated arms (analysis_p2.ARM_SPEC: gate and response),
plus separate copies for the dynamics sums (no gate counters). Stochastic arms are reseeded per pass
by analysis_p2. ``init`` keeps them per process; ``evaluate_world(task)``
returns the record of one world (analysis_p2.world_record) and, on main worlds, the k-step position
errors of L-int-g and E-B from the exact truth.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

import mlx.core as mx

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import analysis_p2 as P2
from ainerzero.v9.experiments.s4 import gated as G
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import models as Mo

_MODELS: dict[str, Callable] = {}
_COUNTERS: dict[str, list] = {}
_DYN: dict[str, Callable] = {}


def weight_names() -> list[str]:
    return [f"{arm}#{s}" for s in P2.SEEDS for arm in ("L-int", "L-ind")]


def build_models(weights: Mapping[str, str]) -> tuple[dict[str, Callable], dict[str, list], dict[str, Callable]]:
    if sorted(weights) != sorted(weight_names()):
        raise ValueError(f"expected weights {weight_names()}, got {sorted(weights)}")
    nets = {name: L.load(name.split("#")[0], path) for name, path in weights.items()}
    models: dict[str, Callable] = {a: Mo.HAND_MODELS[a] for a in P2.HAND}
    counters: dict[str, list] = {}
    dyn: dict[str, Callable] = {"E-B": Mo.bounce}
    for s in P2.SEEDS:
        lint = nets[f"L-int#{s}"]
        models[f"L-int#{s}"] = dyn[f"L-int#{s}"] = L.as_process_model(lint)
        for arm, (base_name, gate, response) in P2.ARM_SPEC.items():
            base = nets[f"{base_name}#{s}"]
            c = [0, 0]
            counters[f"{arm}#{s}"] = c
            models[f"{arm}#{s}"] = G.gated_model(base, gate, response=response, counter=c)
            dyn[f"{arm}#{s}"] = G.gated_model(base, gate, response=response)
    return models, counters, dyn


def init(weights: Mapping[str, str]) -> None:
    mx.set_default_device(mx.cpu)
    models, counters, dyn = build_models(weights)
    _MODELS.clear(); _COUNTERS.clear(); _DYN.clear()
    _MODELS.update(models); _COUNTERS.update(counters); _DYN.update(dyn)


def evaluate_world(task: Mapping[str, Any]) -> dict[str, Any]:
    ep = task["episode"]
    rec = P2.world_record(ep, task["kind"], task["ns"], _MODELS, counters=_COUNTERS, dyn_models=_DYN)
    if task["kind"] == "main":
        rec["kstep"] = {"E-B": A.kstep_sums(ep, Mo.bounce)} | {f"{P2.MAIN_ARM}#{s}": A.kstep_sums(ep, _DYN[f"{P2.MAIN_ARM}#{s}"]) for s in P2.SEEDS}
    return rec
