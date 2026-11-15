#!/usr/bin/env python3
"""S6 phase 1 cells: one (arm, replicate) of pool-based active learning. DESIGN-r2 §2, §3, §6.

A cell builds the replicate's candidate pool, then runs ROUNDS rounds: reveal the picked experiments,
train the learners on everything revealed so far, save the weights, and (except after the last round)
pick the next experiments. Outcomes exist only for revealed samples (``sandbox.CandidatePool`` simulates
them on reveal), and picking runs inside ``sealed()``: the simulator, world generation, pool building and
the pool's reveal raise while it is open, so a pick rule cannot obtain an outcome even by accident.

Training runs on the GPU; scoring for selection and evaluation run on the CPU (as the exploration).
Each learner owns its randomness (numpy batches, and for the epinet an MLX key chain), so a single
learner can be retrained alone in another process from the saved picks (DESIGN-r1 §6 training check).

Evaluation is separate from training (the runner evaluates saved weights in one pass), so training
never touches a test partition.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s6 import epinet_mlx as E
from ainerzero.v9.experiments.s6 import sandbox as S

ARMS = ("R", "E", "Z", "T", "P", "G")
REPLICATES = {"R": 5, "E": 5, "Z": 5, "T": 5, "P": 5, "G": 3}
N_LEARNERS = 3
LR = 1e-3
BATCH = 256
T_COLL_SHARE = 0.5
KINDS = ("collision", "graze", "wall_pillar", "free")


@dataclass(frozen=True)
class Sizes:
    per: int = 3000           # experiments added per round
    rounds: int = 4
    steps: int = 2500         # training steps per learner per round
    pool: int = 60_000        # distinct candidate states per replicate
    cand_worlds: int = 240    # candidate worlds per replicate (240 x 300 steps = 72000 states to draw from)


FULL = Sizes()


class SealBreach(RuntimeError):
    """A pick rule reached the simulator, world generation or the label door."""


# --- seeds ---------------------------------------------------------------------------------------------
def net_seeds(k: int) -> tuple[int, int, int]:
    return (3 * k + 1, 3 * k + 2, 3 * k + 3)


def pool_seed(cand_ns: str, k: int) -> int:
    return W.derive_seed(cand_ns, "s6-pool", k)


def first_seed(cand_ns: str, k: int) -> int:
    return W.derive_seed(cand_ns, "s6-first", k)


def pick_seed(cand_ns: str, arm: str, k: int) -> int:
    """T picks exactly what R picks (it differs only in how it batches what it has); others have their own."""
    return W.derive_seed(cand_ns, "s6-pick", "R" if arm == "T" else arm, k)


# --- candidate states ------------------------------------------------------------------------------------
def candidate_worlds(cand_ns: str, k: int, sizes: Sizes = FULL) -> list[W.Episode]:
    lo = k * sizes.cand_worlds
    return [W.generate_episode(cand_ns, w, A.train_disks(cand_ns, w)) for w in range(lo, lo + sizes.cand_worlds)]


def candidate_source(cand_ns: str, k: int, sizes: Sizes = FULL) -> dict[int, dict[str, np.ndarray]]:
    """The candidate states of replicate k (DESIGN-r2 §2): ``sizes.pool`` distinct (world, step) pairs drawn
    without replacement from the replicate's candidate worlds, as exact float64 states with their pillars,
    grouped by disk count and sorted by (world, step). No outcome is computed here; the episodes (whose
    steps carry contact logs) are dropped before returning."""
    eps = candidate_worlds(cand_ns, k, sizes)
    pairs = [(e, t) for e, ep in enumerate(eps) for t in range(len(ep.steps))]
    if sizes.pool > len(pairs):
        raise ValueError(f"only {len(pairs)} states in {len(eps)} worlds, {sizes.pool} wanted")
    pick = np.random.default_rng(pool_seed(cand_ns, k)).choice(len(pairs), sizes.pool, replace=False)
    chosen = sorted((eps[pairs[i][0]].n_disks, pairs[i][0], pairs[i][1]) for i in pick)
    by_n: dict[int, dict[str, list]] = {}
    for n, e, t in chosen:
        s = eps[e].steps[t]
        row = by_n.setdefault(n, {"p": [], "v": [], "pil": []})
        row["p"].append(np.asarray(s.positions, dtype=np.float64))
        row["v"].append(np.asarray(s.velocities, dtype=np.float64))
        row["pil"].append(np.asarray(eps[e].pillars, dtype=np.float64))
    del eps
    out = {n: {k_: np.stack(v) for k_, v in d.items()} for n, d in sorted(by_n.items())}
    for n, d in out.items():
        flat = np.concatenate([d["p"].reshape(len(d["p"]), -1), d["v"].reshape(len(d["v"]), -1), d["pil"].reshape(len(d["pil"]), -1)], 1)
        if len(np.unique(flat, axis=0)) != len(flat):
            raise AssertionError(f"duplicate candidate states with {n} disks")
    return out


def n_states(source: dict) -> int:
    return sum(len(e["p"]) for e in source.values())


def make_candidate_pool(source: dict) -> S.CandidatePool:
    return S.CandidatePool(source, labeller=S.sim_labels, pool_type=L.Pool)


def pool_digest(source: dict) -> str:
    h = hashlib.sha256()
    for n in sorted(source):
        for key in sorted(source[n]):
            a = np.ascontiguousarray(source[n][key])
            h.update(f"{n}:{key}:{a.dtype}:{a.shape}".encode()); h.update(a.tobytes())
    return h.hexdigest()


# --- the seal --------------------------------------------------------------------------------------------
_SEALED = [(W, "physics"), (W, "generate_episode"), (L, "make_pool"), (L, "make_sigma_pool"),
           (A, "train_worlds"), (Mo, "true_physics"), (Mo, "bounce"), (S, "sim_labels"),
           (S.CandidatePool, "_simulate"), (S.CandidatePool, "reveal")]


@contextmanager
def sealed():
    """While open, the simulator, world generation, pool building and the pool's label door raise."""
    saved = [(obj, name, getattr(obj, name)) for obj, name in _SEALED if hasattr(obj, name)]

    def trap(name):
        def _raise(*a, **k):
            raise SealBreach(f"a pick rule reached {name} while selection was sealed")
        return _raise

    for obj, name, _ in saved:
        setattr(obj, name, trap(f"{getattr(obj, '__name__', obj)}.{name}"))
    try:
        yield
    finally:
        for obj, name, f in saved:
            setattr(obj, name, f)


