"""S4 phase 1 evaluation (DESIGN-r3 §4-§6). Pure CPU, NumPy only; process models are callables.

- partitions and world lists;
- one record per evaluation world: reappearance events, the dynamics sums of every model from
  the exact truth, and per tracking cell the correctness of every event, IDF1 and a digest of the
  track ids;
- aggregation over seeds and worlds, the gates HD, HF, HD-x, H1, H2, H3, the negative control and
  the legality gates on floors and sample counts.

A tracking cell is (arm, seed, variant). Learned arm seed s is the model trained with seed s;
every arm, hand-made ones included, is tracked with the filter seed of (world, s, variant), and an
event's correctness is averaged over the three seeds before summing per world.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import metrics as Me
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

NAMESPACES = {"train": "s4p1-train", "probe": "s4p1-probe", "final": "s4p1-final"}
N_TRAIN = 400
TRAIN_DISKS = (4, 8)
MAIN_DISKS, EXTRAP_DISKS = 6, 10
EXTRAP_OFFSET = 1000
SIZES = {"probe": (50, 25), "final": (200, 100)}         # (main, extrapolation) worlds
SEEDS = (1, 2, 3)
EXPECTED_COLL_EVENTS_PER_40 = 261
EXPECTED_COLL_DISK_STEPS_PER_40 = 552
SAMPLE_BAND = 0.25
DYN_FLOOR = 0.75
NOISE_SCALES = (0.25, 4.0)                              # besides the registered 1x
GATE_VARIANTS = {"tight": (0.4, 1.0), "loose": (0.8, 2.0)}  # (gate_base, gate_grow) besides the registered one
GATE_ARMS = ("E-B", "E-P", "L-int")                     # arms tracked in the noise and gate variants
N_COMPARISONS = 7                                       # HD, HF, HD-x (D and HF), H1, H2, H3

THRESHOLDS = {
    "HD": {"D": 0.8, "D_low": 0.7},
    "HF": {"ratio": 0.10, "ratio_high": 0.15},
    "HD-x": {"D": 0.7, "D_low": 0.6, "ratio": 0.15},
    "H1": {"C": 0.5, "C_low": 0.25},
    "H2": {"diff": 0.05, "diff_low": 0.0},
    "H3": {"C": 0.4, "C_low": 0.2},
    "negative_control": {"D_low_below": 0.5, "C_low_below": 0.25},
}


# --- partitions ----------------------------------------------------------------------------------
def train_disks(ns: str, w: int) -> int:
    lo, hi = TRAIN_DISKS
    return lo + W.derive_seed(ns, "disks", w) % (hi - lo + 1)


def train_worlds(ns: str, n: int) -> list[W.Episode]:
    return [W.generate_episode(ns, w, train_disks(ns, w)) for w in range(n)]


def eval_world_ids(stage_sizes: tuple[int, int]) -> list[tuple[str, int, int]]:
    """(kind, world index, disks) for the main and the extrapolation worlds."""
    n_main, n_ext = stage_sizes
    return [("main", w, MAIN_DISKS) for w in range(n_main)] + [("extrap", EXTRAP_OFFSET + w, EXTRAP_DISKS) for w in range(n_ext)]


def filter_seed(ns: str, w: int, seed: int, variant: str) -> int:
    return W.derive_seed(ns, "filter", w, seed, variant)


# --- tracking cells --------------------------------------------------------------------------------
@dataclass(frozen=True)
class Cell:
    arm: str
    seed: int
    variant: str = "base"                 # base, q0.25, q4, gate-tight, gate-loose

    @property
    def key(self) -> str:
        return f"{self.arm}#{self.seed}@{self.variant}"


def variant_config(variant: str) -> F.FilterConfig:
    base = F.FilterConfig()
    if variant == "base":
        return base
    if variant.startswith("q"):
        s = float(variant[1:])
        return replace(base, q_pos=base.q_pos * s, q_vel=base.q_vel * s)
    if variant.startswith("gate-"):
        g, k = GATE_VARIANTS[variant[5:]]
        return replace(base, gate_base=g, gate_grow=k)
    raise ValueError(f"unknown variant {variant!r}")


def variants() -> list[str]:
    return ["base"] + [f"q{s:g}" for s in NOISE_SCALES] + [f"gate-{k}" for k in GATE_VARIANTS]


def plan_cells(learned_arms: Sequence[str]) -> list[Cell]:
    """Every arm at the registered filter over three seeds, plus the S-P diagnostic; E-B, E-P, S-P
    and L-int also at the noise and gate variants."""
    cells = []
    for arm in ("E-CV", "E-B", "E-P", "S-P", *learned_arms):
        cells += [Cell(arm, s) for s in SEEDS]
    for v in variants()[1:]:
        for arm in (*GATE_ARMS, "S-P"):
            cells += [Cell(arm, s, v) for s in SEEDS]
    return cells


def ids_digest(ids: Sequence[np.ndarray]) -> str:
    return hashlib.sha256(json.dumps([np.asarray(i).tolist() for i in ids]).encode()).hexdigest()


def student_detections(ep: W.Episode) -> list[np.ndarray]:
    """What every student tracker reads: the detections of the student view, step by step."""
    views = [W.student_view(s) for s in ep.steps]
    if any(set(v) != W.STUDENT_KEYS for v in views):
        raise RuntimeError("the student view has fields outside the whitelist")
    return [v["detections"] for v in views]


def future_mutation(dets: Sequence[np.ndarray], cut: int) -> list[np.ndarray]:
    """The legality check's future-frame mutation: after the cut every step loses its last
    detection and the rest move by 0.5."""
    return [d if t <= cut else d[:-1] + 0.5 for t, d in enumerate(dets)]


def mutation_row(a: Sequence[np.ndarray], b: Sequence[np.ndarray], mut: Sequence[np.ndarray], cut: int) -> dict[str, bool]:
    """Compare the ids of the unmutated run ``a`` with those of the mutated run ``b``.

    prefix_equal: no id up to the cut changes; consumed: the tracker returned one id per mutated
    detection; suffix_changed: after the cut some id differs on the detections both runs share
    (an aligned prefix, so a tracker that reads only the lengths of the new lists cannot pass by
    the length difference alone)."""
    return {"prefix_equal": all(np.array_equal(x, y) for x, y in zip(a[: cut + 1], b[: cut + 1])),
            "consumed": len(b) == len(mut) and all(len(y) == len(d) for y, d in zip(b, mut)),
            "suffix_changed": any(not np.array_equal(np.asarray(x)[: len(y)], y) for x, y in zip(a[cut + 1:], b[cut + 1:]))}


def track_cell(ep: W.Episode, cell: Cell, model: Callable | None, ns: str) -> tuple[list[np.ndarray], int]:
    rng = np.random.default_rng(filter_seed(ns, ep.world_index, cell.seed, cell.variant))
    cfg = variant_config(cell.variant)
    if cell.arm == "S-P":
        return F.track_truth_diagnostic(ep, Mo.true_physics, rng, cfg)
    return F.track(student_detections(ep), ep.pillars, model, rng, cfg)


# --- one world ----------------------------------------------------------------------------------
def dyn_sums(ep: W.Episode, model: Callable) -> dict[str, float]:
    e = Me.dynamics_errors(ep, model)
    return {"coll": float(np.sum(e["coll"])), "n_coll": len(e["coll"]), "graze": float(np.sum(e["graze"])), "n_graze": len(e["graze"])}


def world_record(ep: W.Episode, kind: str, ns: str, cells: Sequence[Cell], models: Mapping[str, Callable]) -> dict[str, Any]:
    """``models`` maps an arm or an arm#seed (learned) to its process model."""
    events = W.reappearances(ep)
    rec: dict[str, Any] = {"kind": kind, "world": ep.world_index, "n_disks": ep.n_disks,
                           "events": [[e["k"], e["a"], e["b"], int(e["collision"])] for e in events], "dyn": {}, "reid": {}, "idf1": {}, "ids_sha256": {}, "n_tracks": {}}
    for name, m in models.items():
        if name != "E-CV" and not name.startswith("L-int-s"):
            rec["dyn"][name] = dyn_sums(ep, m)
    for cell in cells:
        model = None if cell.arm == "S-P" else models.get(f"{cell.arm}#{cell.seed}", models.get(cell.arm))
        if cell.arm != "S-P" and model is None:
            raise KeyError(f"no model for {cell.key}")
        ids, n_tracks = track_cell(ep, cell, model, ns)
        r = Me.reid(ep, ids, events)
        rec["reid"][cell.key] = [x["correct"] for x in r]
        rec["idf1"][cell.key] = Me.idf1(ep, ids)
        rec["ids_sha256"][cell.key] = ids_digest(ids)
        rec["n_tracks"][cell.key] = n_tracks
    return rec


