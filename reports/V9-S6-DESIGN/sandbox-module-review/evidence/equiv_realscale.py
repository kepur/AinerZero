#!/usr/bin/env python3
"""P253 review, item 2: the module against the prototype code at the prototype's real scale.

Imports MLX (learned_mlx, gated, the prototypes): run under the shared lock with PYTHONDONTWRITEBYTECODE=1.
Reads (never writes) the phase-1 L-int weights for a realistic disagreement score. Candidate pool exactly
as explore_s6c / explore_s6f: make_pool(train_worlds("s6x-cand", 120), 60000, rng 11, exact_frac=1.0).

Checks:
  G  geo_flags vs explore_s6f.geo_flags (= gated.geo_gate(float64).any) on all 60000 samples; also a float32
     evaluation of geo_gate, to size the "drop the float64 cast" mutation.
  D  exact duplicate states in the pool; are labels identical inside a duplicate group?
  R  arm random, 4 rounds x 3000: prototype rng stream vs pick_random + reveal; ids and revealed_pool vs
     explore_s6a.subset(cand, chosen), field by field, bit for bit, in row order.
  Gm arm geo, same, with pick_geo.
  T  arm top with the real disagreement score (explore_s6a.score_pool over the phase-1 L-int#1-3, CPU):
     prototype rest[np.argsort(-score[rest])[:per]] vs pick_top; then a coarsened score (rounded) that
     forces ties between distinct states.
  X  labels recomputed from the public states with the simulator (W.physics), float32 states -> float64.
"""
import sys
import time

import numpy as np

sys.path.insert(0, "reports/V9-S6-DESIGN/tier1-explore")
import explore_s6a as XA  # noqa: E402
import explore_s6f as XF  # noqa: E402
import mlx.core as mx  # noqa: E402

from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import gated as G  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s6 import sandbox as S  # noqa: E402

print("sandbox module:", S.__file__, flush=True)
PER, ROUNDS = 3000, 4
t0 = time.time()
cand = L.make_pool(A.train_worlds("s6x-cand", 120), 60_000, np.random.default_rng(11), W.physics, exact_frac=1.0)
allp = XA.flat_pool(cand)
N = len(allp)
print(f"pool built {time.time() - t0:.0f}s; N={N}; buckets {{n: rows}} = {{{', '.join(f'{n}: {len(e['p'])}' for n, e in cand.by_n.items())}}}", flush=True)
print("pool fields per bucket (make_pool key order):", list(cand.by_n[min(cand.by_n)]))


def same_pool(a, b):
    """Bit-identical field by field, rows in order; reports the first mismatch."""
    if sorted(a.by_n) != sorted(b.by_n):
        return f"bucket sets differ {sorted(a.by_n)} vs {sorted(b.by_n)}"
    for n in a.by_n:
        if set(a.by_n[n]) != set(b.by_n[n]):
            return f"field sets differ at n={n}"
        for k in a.by_n[n]:
            x, y = a.by_n[n][k], b.by_n[n][k]
            if x.dtype != y.dtype or x.shape != y.shape or x.tobytes() != y.tobytes():
                return f"n={n} field {k} differs ({x.dtype}{x.shape} vs {y.dtype}{y.shape})"
    return "identical"


# --- G: geo flags -------------------------------------------------------------------------------
cp = S.CandidatePool(cand)
st = cp.states()
flags = S.geo_flags(st)
gf = XF.geo_flags(cand)
gvec = np.array([gf[n][i] for n, i in allp])
print(f"G geo_flags == explore_s6f.geo_flags on all {N}: {np.array_equal(flags, gvec)}; flagged {int(flags.sum())} "
      f"({flags.mean():.4f})", flush=True)
f32 = np.concatenate([G.geo_gate(cand.by_n[n]["p"], cand.by_n[n]["v"]).any(-1) for n in sorted(cand.by_n)])
print(f"G geo_gate on float32 states (no cast) differs from float64 on {int((f32 != gvec).sum())} of {N} samples")

# --- D: duplicates ------------------------------------------------------------------------------
dup_groups, dup_rows, label_mismatch, distinct = 0, 0, 0, 0
key_of = np.empty(N, dtype=object)
for n in sorted(cand.by_n):
    e = cand.by_n[n]
    first = cp._first_id[n]
    keys = {}
    for i in range(len(e["p"])):
        k = (n, e["p"][i].tobytes(), e["v"][i].tobytes(), e["pil"][i].tobytes())
        keys.setdefault(k, []).append(i)
        key_of[first + i] = k
    distinct += len(keys)
    for rows in keys.values():
        if len(rows) > 1:
            dup_groups += 1
            dup_rows += len(rows)
            for k in e:
                if k in ("p", "v", "pil"):
                    continue
                if any(e[k][r].tobytes() != e[k][rows[0]].tobytes() for r in rows[1:]):
                    label_mismatch += 1
                    break
steps_per_ep = len(W.generate_episode("s6x-cand", 0, A.train_disks("s6x-cand", 0)).steps)
print(f"D distinct states {distinct} of {N}; duplicate groups {dup_groups} covering {dup_rows} rows; "
      f"groups whose labels differ: {label_mismatch}; steps per episode {steps_per_ep}", flush=True)


