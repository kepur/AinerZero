#!/usr/bin/env python3
"""S4 phase 2 exploration, round B (exploration only, not a result).

Two candidate fixes for the round-A findings, trained on the phase-1 training partition only
(s4p1-train) and evaluated on the round-A exploration worlds (s4x-p2a, 6 disks):
  Q  an error head on the frozen phase-1 L-int: per-coordinate log-variance of the model's own
     one-step error against the simulator, fitted on member states the filter actually produces
     (filter run with the same L-int on s4p1-train worlds); in the filter the process noise is the
     registered noise plus the learned error variance;
  R  a residual hybrid: the wall-and-pillar rule (E-B) plus a learned correction from the L-int
     network (messages included), trained exactly like phase-1 L-int (same pool, recipe, steps).

Subcommands (MLX; run under the shared lock):
  pool    N_WORLDS EVERY MEMBERS OUT.npz        filter-state pool from s4p1-train worlds 0..N-1
  trainq  POOL.npz STEPS OUTDIR                 error heads for L-int#1..3
  trainr  STEPS OUTDIR [SEEDS]                  residual hybrids on the phase-1 pool
  eval    N_WORLDS OUTDIR OUT.json              tracking and dynamics on s4x-p2a worlds
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import metrics as Me
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import explore_p2a as XA  # noqa: E402

WDIR = "artifacts/v9/s4/phase1/final-final/weights"
TRAIN_NS = "s4p1-train"
SEEDS = (1, 2, 3)


# --- E-B in MLX (same substeps and order as world.physics with disks=False) -----------------------
def eb_mlx(p, v, pil):
    h = W.DT / W.SUBSTEPS
    for _ in range(W.SUBSTEPS):
        p = p + v * h
        lo, hi = p < W.RADIUS, p > W.ARENA - W.RADIUS
        v = mx.where(lo, mx.abs(v), mx.where(hi, -mx.abs(v), v))
        p = mx.clip(p, W.RADIUS, W.ARENA - W.RADIUS)
        for k in range(L.N_PILLARS):
            ck, rk = pil[:, None, k, :2], pil[:, None, k, 2:3]
            dvec = p - ck
            dist = mx.sqrt((dvec ** 2).sum(-1, keepdims=True) + 1e-18)
            nrm = dvec / mx.maximum(dist, 1e-9)
            hit = dist < rk + W.RADIUS
            vn = (v * nrm).sum(-1, keepdims=True)
            back = hit & (vn < 0)
            v = mx.where(back, v - 2 * vn * nrm, v)
            p = mx.where(hit, ck + nrm * (rk + W.RADIUS), p)
    return p, v


_eb_compiled = mx.compile(eb_mlx)


def eb_train(p, v, pil):
    """E-B values with the gradient of constant velocity (exact away from walls and pillars); training
    through the E-B substeps directly is 4.5x slower per step (bench, round B)."""
    pe, ve = _eb_compiled(mx.stop_gradient(p), mx.stop_gradient(v), pil)
    return mx.stop_gradient(pe - (p + v * W.DT)) + p + v * W.DT, mx.stop_gradient(ve - v) + v


class Residual(L.Dynamics):
    def __init__(self):
        super().__init__("L-int")

    def __call__(self, p, v, pil):
        pe, ve = eb_train(p, v, pil)
        logits, scal, _ = self.messages(p, v)
        z = nn.relu(self.up2(nn.relu(self.up1(mx.concatenate([L.node_features(p, v, pil), scal], -1)))))
        o = self.out(z)
        return pe + o[..., 0:2] * L.P_SCALE, ve + o[..., 2:4], logits, None


class ResidualS(L.Dynamics):
    """The residual hybrid with an error head (log-variance of its own one-step error) on its frozen latent."""

    def __init__(self):
        super().__init__("L-int-s")

    def __call__(self, p, v, pil):
        pe, ve = eb_mlx(p, v, pil)
        logits, scal, _ = self.messages(p, v)
        z = nn.relu(self.up2(nn.relu(self.up1(mx.concatenate([L.node_features(p, v, pil), scal], -1)))))
        o = self.out(z)
        logvar = mx.clip(self.var2(nn.relu(self.var1(mx.stop_gradient(z)))), *L.LOGVAR_RANGE)
        return pe + o[..., 0:2] * L.P_SCALE, ve + o[..., 2:4], logits, logvar


def load_residual(path):
    m = Residual(); m.load_weights(path); mx.eval(m.parameters()); return m


def wrap(net, *, q_head=None, q_reg=(0.01, 0.05), q_cap=None):
    """Filter process model; with ``q_head`` (an L-int-s with this mean) returns registered + learned variances,
    the learned ones capped at ``q_cap`` = (position, velocity) variance if given."""
    def step(P, V, pillars):
        if P.shape[1] == 0:
            return (P.copy(), V.copy()) if q_head is None else (P.copy(), V.copy(), np.full_like(P, q_reg[0] ** 2), np.full_like(V, q_reg[1] ** 2))
        pil = mx.array(np.broadcast_to(np.array(pillars, dtype=np.float32), (P.shape[0], L.N_PILLARS, 3)))
        pp, vv = mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32))
        p, v, _, _ = net(pp, vv, pil)
        out = [np.array(p, dtype=np.float64), np.array(v, dtype=np.float64)]
        if q_head is not None:
            _, _, _, lv = q_head(pp, vv, pil)
            var = np.exp(np.array(lv, dtype=np.float64))
            vp, vv = var[..., 0:2], var[..., 2:4]
            if q_cap is not None:
                vp, vv = np.minimum(vp, q_cap[0]), np.minimum(vv, q_cap[1])
            out += [vp + q_reg[0] ** 2, vv + q_reg[1] ** 2]
        return tuple(out)
    return step


# --- subcommands ---------------------------------------------------------------------------------
def cmd_pool(n_worlds, every, members, out, net=None):
    mx.set_default_device(mx.cpu)
    net = net or L.as_process_model(L.load("L-int", f"{WDIR}/L-int#1.safetensors"))
    rows: dict[int, dict[str, list]] = {}
    t0 = time.time()
    for w in range(n_worlds):
        ep = W.generate_episode(TRAIN_NS, w, A.train_disks(TRAIN_NS, w))
        pick = np.random.default_rng(W.derive_seed("s4x-p2b", "pick", w))
        calls = [0]

        def model(P, V, pillars):
            o = net(P, V, pillars)
            calls[0] += 1
            if calls[0] % every == 0 and P.shape[1] >= 2:
                for m in pick.choice(P.shape[0], members, replace=False):
                    tp, tv, _ = W.physics(P[m:m + 1], V[m:m + 1], pillars)
                    d = rows.setdefault(P.shape[1], {"p": [], "v": [], "pil": [], "tp": [], "tv": []})
                    d["p"].append(P[m]); d["v"].append(V[m]); d["pil"].append(np.array(pillars)); d["tp"].append(tp[0]); d["tv"].append(tv[0])
            return o
        F.track(A.student_detections(ep), ep.pillars, model, np.random.default_rng(W.derive_seed("s4x-p2b", "filter", w)))
    flat = {f"{n}/{k}": np.stack(v).astype(np.float32) for n, d in rows.items() for k, v in d.items()}
    np.savez(out, **flat)
    print("pool", {n: len(d["p"]) for n, d in sorted(rows.items())}, f"{time.time() - t0:.0f}s")


def load_pool(path):
    z = np.load(path)
    by_n: dict[int, dict[str, np.ndarray]] = {}
    for key in z.files:
        n, k = key.split("/")
        by_n.setdefault(int(n), {})[k] = z[key]
    return L.Pool(dict(sorted(by_n.items())))


def cmd_trainq(pool_path, steps, outdir):
    pool = load_pool(pool_path)
    for s in SEEDS:
        mean = L.load("L-int", f"{WDIR}/L-int#{s}.safetensors")
        t0 = time.time()
        net, log = L.train("L-int-s", pool, steps=steps, batch=256, seed=s, mean_model=mean)
        L.save(net, f"{outdir}/Q#{s}.safetensors")
        print(f"Q#{s} {time.time() - t0:.0f}s loss {log[-1]}", flush=True)


def cmd_trainr(steps, outdir, seeds):
    t0 = time.time()
    eps = A.train_worlds(TRAIN_NS, A.N_TRAIN)
    pool = L.make_pool(eps, 240_000, np.random.default_rng(W.derive_seed(TRAIN_NS, "pool")), W.physics)
    print(f"pool {pool.size()} {time.time() - t0:.0f}s", flush=True)
    for s in seeds:
        t1 = time.time()
        mx.random.seed(s)
        model = Residual()
        mx.eval(model.parameters())
        opt = optim.Adam(learning_rate=1e-3)
        vg = nn.value_and_grad(model, L.rollout_loss)
        rng = np.random.default_rng(s)
        last = None
        for t, (n, idx) in enumerate(L.batches(pool, steps, 256, rng, coll_share=L.COLL_SHARE, near_share=L.NEAR_SHARE), 1):
            b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
            loss, grads = vg(model, b)
            grads, norm = optim.clip_grad_norm(grads, max_norm=L.CLIP)
            mx.eval(loss, norm)
            if not (np.isfinite(float(loss)) and np.isfinite(float(norm))):
                raise FloatingPointError(f"R#{s} non-finite at {t}")
            opt.update(model, grads)
            mx.eval(model.parameters(), opt.state)
            last = float(loss)
            if t % 2000 == 0:
                print(f"  R#{s} step {t} loss {last:.4f} {time.time() - t1:.0f}s", flush=True)
        model.save_weights(f"{outdir}/R#{s}.safetensors")
        print(f"R#{s} {time.time() - t1:.0f}s loss {last}", flush=True)


def cmd_trainqr(sdir, steps):
    """Error heads for the residual hybrids: member states from the filter run with R#s on s4p1-train worlds."""
    from mlx.utils import tree_flatten
    for s in SEEDS:
        cmd_pool(int(__import__("os").environ.get("P2B_POOL_WORLDS", "120")), 5, 4, f"{sdir}/poolR#{s}.npz", net=wrap(load_residual(f"{sdir}/R#{s}.safetensors")))
        mx.set_default_device(mx.gpu)
        pool = load_pool(f"{sdir}/poolR#{s}.npz")
        mean = load_residual(f"{sdir}/R#{s}.safetensors")
        mx.random.seed(s)
        model = ResidualS()
        model.load_weights(list(tree_flatten(mean.parameters())), strict=False)
        model.freeze(); model.var1.unfreeze(); model.var2.unfreeze()
        mx.eval(model.parameters())
        opt = optim.Adam(learning_rate=1e-3)
        vg = nn.value_and_grad(model, L.nll_loss)
        rng = np.random.default_rng(s)
        t0 = time.time()
        for t, (n, idx) in enumerate(L.batches(pool, steps, 256, rng), 1):
            b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
            loss, grads = vg(model, b)
            opt.update(model, grads)
            mx.eval(model.parameters(), opt.state)
        model.save_weights(f"{sdir}/QR#{s}.safetensors")
        print(f"QR#{s} {time.time() - t0:.0f}s loss {float(loss)}", flush=True)