def label_log(kind: str, ep: W.Episode) -> dict[str, Any]:
    """The truth the label verifier recomputes events from: visibility, detected identities and disk contacts per step."""
    disk = [sorted([min(i, j), max(i, j)] for k, i, j in s.contacts if k == "disk") for s in ep.steps]
    return {"kind": kind, "world": ep.world_index, "n_disks": ep.n_disks,
            "visible": ["".join("1" if x else "0" for x in s.visible) for s in ep.steps],
            "detected": [sorted(s.truth_ids.tolist()) for s in ep.steps], "disk_contacts": disk}


# --- aggregation ---------------------------------------------------------------------------------
def acc_sums(records: Sequence[dict], arm: str, variant: str = "base", *, collision: bool = True) -> np.ndarray:
    """Per world: sum over (collision) events of the correctness averaged over the three seeds."""
    out = []
    for r in records:
        mask = np.array([e[3] == 1 if collision else True for e in r["events"]], dtype=bool)
        per = np.mean([np.asarray(r["reid"][Cell(arm, s, variant).key], dtype=np.float64) for s in SEEDS], axis=0) if r["events"] else np.zeros(0)
        out.append(float(per[mask].sum()) if len(per) else 0.0)
    return np.array(out)


def n_events(records: Sequence[dict], *, collision: bool = True) -> np.ndarray:
    return np.array([float(sum(1 for e in r["events"] if (e[3] == 1 or not collision))) for r in records])