def run_proto(arm, score_fn=None):
    rng = np.random.default_rng(100)
    chosen = list(rng.choice(N, PER, replace=False))
    for r in range(1, ROUNDS):
        rest = np.setdiff1d(np.arange(N), chosen)
        if arm == "random":
            new = rng.choice(rest, PER, replace=False)
        elif arm == "geo":
            flagged = rest[gvec[rest]]
            take = rng.choice(flagged, min(PER, len(flagged)), replace=False)
            fill = rng.choice(np.setdiff1d(rest, take), PER - len(take), replace=False) if len(take) < PER else np.array([], int)
            new = np.concatenate([take, fill]).astype(int)
        else:
            score = score_fn(r)
            new = rest[np.argsort(-score[rest])[:PER]]
        chosen += list(new)
    return [int(x) for x in chosen]


def run_module(arm, score_fn=None):
    pool = S.CandidatePool(cand)
    rng = np.random.default_rng(100)
    per_round = []
    for r in range(ROUNDS):
        if r == 0:
            ids = S.pick_random(pool.remaining(), PER, rng)
        elif arm == "random":
            ids = S.pick_random(pool.remaining(), PER, rng)
        elif arm == "geo":
            ids = S.pick_geo(flags, pool.remaining(), PER, rng)
        else:
            ids = S.pick_top(score_fn(r), pool.remaining(), PER)
        got = pool.reveal(ids)
        per_round.append(same_pool(got, XA.subset(cand, [allp[i] for i in ids])))
    return pool, per_round


def compare(arm, score_fn=None):
    proto = run_proto(arm, score_fn)
    pool, per_round = run_module(arm, score_fn)
    mod = pool.revealed_ids().tolist()
    same_ids = proto == mod
    same_set = set(proto) == set(mod)
    pos_diff = sum(a != b for a, b in zip(proto, mod))
    content = same_pool(pool.revealed_pool(), XA.subset(cand, [allp[i] for i in proto]))
    # content of the differing positions: same state (duplicate) or not
    dup_swap = sum(1 for a, b in zip(proto, mod) if a != b and key_of[a] == key_of[b])
    picks_distinct = len({key_of[i] for i in mod})
    print(f"{arm}: ids identical {same_ids}; sets identical {same_set}; positions differing {pos_diff} "
          f"(of which same state, i.e. duplicate swapped: {dup_swap}); revealed_pool vs subset(cand, prototype "
          f"chosen): {content}; each round's reveal() vs subset(cand, ids): {per_round}; distinct states among "
          f"the {len(mod)} picks: {picks_distinct}", flush=True)


compare("random")
compare("geo")

# --- T: real disagreement score -----------------------------------------------------------------
mx.set_default_device(mx.cpu)
nets = [L.load("L-int", f"{XA.WDIR}/L-int#{s}.safetensors") for s in XA.SEEDS]
dis, _ = XA.score_pool(cand, nets)            # the prototype also computes err (labels); unused here
dvec = np.array([dis[n][i] for n, i in allp])
print(f"T disagreement score computed {time.time() - t0:.0f}s; dtype {dvec.dtype}", flush=True)
# ties: how many distinct score values, and do ties coincide with duplicate states?
vals, inv, cnt = np.unique(dvec, return_inverse=True, return_counts=True)
tied = cnt[inv] > 1
nondup_ties = 0
by_val = {}
for i in np.flatnonzero(tied):
    by_val.setdefault(int(inv[i]), []).append(int(i))
for members in by_val.values():
    if len({key_of[i] for i in members}) > 1:
        nondup_ties += 1
print(f"T samples sharing their exact score with another sample: {int(tied.sum())}; score values shared by "
      f"distinct states: {nondup_ties}")
# within a duplicate group, is the score identical?
grp = {}
for i in range(N):
    grp.setdefault(key_of[i], []).append(i)
dup_score_diff = sum(1 for rows in grp.values() if len(rows) > 1 and len(set(dvec[rows].tolist())) > 1)
print(f"T duplicate groups whose members got different scores: {dup_score_diff}")
compare("top", lambda r: dvec)
coarse = np.round(dvec, 2)
print(f"T coarse score: distinct values {len(np.unique(coarse))}")
compare("top-coarse", lambda r: coarse)

# --- X: labels from states with the simulator -----------------------------------------------------
pool = S.CandidatePool(cand)
st = pool.states()
n0 = sorted(st)[0]
ids = st[n0]["id"][:200]
rev = pool.reveal(ids).by_n[n0]
err = 0.0
for b in range(len(ids)):
    pil = tuple(map(tuple, st[n0]["pil"][b].astype(np.float64)))
    p1, v1, _ = W.physics(st[n0]["p"][b:b + 1].astype(np.float64), st[n0]["v"][b:b + 1].astype(np.float64), pil, log=True)
    err = max(err, float(np.abs(p1[0] - rev["p1"][b]).max()), float(np.abs(v1[0] - rev["v1"][b]).max()))
print(f"X p1/v1 recomputed from public states with W.physics on {len(ids)} samples (n={n0}): max |diff| {err:.3g}")
print(f"total {time.time() - t0:.0f}s")