# --- learners --------------------------------------------------------------------------------------------
class NetLearner:
    """L-int from scratch (DESIGN-r1 §3); optimizer and batch generator persist across rounds."""

    def __init__(self, seed: int):
        self.seed = seed
        mx.random.seed(seed)
        self.model = L.Dynamics("L-int")
        mx.eval(self.model.parameters())
        self.opt = optim.Adam(learning_rate=LR)
        self.vg = nn.value_and_grad(self.model, L.rollout_loss)
        self.rng = np.random.default_rng(seed)

    def train(self, pool: L.Pool, steps: int, coll_share: float = 0.0) -> None:
        for n, idx in L.batches(pool, steps, BATCH, self.rng, coll_share=coll_share):
            b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
            loss, grads = self.vg(self.model, b)
            grads, norm = optim.clip_grad_norm(grads, max_norm=L.CLIP)
            self.opt.update(self.model, grads)
            mx.eval(self.model.parameters(), self.opt.state, loss, norm)
            if not (math.isfinite(float(loss.item())) and math.isfinite(float(norm.item()))):
                raise FloatingPointError(f"non-finite loss or gradient (seed {self.seed})")


class EpiLearner:
    """L-int + epinet, decoupled (s6/epinet_mlx.py total_loss, clip_parts); its own MLX key chain for z."""

    def __init__(self, seed: int):
        self.seed = seed
        mx.random.seed(seed)
        self.model = E.EpiDynamics()
        mx.eval(self.model.parameters())
        self.opt = optim.Adam(learning_rate=LR)
        self.vg = nn.value_and_grad(self.model, E.total_loss)
        self.rng = np.random.default_rng(seed)
        self.key = mx.random.key(seed)

    def train(self, pool: L.Pool, steps: int, coll_share: float = 0.0) -> None:
        if coll_share:
            raise ValueError("the epinet arm uses uniform batches")
        for n, idx in L.batches(pool, steps, BATCH, self.rng, coll_share=0.0):
            b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
            self.key, sub = mx.random.split(self.key)
            z = mx.random.normal((len(idx), E.DZ), key=sub)
            loss, grads = self.vg(self.model, b, z)
            grads, norm = E.clip_parts(grads)
            self.opt.update(self.model, grads)
            mx.eval(self.model.parameters(), self.opt.state, loss, norm)
            if not (math.isfinite(float(loss.item())) and math.isfinite(float(norm.item()))):
                raise FloatingPointError(f"non-finite loss or gradient (seed {self.seed})")
        self.model.z = None