def dyn_world(records: Sequence[dict], arm: str, field: str, *, seeds: Sequence[int] | None = None) -> np.ndarray:
    """Per world sum of a dynamics field; learned arms averaged over seeds."""
    if seeds is None:
        return np.array([r["dyn"][arm][field] for r in records], dtype=np.float64)
    return np.array([np.mean([r["dyn"][f"{arm}#{s}"][field] for s in seeds]) for r in records], dtype=np.float64)


def D_of(records, arm, *, learned=True, m=N_COMPARISONS):
    x = dyn_world(records, arm, "coll", seeds=SEEDS if learned else None)
    return Me.bootstrap(Me.stat_D, {"x_coll": x, "b_coll": dyn_world(records, "E-B", "coll")}, m=m)


def HF_of(records, arm, *, learned=True, m=N_COMPARISONS):
    s = SEEDS if learned else None
    return Me.bootstrap(Me.stat_HF, {"x_graze": dyn_world(records, arm, "graze", seeds=s), "n_graze": dyn_world(records, arm, "n_graze", seeds=s),
                                     "b_coll": dyn_world(records, "E-B", "coll"), "n_coll": dyn_world(records, "E-B", "n_coll")}, m=m)


def C_of(records, arm, variant="base", *, m=N_COMPARISONS):
    return Me.bootstrap(Me.stat_C, {"x": acc_sums(records, arm, variant), "b": acc_sums(records, "E-B", variant), "p": acc_sums(records, "E-P", variant)}, m=m)


def acc_of(records, arm, variant="base", *, collision=True, m=1):
    return Me.bootstrap(Me.stat_diff, {"x": acc_sums(records, arm, variant, collision=collision), "y": np.zeros(len(records)),
                                       "n": n_events(records, collision=collision)}, m=m)


def diff_of(records, a, b, variant="base", *, m=N_COMPARISONS):
    return Me.bootstrap(Me.stat_diff, {"x": acc_sums(records, a, variant), "y": acc_sums(records, b, variant), "n": n_events(records)}, m=m)


