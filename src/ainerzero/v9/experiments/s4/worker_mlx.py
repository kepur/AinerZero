"""S4 phase 1 evaluation worker (MLX on CPU). Runs in a spawned process; never generates worlds.

``init(weights, refs)`` loads every learned cell from its weights file once per process;
``evaluate_world(task)`` returns the record of one world (analysis.world_record) plus the
descriptive sums that need the learned models: contact head counts, k-step errors, errors from
perturbed inputs, L-int-σ calibration sums and the filter-level calibration of each base cell.
"""

from __future__ import annotations

from typing import Any, Mapping

import mlx.core as mx
import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

_MODELS: dict[str, Any] = {}
_NETS: dict[str, L.Dynamics] = {}
_REFS: dict[int, dict] = {}
CALIB_EVERY = 2


def base_arm(name: str) -> str:
    """Architecture of a learned cell name such as L-int-e8#2."""
    arm = name.split("#")[0]
    return arm[:-3] if arm.endswith("-e8") else arm


def init(weights: Mapping[str, str], refs: Mapping[int, dict]) -> None:
    mx.set_default_device(mx.cpu)
    _MODELS.clear(); _NETS.clear(); _REFS.clear()
    _MODELS.update(Mo.HAND_MODELS)
    for name, path in weights.items():
        net = L.load(base_arm(name), path)
        _NETS[name] = net
        _MODELS[name] = L.as_process_model(net, with_variance=base_arm(name) == "L-int-s")
    _REFS.update({int(k): v for k, v in refs.items()})


def _logits_fn(net: L.Dynamics):
    def f(P, V, pillars):
        pil = mx.array(np.broadcast_to(np.array(pillars, dtype=np.float32), (P.shape[0], L.N_PILLARS, 3)))
        _, _, lg, _ = net(mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32)), pil)
        return np.array(lg, dtype=np.float64)
    return f


def evaluate_world(task: Mapping[str, Any]) -> dict[str, Any]:
    ep: W.Episode = task["episode"]
    kind, ns = task["kind"], task["ns"]
    cells = [A.Cell(*c) for c in task["cells"]]
    seeds = A.SEEDS
    rec = A.world_record(ep, kind, ns, cells, _MODELS)
    desc: dict[str, Any] = {}
    mean_names = [n for n in _NETS if base_arm(n) in L.MEAN_ARMS]
    # filter-level calibration of the base cells (a second pass with the read-only hook)
    fc = {}
    for c in cells:
        if c.variant != "base" or c.arm == "S-P":
            continue
        hook = A.FilterCalibration(ep)
        model = _MODELS.get(f"{c.arm}#{c.seed}", _MODELS.get(c.arm))
        rng = np.random.default_rng(A.filter_seed(ns, ep.world_index, c.seed, c.variant))
        ids, _ = F.track(A.student_detections(ep), ep.pillars, model, rng, A.variant_config(c.variant), on_predict=hook)
        if A.ids_digest(ids) != rec["ids_sha256"][c.key]:
            raise RuntimeError(f"the calibration hook changed the tracking of {c.key}")
        fc[c.key] = hook.sums()
    desc["filter_calibration"] = fc
    desc["contact"] = {n: A.contact_counts(ep, _logits_fn(_NETS[n])) for n in mean_names if base_arm(n) != "L-ind"}
    if kind == "main":
        ks = {name: A.kstep_sums(ep, m) for name, m in Mo.HAND_MODELS.items()}
        ks.update({n: A.kstep_sums(ep, _MODELS[n]) for n in mean_names})
        desc["kstep"] = ks
        pert_models = {"E-B": Mo.bounce, "E-P": Mo.true_physics} | {n: _MODELS[n] for n in mean_names}
        desc["perturbed"] = A.perturbed_dyn_sums(ep, pert_models, L.perturb, np.random.default_rng(W.derive_seed(ns, "perturb", ep.world_index)))
    sig = [f"L-int-s#{s}" for s in seeds if f"L-int-s#{s}" in _MODELS]
    desc["calibration"] = {}
    for n in sig:
        s = int(n.split("#")[1])
        rows = A.calib_rows(ep, _MODELS[n], np.random.default_rng(W.derive_seed(ns, "calib", ep.world_index, s)), every=CALIB_EVERY)
        desc["calibration"][n] = A.calibration_sums(rows, _REFS[s])
    rec["descriptive"] = desc
    return rec