def make_learner(arm: str, seed: int):
    return EpiLearner(seed) if arm == "P" else NetLearner(seed)


def load_model(arm: str, path: str | Path):
    if arm == "P":
        m = E.EpiDynamics()
        m.load_weights(str(path))
        m.z = None
    else:
        m = L.Dynamics("L-int")
        m.load_weights(str(path))
    mx.eval(m.parameters())
    return m


# --- scores (states only) ---------------------------------------------------------------------------------
def _per_id(states: dict, per_bucket: dict[int, np.ndarray]) -> np.ndarray:
    total = sum(len(e["id"]) for e in states.values())
    out = np.full(total, np.nan)
    for n, e in states.items():
        out[e["id"]] = per_bucket[n]
    return out


def disagreement(states: dict, models: list) -> np.ndarray:
    """E: mean over networks of |v_net - v_mean| per disk, max over disks; by global id."""
    per = {}
    for n, e in states.items():
        p, v, pil = mx.array(e["p"]), mx.array(e["v"]), mx.array(e["pil"])
        preds = []
        for m in models:
            _, vv, _, _ = m(p, v, pil)
            preds.append(np.array(vv, dtype=np.float64))
        st = np.stack(preds)
        per[n] = np.linalg.norm(st - st.mean(0)[None], axis=-1).mean(0).max(-1)
    return _per_id(states, per)


def epinet_spread(states: dict, model) -> np.ndarray:
    """P: the epinet index spread (epinet_mlx.spread) per disk, max over disks; by global id."""
    per = {n: E.spread(model, {"p": e["p"], "v": e["v"], "pil": e["pil"]}).max(-1) for n, e in states.items()}
    return _per_id(states, per)


def closest_pair(states: dict) -> np.ndarray:
    """Z: minus the smallest centre distance between two disks; by global id. Reads p only."""
    per = {}
    for n, e in states.items():
        p = np.asarray(e["p"], dtype=np.float64)
        d = np.linalg.norm(p[:, :, None] - p[:, None], axis=-1) + np.eye(p.shape[1])[None] * 1e9
        per[n] = -d.min((1, 2))
    return _per_id(states, per)


def score_digest(score: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(score, dtype=np.float64).tobytes()).hexdigest()


# --- one cell -------------------------------------------------------------------------------------------------
@dataclass
class Track:
    """One selection stream: a candidate pool object, its learners and its picks."""
    cp: S.CandidatePool
    learners: list
    picks: list[list[int]] = field(default_factory=list)
    digests: list[str | None] = field(default_factory=list)


def select(arm: str, track: Track, k: int, per: int, cand_ns: str, rng: np.random.Generator | None) -> tuple[np.ndarray, str | None]:
    """The next ``per`` picks of one track. Runs sealed, on the CPU; returns (ids, score digest or None)."""
    prev = mx.default_device()
    mx.set_default_device(mx.cpu)
    try:
        with sealed():
            st = track.cp.states()
            rem = track.cp.remaining()
            if arm in ("R", "T"):
                return S.pick_random(rem, per, rng), None
            if arm == "G":
                return S.pick_geo(S.geo_flags(st), rem, per, rng), None
            if arm == "E":
                score = disagreement(st, [l.model for l in track.learners])
            elif arm == "Z":
                score = closest_pair(st)
            elif arm == "P":
                score = epinet_spread(st, track.learners[0].model)
            else:
                raise ValueError(f"unknown arm {arm!r}")
            return S.pick_top(score, rem, per), score_digest(score)
    finally:
        mx.set_default_device(prev)