# --- gates -----------------------------------------------------------------------------------------
def legality(main: Sequence[dict], extrap: Sequence[dict], *, n_main: int, n_extrap: int, labels_ok: bool, student_ok: bool,
             replay_ok: bool) -> dict[str, Any]:
    acc = {a: acc_of(main, a)["value"] for a in ("E-CV", "E-B", "E-P")}
    missing = [a for a, v in acc.items() if v is None]
    floor = not missing and acc["E-CV"] < acc["E-B"] < acc["E-P"]
    n_coll_events = int(n_events(main).sum())
    expected = EXPECTED_COLL_EVENTS_PER_40 * n_main / 40
    n_coll_steps = int(dyn_world(main, "E-B", "n_coll").sum())
    dyn_expected = EXPECTED_COLL_DISK_STEPS_PER_40 * n_main / 40
    out = {
        "labels": {"passed": bool(labels_ok)},
        "student_view": {"passed": bool(student_ok)},
        "floor": {"passed": bool(floor), "acc": acc, **({"undefined": missing} if missing else {})},
        "complete": {"passed": len(main) == n_main and len(extrap) == n_extrap, "main": len(main), "extrap": len(extrap),
                     "registered": [n_main, n_extrap]},
        "samples": {"passed": bool(abs(n_coll_events - expected) <= SAMPLE_BAND * expected and n_coll_steps >= DYN_FLOOR * dyn_expected),
                    "collision_events": n_coll_events, "expected": expected, "collision_disk_steps": n_coll_steps, "dyn_expected": dyn_expected},
        "determinism": {"passed": bool(replay_ok)},
    }
    return out


def evaluate(main: Sequence[dict], extrap: Sequence[dict], *, n_main: int, n_extrap: int, labels_ok: bool, student_ok: bool,
             replay_ok: bool) -> dict[str, Any]:
    T = THRESHOLDS
    lg = legality(main, extrap, n_main=n_main, n_extrap=n_extrap, labels_ok=labels_ok, student_ok=student_ok, replay_ok=replay_ok)
    valid = all(v["passed"] for v in lg.values())
    d, hf = D_of(main, "L-int"), HF_of(main, "L-int")
    dx, hfx = D_of(extrap, "L-int"), HF_of(extrap, "L-int")
    c, cx = C_of(main, "L-int"), C_of(extrap, "L-int")
    h2 = diff_of(main, "L-int", "L-ind")
    d_ind, c_ind = D_of(main, "L-ind"), C_of(main, "L-ind")

    def ok(*conds):
        return bool(all(x is not None for x in conds[::2]) and all(conds[1::2]))

    neg = {"passed": ok(d_ind["ci_low"], d_ind["ci_low"] is not None and d_ind["ci_low"] < T["negative_control"]["D_low_below"],
                        c_ind["ci_low"], c_ind["ci_low"] is not None and c_ind["ci_low"] < T["negative_control"]["C_low_below"]),
           "D_L-ind": d_ind, "C_L-ind": c_ind}
    g = {
        "HD": {"passed": ok(d["value"], d["value"] is not None and d["value"] >= T["HD"]["D"], d["ci_low"], d["ci_low"] is not None and d["ci_low"] > T["HD"]["D_low"]), "D": d},
        "HF": {"passed": ok(hf["value"], hf["value"] is not None and hf["value"] <= T["HF"]["ratio"], hf["ci_high"], hf["ci_high"] is not None and hf["ci_high"] <= T["HF"]["ratio_high"]), "ratio": hf},
        "HD-x": {"passed": ok(dx["value"], dx["value"] is not None and dx["value"] >= T["HD-x"]["D"], dx["ci_low"], dx["ci_low"] is not None and dx["ci_low"] > T["HD-x"]["D_low"],
                              hfx["value"], hfx["value"] is not None and hfx["value"] <= T["HD-x"]["ratio"]), "D": dx, "ratio": hfx},
        "H1": {"passed": ok(c["value"], c["value"] is not None and c["value"] >= T["H1"]["C"], c["ci_low"], c["ci_low"] is not None and c["ci_low"] > T["H1"]["C_low"]), "C": c},
        "H2": {"passed": ok(h2["value"], h2["value"] is not None and h2["value"] >= T["H2"]["diff"], h2["ci_low"], h2["ci_low"] is not None and h2["ci_low"] > T["H2"]["diff_low"]), "diff": h2},
        "H3": {"passed": ok(cx["value"], cx["value"] is not None and cx["value"] >= T["H3"]["C"], cx["ci_low"], cx["ci_low"] is not None and cx["ci_low"] > T["H3"]["C_low"]), "C": cx},
    }
    if not neg["passed"]:
        for k in ("HD", "H1"):
            g[k] = dict(g[k], passed=False, void="negative control failed")
    if not valid:
        for k in g:
            g[k] = dict(g[k], passed=False, void="legality failed")
    return {"valid": valid, "legality": lg, "negative_control": neg, "gates": g}