def error_cap(mean_net, pool_path, q=99.9):
    """Per (position, velocity): the q-th percentile of the squared one-step error of ``mean_net`` on its pool."""
    pool = load_pool(pool_path)
    ep, ev = [], []
    for n, e in pool.by_n.items():
        for i in range(0, len(e["p"]), 2048):
            b = {k: mx.array(v[i:i + 2048]) for k, v in e.items()}
            p, v, _, _ = mean_net(b["p"], b["v"], b["pil"])
            ep.append((np.array(p) - e["tp"][i:i + 2048]).reshape(-1) ** 2)
            ev.append((np.array(v) - e["tv"][i:i + 2048]).reshape(-1) ** 2)
    return float(np.percentile(np.concatenate(ep), q)), float(np.percentile(np.concatenate(ev), q))


def safe_track(dets, pillars, model, rng, cfg, on_predict):
    """F.track, or None if the filter produced a non-finite cost (divergence)."""
    try:
        return F.track(dets, pillars, model, rng, cfg, on_predict=on_predict)
    except ValueError as e:
        if "finite" not in str(e):
            raise
        return None


def cmd_eval(n_worlds, outdir, out):
    mx.set_default_device(mx.cpu)
    nets = {s: L.load("L-int", f"{WDIR}/L-int#{s}.safetensors") for s in SEEDS}
    arms = {}
    import os
    if all(os.path.exists(f"{outdir}/Q#{s}.safetensors") for s in SEEDS):
        qs = {s: L.load("L-int-s", f"{outdir}/Q#{s}.safetensors") for s in SEEDS}
        arms["L-int+Q"] = {s: wrap(nets[s], q_head=qs[s]) for s in SEEDS}
        caps = {s: error_cap(nets[s], f"{outdir}/p2b-pool.npz") for s in SEEDS}
        print("caps L-int", caps, flush=True)
        arms["L-int+Qcap"] = {s: wrap(nets[s], q_head=qs[s], q_cap=caps[s]) for s in SEEDS}
    rs = [s for s in SEEDS if os.path.exists(f"{outdir}/R#{s}.safetensors")]
    if rs:
        R = {}
        for s in rs:
            m = Residual(); m.load_weights(f"{outdir}/R#{s}.safetensors"); mx.eval(m.parameters()); R[s] = m
        arms["L-int-r"] = {s: wrap(R[s]) for s in rs}
    res = {"arms": list(arms), "per_world": [], "dyn": {}}
    t0 = time.time()
    dyn = {}
    for w in range(n_worlds):
        ep = W.generate_episode(XA.NS, w, A.MAIN_DISKS)
        events = W.reappearances(ep)
        dets = A.student_detections(ep)
        rec = {"world": w, "events": [[e["k"], e["a"], e["b"], int(e["collision"])] for e in events], "cells": {}}
        for name, by_seed in arms.items():
            for s, model in by_seed.items():
                probe = XA.Probe(model)
                cal = XA.Calib(ep)
                rng = np.random.default_rng(W.derive_seed(XA.NS, "filter", w, s, "q1"))
                got = safe_track(dets, ep.pillars, probe, rng, F.FilterConfig(), cal)
                if got is None:
                    rec["cells"][f"{name}#{s}@q1"] = {"diverged": True}
                    continue
                ids, n_tracks = got
                b, sw = XA.breaks(ep, ids)
                rows = np.array(cal.rows, dtype=np.float64).reshape(-1, 5)
                calib = {}
                for kname, kk in (("all", None), ("collision", 0), ("graze", 1), ("free", 2)):
                    m = np.ones(len(rows), bool) if kk is None else rows[:, 0] == kk
                    calib[kname] = [int(m.sum()), float(rows[m, 1].sum()), float(rows[m, 2].sum()), float(rows[m, 3].sum()), float(rows[m, 4].sum())]
                rec["cells"][f"{name}#{s}@q1"] = {"correct": [x["correct"] for x in Me.reid(ep, ids, events)], "idf1": Me.idf1(ep, ids),
                                                   "n_tracks": n_tracks, "births": b, "swaps": sw, "calib": calib, "probe": probe.s}
                if name == "L-int-r":
                    e = Me.dynamics_errors(ep, model)
                    d = dyn.setdefault(f"{name}#{s}", [0.0, 0, 0.0, 0])
                    d[0] += sum(e["coll"]); d[1] += len(e["coll"]); d[2] += sum(e["graze"]); d[3] += len(e["graze"])
        for name, m in (("E-B", Mo.bounce), *((f"L-int#{s}", wrap(nets[s])) for s in SEEDS)):
            e = Me.dynamics_errors(ep, m)
            d = dyn.setdefault(name, [0.0, 0, 0.0, 0])
            d[0] += sum(e["coll"]); d[1] += len(e["coll"]); d[2] += sum(e["graze"]); d[3] += len(e["graze"])
        res["per_world"].append(rec)
        print(f"world {w} {time.time() - t0:.0f}s", flush=True)
    eb = dyn["E-B"][0] / dyn["E-B"][1]
    res["dyn"] = {k: {"D": 1 - (v[0] / v[1]) / eb, "HF": (v[2] / v[3]) / eb, "n_coll": v[1]} for k, v in dyn.items()}
    res["elapsed_s"] = time.time() - t0
    json.dump(res, open(out, "w"))
    print(json.dumps(res["dyn"], indent=1))


if __name__ == "__main__":
    c = sys.argv[1]
    if c == "pool":
        cmd_pool(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5])
    elif c == "trainq":
        cmd_trainq(sys.argv[2], int(sys.argv[3]), sys.argv[4])
    elif c == "trainr":
        cmd_trainr(int(sys.argv[2]), sys.argv[3], [int(x) for x in sys.argv[4].split(",")] if len(sys.argv) > 4 else list(SEEDS))
    elif c == "trainqr":
        cmd_trainqr(sys.argv[2], int(sys.argv[3]))
    elif c == "eval":
        cmd_eval(int(sys.argv[2]), sys.argv[3], sys.argv[4])
    else:
        raise SystemExit(__doc__)