def run_cell(arm: str, k: int, source: dict, out: Path, *, cand_ns: str, sizes: Sizes = FULL,
             say: Callable[..., None] = lambda *a: None, check_time: Callable[[], None] = lambda: None) -> dict:
    """Run one (arm, replicate) cell into ``out`` (must not exist). Returns the cell record (also written
    to out/cell.json last, with the SHA of every file)."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}")
    if not 0 <= k < REPLICATES[arm]:
        raise ValueError(f"arm {arm} has no replicate {k}")
    out.mkdir(parents=True)
    t0 = time.time()
    seeds = net_seeds(k)
    mx.set_default_device(mx.gpu)
    if arm == "P":     # three single-network learners, each with its own picks
        tracks = [Track(make_candidate_pool(source), [make_learner(arm, s)]) for s in seeds]
    else:              # three networks sharing one selection
        tracks = [Track(make_candidate_pool(source), [make_learner(arm, s) for s in seeds])]
    first = S.pick_random(tracks[0].cp.remaining(), sizes.per, np.random.default_rng(first_seed(cand_ns, k)))
    pick_rngs = [np.random.default_rng(pick_seed(cand_ns, arm, k)) for _ in tracks]
    for tr in tracks:
        tr.picks.append(first.tolist()); tr.digests.append(None)
    timings = []
    for r in range(sizes.rounds):
        check_time()
        tr_t = time.time()
        for ti, tr in enumerate(tracks):
            tr.cp.reveal(np.array(tr.picks[r], dtype=np.int64))
            pool = tr.cp.revealed_pool()
            for li, lr in enumerate(tr.learners):
                lr.train(pool, sizes.steps, T_COLL_SHARE if arm == "T" else 0.0)
                j = ti if arm == "P" else li
                lr.model.save_weights(str(out / f"r{r}-n{j}.safetensors"))
        train_s = time.time() - tr_t
        sel_t = time.time()
        if r < sizes.rounds - 1:
            for ti, tr in enumerate(tracks):
                ids, dig = select(arm, tr, k, sizes.per, cand_ns, pick_rngs[ti])
                tr.picks.append(ids.tolist()); tr.digests.append(dig)
        timings.append({"round": r, "train_s": round(train_s, 2), "select_s": round(time.time() - sel_t, 2)})
        say(f"{arm} r{k} round {r} train {train_s:.0f}s")
    files = sorted(p.name for p in out.iterdir())
    rec = {
        "schema": "s6.phase1.cell.v1", "arm": arm, "replicate": k, "cand_ns": cand_ns, "sizes": sizes.__dict__,
        "net_seeds": list(seeds), "first_seed": first_seed(cand_ns, k), "pick_seed": pick_seed(cand_ns, arm, k),
        "pool_seed": pool_seed(cand_ns, k), "pool_sha256": pool_digest(source),
        "tracks": [{"picks": tr.picks, "score_sha256": tr.digests, "reveal_log": tr.cp.log(),
                    "revealed": tr.cp.revealed_ids().tolist()} for tr in tracks],
        "timings": timings, "seconds": round(time.time() - t0, 1),
        "files_sha256": {f: hashlib.sha256((out / f).read_bytes()).hexdigest() for f in files},
    }
    check_cell_record(rec, sizes)
    tmp = out / "cell.json.tmp"
    tmp.write_text(json.dumps(rec, sort_keys=True), encoding="utf-8")
    tmp.rename(out / "cell.json")
    return rec


def check_cell_record(rec: dict, sizes: Sizes = FULL) -> None:
    """The label-isolation and completeness checks a finished cell must pass (DESIGN-r1 §6 ①, completeness)."""
    arm = rec["arm"]
    want_tracks = N_LEARNERS if arm == "P" else 1
    if len(rec["tracks"]) != want_tracks:
        raise AssertionError(f"{arm}: {len(rec['tracks'])} tracks")
    for tr in rec["tracks"]:
        picks, log = tr["picks"], tr["reveal_log"]
        if len(picks) != sizes.rounds or any(len(p) != sizes.per for p in picks):
            raise AssertionError("picks per round do not match the budget")
        if [e["ids"] for e in log] != picks or [e["call"] for e in log] != list(range(sizes.rounds)):
            raise AssertionError("the reveal log differs from the picks: something other than the picks was revealed")
        flat = [i for p in picks for i in p]
        if len(set(flat)) != len(flat) or tr["revealed"] != flat:
            raise AssertionError("a sample was picked twice or the revealed set differs from the picks")
    names = {f"r{r}-n{j}.safetensors" for r in range(sizes.rounds) for j in range(N_LEARNERS)}
    if set(rec["files_sha256"]) != names:
        raise AssertionError(f"weights on disk differ from the expected {len(names)} files")


def verify_cell_dir(out: Path, sizes: Sizes = FULL) -> dict:
    """Read a finished cell: record present, checks pass, every file has its recorded SHA."""
    rec = json.loads((out / "cell.json").read_text(encoding="utf-8"))
    check_cell_record(rec, sizes)
    for f, want in rec["files_sha256"].items():
        if hashlib.sha256((out / f).read_bytes()).hexdigest() != want:
            raise AssertionError(f"{out.name}/{f} changed after the cell finished")
    return rec


# --- evaluation (separate from training) ----------------------------------------------------------------
def classify(ep: W.Episode, t: int) -> np.ndarray:
    """Step kind per disk at step t: 0 disk collision, 1 graze, 2 wall or pillar, 3 free (as S6 exploration)."""
    s = ep.steps[t]
    disk = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
    wallp = {i for k, i, j in s.contacts if k in ("wall", "pillar")}
    nxt = ep.steps[t + 1].positions
    d = np.linalg.norm(nxt[:, None] - nxt[None], axis=-1) + np.eye(ep.n_disks) * 99
    return np.array([0 if i in disk else (1 if d[i].min() < 2 * W.RADIUS + 0.3 else (2 if i in wallp else 3))
                     for i in range(ep.n_disks)])


@dataclass(frozen=True)
class TestWorld:
    P: np.ndarray
    V: np.ndarray
    target: np.ndarray
    kinds: np.ndarray
    eb_err: np.ndarray
    pil: np.ndarray


def prepare_world(ep: W.Episode) -> TestWorld:
    T = len(ep.steps) - 1
    P = np.stack([s.positions for s in ep.steps[:T]]).astype(np.float32)
    V = np.stack([s.velocities for s in ep.steps[:T]]).astype(np.float32)
    tgt = np.stack([s.velocities for s in ep.steps[1:T + 1]])
    kinds = np.stack([classify(ep, t) for t in range(T)])
    _, vb = Mo.bounce(P.astype(np.float64), V.astype(np.float64), ep.pillars)
    pil = np.broadcast_to(np.array(ep.pillars, dtype=np.float32), (T, L.N_PILLARS, 3)).copy()
    return TestWorld(P, V, tgt, kinds, np.linalg.norm(vb - tgt, axis=-1), pil)


def world_counts(tw: TestWorld) -> tuple[np.ndarray, float]:
    """(counts [4] of disk-steps per kind, E-B error sum on collision disk-steps)."""
    return np.array([(tw.kinds == c).sum() for c in range(4)], dtype=np.int64), float(tw.eb_err[tw.kinds == 0].sum())


def world_sums(model, tw: TestWorld) -> np.ndarray:
    """[4] next-velocity error sums per kind for one model on one test world (CPU)."""
    _, v, _, _ = model(mx.array(tw.P), mx.array(tw.V), mx.array(tw.pil))
    e = np.linalg.norm(np.array(v, dtype=np.float64) - tw.target, axis=-1)
    return np.array([e[tw.kinds == c].sum() for c in range(4)])