def descriptive_tracking(main: Sequence[dict], extrap: Sequence[dict], learned_arms: Sequence[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"acc_collision": {}, "acc_all": {}, "C": {}, "idf1": {}, "n_tracks": {}}
    for part, recs in (("main", main), ("extrap", extrap)):
        arms = ["E-CV", "E-B", "E-P", "S-P", *learned_arms]
        out["acc_collision"][part] = {a: acc_of(recs, a)["value"] for a in arms}
        out["acc_all"][part] = {a: acc_of(recs, a, collision=False)["value"] for a in arms}
        out["C"][part] = {a: C_of(recs, a, m=1) for a in ("S-P", *learned_arms)}
        out["idf1"][part] = {a: float(np.mean([np.mean([r["idf1"][Cell(a, s).key] for s in SEEDS]) for r in recs])) for a in arms}
        out["n_tracks"][part] = {a: float(np.mean([np.mean([r["n_tracks"][Cell(a, s).key] for s in SEEDS]) for r in recs])) for a in arms}
    out["variants"] = {v: {"C_L-int": C_of(main, "L-int", v, m=1), "C_S-P": C_of(main, "S-P", v, m=1),
                           "acc": {a: acc_of(main, a, v)["value"] for a in (*GATE_ARMS, "S-P")}} for v in variants()}
    return out


# --- descriptive dynamics (from the exact truth unless said otherwise) -----------------------------
KSTEPS = (1, 5, 10, 30)
KSTEP_EVERY = 10
CHI2_2_90 = -2 * np.log(0.1)           # 90% region of a 2-D Gaussian
CALIB_BINS = (0.0, 0.6, 0.7, 0.8, 1.0, 1.3, 2.0, 99.0)
GRAZE = 2 * W.RADIUS + Me.GRAZE_MARGIN
VISIBLE_SIGMA = (0.05, 0.2)            # visible-track noise; equals learned_mlx.VISIBLE_SIGMA (tested)


def _disk_pairs(contacts) -> set[tuple[int, int]]:
    return {(min(i, j), max(i, j)) for kind, i, j in contacts if kind == "disk"}


def cv_contact_pairs(p: np.ndarray, v: np.ndarray) -> set[tuple[int, int]]:
    """Baseline: a pair approaching on straight lines that touches within one step."""
    out = set()
    n = len(p)
    for i in range(n):
        for j in range(i + 1, n):
            d, u = p[j] - p[i], v[j] - v[i]
            a, b, c = u @ u, 2 * d @ u, d @ d - (2 * W.RADIUS) ** 2
            if c <= 0 and b < 0:
                out.add((i, j))
                continue
            disc = b * b - 4 * a * c
            if a > 0 and disc >= 0 and b < 0:
                tau = (-b - np.sqrt(disc)) / (2 * a)
                if 0 <= tau < W.DT:
                    out.add((i, j))
    return out


def contact_counts(ep: W.Episode, logits_fn: Callable) -> dict[str, dict[str, int]]:
    """True/false positives and misses of the contact head (logit > 0) and of the baseline."""
    out = {k: {"tp": 0, "fp": 0, "fn": 0} for k in ("head", "cv")}
    for s in ep.steps[:-1]:
        truth = _disk_pairs(s.contacts)
        lg = np.asarray(logits_fn(s.positions[None], s.velocities[None], ep.pillars))[0]
        head = {(i, j) for i in range(ep.n_disks) for j in range(i + 1, ep.n_disks) if lg[i, j] > 0}
        for name, pred in (("head", head), ("cv", cv_contact_pairs(s.positions, s.velocities))):
            out[name]["tp"] += len(pred & truth)
            out[name]["fp"] += len(pred - truth)
            out[name]["fn"] += len(truth - pred)
    return out


def f1(c: Mapping[str, int]) -> float | None:
    d = 2 * c["tp"] + c["fp"] + c["fn"]
    return None if d == 0 else 2 * c["tp"] / d


def kstep_sums(ep: W.Episode, model: Callable) -> dict[str, list[float]]:
    """Mean position error over disks after k of the model's own steps from the exact truth, summed over starts."""
    out = {str(k): [0.0, 0] for k in KSTEPS}
    T = len(ep.steps)
    for t in range(0, T - max(KSTEPS), KSTEP_EVERY):
        P, V = ep.steps[t].positions[None], ep.steps[t].velocities[None]
        for k in range(1, max(KSTEPS) + 1):
            o = model(P, V, ep.pillars)
            P, V = np.asarray(o[0]), np.asarray(o[1])
            if k in KSTEPS:
                out[str(k)][0] += float(np.linalg.norm(P[0] - ep.steps[t + k].positions, axis=1).mean())
                out[str(k)][1] += 1
    return out


def perturbed_dyn_sums(ep: W.Episode, models: Mapping[str, Callable], perturb: Callable, rng: np.random.Generator) -> dict[str, dict[str, float]]:
    """Collision-disk velocity errors on perturbed inputs (training perturbation), labels from the
    simulator on the perturbed input; every model sees the same inputs."""
    out = {name: {"coll": 0.0, "n_coll": 0} for name in models}
    for s in ep.steps[:-1]:
        p, v = perturb(s.positions, s.velocities, rng, exact=False)
        tp, tv, c = W.physics(p[None], v[None], ep.pillars, log=True)
        coll = sorted({i for kind, i, j in c if kind == "disk"} | {j for kind, i, j in c if kind == "disk"})
        if not coll:
            continue
        for name, m in models.items():
            o = m(p[None], v[None], ep.pillars)
            err = np.linalg.norm(np.asarray(o[1])[0] - tv[0], axis=1)
            out[name]["coll"] += float(err[coll].sum())
            out[name]["n_coll"] += len(coll)
    return out


def calib_rows(ep: W.Episode, mean_var: Callable, rng: np.random.Generator, *, every: int = 1) -> dict[str, np.ndarray]:
    """L-int-σ rows: visible-noise truth at t, against the true next velocity. Per disk: kind
    (0 collision, 1 graze, 2 free), input distance to the nearest disk, error and variance per axis."""
    kinds, dmin, err, var = [], [], [], []
    for s, nxt in list(zip(ep.steps[:-1], ep.steps[1:]))[::every]:
        p0 = np.clip(s.positions + rng.normal(0, VISIBLE_SIGMA[0], s.positions.shape), W.RADIUS, W.ARENA - W.RADIUS)
        v0 = s.velocities + rng.normal(0, VISIBLE_SIGMA[1], s.velocities.shape)
        _, vm, _, vv = mean_var(p0[None], v0[None], ep.pillars)
        coll = {i for kind, i, j in s.contacts if kind == "disk"} | {j for kind, i, j in s.contacts if kind == "disk"}
        dn = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1) + np.eye(ep.n_disks) * 99
        d0 = np.linalg.norm(p0[:, None] - p0[None], axis=-1) + np.eye(ep.n_disks) * 99
        for i in range(ep.n_disks):
            kinds.append(0 if i in coll else (1 if dn[i].min() < GRAZE else 2))
        dmin.append(d0.min(1)); err.append(np.asarray(vm)[0] - nxt.velocities); var.append(np.asarray(vv)[0])
    return {"kind": np.array(kinds, dtype=np.int64), "dmin": np.concatenate(dmin), "err": np.concatenate(err), "var": np.concatenate(var)}


def _gauss(se_axes: np.ndarray, var_axes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    nll = (0.5 * np.log(2 * np.pi * var_axes) + se_axes / (2 * var_axes)).sum(-1)
    inside = (se_axes / var_axes).sum(-1) <= CHI2_2_90
    return nll, inside


def fit_references(train: Mapping[str, np.ndarray]) -> dict[str, Any]:
    """Per-axis variances fitted on train rows: a constant on collision and graze rows, distance bins
    on all rows (student-visible), and a two-bin truth oracle (collision or graze, free)."""
    se = train["err"] ** 2
    cg = train["kind"] <= 1
    idx = np.clip(np.digitize(train["dmin"], CALIB_BINS) - 1, 0, len(CALIB_BINS) - 2)
    const = float(se[cg].mean())
    bins = [float(se[idx == b].mean()) if (idx == b).any() else const for b in range(len(CALIB_BINS) - 1)]
    return {"constant": const, "bins": bins, "oracle": [float(se[cg].mean()), float(se[~cg].mean())]}


CALIB_KINDS = ("collision", "graze", "free", "collision+graze")
CALIB_NAMES = ("L-int-s", "constant", "binned", "oracle")


def calibration_sums(rows: Mapping[str, np.ndarray], ref: Mapping[str, Any]) -> dict[str, dict[str, list[float]]]:
    """Per step kind and predictor: [sum of velocity NLL, number inside the 90% region, rows]."""
    se = rows["err"] ** 2
    n = len(se)
    idx = np.clip(np.digitize(rows["dmin"], CALIB_BINS) - 1, 0, len(CALIB_BINS) - 2)
    cg = rows["kind"] <= 1
    var = {"L-int-s": rows["var"], "constant": np.full((n, 2), ref["constant"]),
           "binned": np.repeat(np.array(ref["bins"])[idx][:, None], 2, 1),
           "oracle": np.repeat(np.where(cg, ref["oracle"][0], ref["oracle"][1])[:, None], 2, 1)}
    sel = {"collision": rows["kind"] == 0, "graze": rows["kind"] == 1, "free": rows["kind"] == 2, "collision+graze": cg}
    out: dict[str, dict[str, list[float]]] = {}
    for k in CALIB_KINDS:
        out[k] = {}
        for name in CALIB_NAMES:
            nll, inside = _gauss(se[sel[k]], var[name][sel[k]])
            out[k][name] = [float(nll.sum()), float(inside.sum()), int(sel[k].sum())]
    return out


def calibration_from_sums(parts: Sequence[Mapping[str, Mapping[str, Sequence[float]]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in CALIB_KINDS:
        n = sum(p[k][CALIB_NAMES[0]][2] for p in parts)
        out[k] = {"n": int(n)}
        for name in CALIB_NAMES:
            a = sum(p[k][name][0] for p in parts)
            b = sum(p[k][name][1] for p in parts)
            out[k][name] = {"nll": a / n if n else None, "cov90": b / n if n else None}
    return out


def calibration(rows: Mapping[str, np.ndarray], ref: Mapping[str, Any]) -> dict[str, Any]:
    """Velocity NLL and 90% coverage of L-int-σ and of the three references, by step kind."""
    return calibration_from_sums([calibration_sums(rows, ref)])


class FilterCalibration:
    """``on_predict`` hook: for tracks assigned at t-1 and again at t, the predicted ensemble's NLL of
    the true position of the detected disk and whether it lies in the 90% ellipse."""

    def __init__(self, ep: W.Episode):
        self.ep = ep
        self.nll: list[float] = []
        self.inside: list[bool] = []

    def __call__(self, t, P, V, assign, last):
        s = self.ep.steps[t]
        for r, k in assign.items():
            if last[k] != t - 1:
                continue
            x = P[:, k]
            mu = x.mean(0)
            cov = np.cov(x.T) + np.eye(2) * 1e-9
            d = s.positions[int(s.truth_ids[r])] - mu
            m2 = float(d @ np.linalg.solve(cov, d))
            self.nll.append(float(0.5 * (np.log((2 * np.pi) ** 2 * np.linalg.det(cov)) + m2)))
            self.inside.append(m2 <= CHI2_2_90)

    def sums(self) -> dict[str, float]:
        return {"nll": float(np.sum(self.nll)), "inside": float(np.sum(self.inside)), "n": len(self.nll)}


# --- descriptive summary from the worker sums ------------------------------------------------------
def summarize_descriptive(main: Sequence[dict], extrap: Sequence[dict], learned_arms: Sequence[str]) -> dict[str, Any]:
    mean_arms = [a for a in learned_arms if a != "L-int-s"]
    out: dict[str, Any] = {"tracking": descriptive_tracking(main, extrap, learned_arms)}
    out["dynamics"] = {}
    for part, recs in (("main", main), ("extrap", extrap)):
        d = {a: {"D": D_of(recs, a, m=1), "HF": HF_of(recs, a, m=1)} for a in mean_arms}
        d["E-P"] = {"D": D_of(recs, "E-P", learned=False, m=1)}
        out["dynamics"][part] = d
    out["canonical_minus_plain"] = {
        tag: {"D": _gap(out["dynamics"]["main"], f"L-int-c{tag}", f"L-int{tag}"), "acc_collision": diff_of(main, f"L-int-c{tag}", f"L-int{tag}", m=1)}
        for tag in ("", "-e8") if f"L-int-c{tag}" in learned_arms and f"L-int{tag}" in learned_arms}
    cont: dict[str, Any] = {}
    for part, recs in (("main", main), ("extrap", extrap)):
        tot: dict[str, dict[str, int]] = {}
        for r in recs:
            for name, c in r["descriptive"]["contact"].items():
                arm = name.split("#")[0]
                for k in ("head", "cv"):
                    key = arm if k == "head" else "CV baseline"
                    t = tot.setdefault(key, {"tp": 0, "fp": 0, "fn": 0})
                    if k == "cv" and not name.endswith("#1"):
                        continue                      # the baseline does not depend on the model
                    for f in t:
                        t[f] += c[k][f]
        cont[part] = {k: {"f1": f1(v), **v} for k, v in tot.items()}
    out["contact_f1"] = cont
    ks: dict[str, dict[str, float]] = {}
    for r in main:
        for name, sums in r["descriptive"]["kstep"].items():
            arm = name.split("#")[0]
            for k, (s, n) in sums.items():
                acc = ks.setdefault(arm, {}).setdefault(k, [0.0, 0])
                acc[0] += s; acc[1] += n
    out["kstep_position_error"] = {a: {k: v[0] / v[1] for k, v in d.items()} for a, d in ks.items()}
    pert: dict[str, list[float]] = {}
    for r in main:
        for name, v in r["descriptive"]["perturbed"].items():
            acc = pert.setdefault(name.split("#")[0], [0.0, 0])
            acc[0] += v["coll"]; acc[1] += v["n_coll"]
    out["perturbed_D"] = {a: 1 - (v[0] / v[1]) / (pert["E-B"][0] / pert["E-B"][1]) for a, v in pert.items() if a != "E-B" and v[1]}
    out["calibration"] = {part: calibration_from_sums([p for r in recs for p in r["descriptive"]["calibration"].values()])
                          for part, recs in (("main", main), ("extrap", extrap)) if any(r["descriptive"]["calibration"] for r in recs)}
    fc: dict[str, dict[str, list[float]]] = {}
    for part, recs in (("main", main), ("extrap", extrap)):
        for r in recs:
            for key, v in r["descriptive"]["filter_calibration"].items():
                acc = fc.setdefault(part, {}).setdefault(key.split("#")[0], [0.0, 0.0, 0])
                acc[0] += v["nll"]; acc[1] += v["inside"]; acc[2] += v["n"]
    out["filter_calibration"] = {part: {a: {"nll": v[0] / v[2], "cov90": v[1] / v[2], "n": v[2]} for a, v in d.items() if v[2]} for part, d in fc.items()}
    return out


def _gap(d: Mapping[str, Any], a: str, b: str) -> float | None:
    x, y = d.get(a, {}).get("D", {}).get("value"), d.get(b, {}).get("D", {}).get("value")
    return None if x is None or y is None else x - y
