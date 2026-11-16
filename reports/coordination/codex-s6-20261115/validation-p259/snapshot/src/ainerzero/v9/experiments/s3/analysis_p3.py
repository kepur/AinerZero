"""GridLab-S3 phase 3: events, policies, contract gates and registered descriptive quantities.

Per reports/V9-S3-PHASE3-DESIGN/DESIGN-r2.md §2–§4. Pure CPU, NumPy / standard library only.
Zero MLX imports.

Policies answer from student-visible records only (estimated pose, terrain, tokens), with two
declared truth inputs: the query type (which store G consults) and the start pose that the
frozen tour anchors every episode to. The truth is otherwise used to schedule and classify
queries (as the phase 1/2 readout events) and for diagnostics (GT, LT, item purity).
"""

from __future__ import annotations

import json
import random
from typing import Any, Sequence

import numpy as np

from ainerzero.v9.experiments.s3 import persist as PS
from ainerzero.v9.experiments.s3 import promotion as PR
from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.cues import rank_candidates
from ainerzero.v9.experiments.s3.data import derive_seed
from ainerzero.v9.experiments.s3.store import EpisodicStore

NAMESPACES = {"train": "s3p3-train", "dev": "s3p3-dev", "final": "s3p3-final", "probe": "s3p3-probe"}
LAM = 1.0
GAP = 5
TIE = 1e-6
ALPHAS = {"U0": 0.0, "U05": 0.5, "U1": 1.0, "U2": 2.0}
OFFSETS = (1, 2, 3, 5)
BOOT_N, BOOT_SEED, LEVEL = 10_000, 20261110, 0.95
EXPECTED_PER_100 = {"fast": 2030, "decoy_stable": 800, "relocated": 1070}
# 4 SD of (count - expectation), counting the expectation's own error (DESIGN-r2 §4 K5).
SAMPLE_BAND = {"fast": 0.07, "decoy_stable": 0.13, "relocated": 0.21}
POLICIES = ("C", "L", "G", "GNR", "MODE", "GP", "SR", "U0", "U05", "U1", "U2", "GT", "LT")
KIND_FAST, KIND_QUERY = 0, 1
FIELDS = (
    "kind", "world", "episode", "t", "answer", "shown", "decoy", "relocated", "tok_before", "tok_after",
    "first_ok", "g_slow", "g_item_on_cell", "query_tie", "sr_fast", "u0_past",
) + tuple(f"pred_{p}" for p in POLICIES)

# Registered descriptive comparisons: (name, event set, a, b) for accuracy(a) - accuracy(b).
COMPARISONS = (
    ("D1_G_minus_Gperm_decoy", "decoy", "G", "GP"),
    ("D1_G_minus_C_decoy", "decoy", "G", "C"),
    ("D1_G_minus_C_all_queries", "query", "G", "C"),
    ("D2_C_minus_U0", "fast_e1", "C", "U0"),
    ("D2_C_minus_U05", "fast_e1", "C", "U05"),
    ("D2_C_minus_U1", "fast_e1", "C", "U1"),
    ("D2_C_minus_U2", "fast_e1", "C", "U2"),
    ("D3_G_minus_L", "decoy_stable", "G", "L"),
    ("D3_G_minus_MODE", "decoy_stable", "G", "MODE"),
    ("D3_MODE_minus_L", "decoy_stable", "MODE", "L"),
    ("D3_G_minus_GNR", "decoy_stable", "G", "GNR"),
    ("D4_G_minus_GNR", "relocated", "G", "GNR"),
    ("D4_G_minus_L", "relocated", "G", "L"),
    ("D4_G_minus_MODE", "relocated", "G", "MODE"),
    ("D5_SR_minus_G_queries", "query", "SR", "G"),
    ("D5_SR_minus_G_fast", "fast", "SR", "G"),
    ("D7_GT_minus_G_stable", "decoy_stable", "GT", "G"),
    ("D7_LT_minus_L_stable", "decoy_stable", "LT", "L"),
    ("D7_GT_minus_G_relocated", "relocated", "GT", "G"),
    ("D7_LT_minus_L_relocated", "relocated", "LT", "L"),
    ("D9_C_minus_G_clean", "clean", "C", "G"),
)
OFFSET_COMPARISONS = (
    ("C_minus_U0", "fast_e1", "C", "U0"),
    ("G_minus_L_stable", "decoy_stable", "G", "L"),
    ("G_minus_GNR_relocated", "relocated", "G", "GNR"),
)
N_COMPARISONS = len(COMPARISONS) + len(OFFSET_COMPARISONS) * len(OFFSETS)


# --- retrieval --------------------------------------------------------------------
def top1(R: PS.Records, idx: np.ndarray, qi: int, *, alpha: float = 0.0, eligible_only: bool = False) -> int | None:
    """Best record among ``idx`` for query ``qi``: phase 2 hand cue minus alpha per episode back,
    ties to the latest by global time. With ``eligible_only`` only records passing the place gate."""
    if len(idx) == 0:
        return None
    score, ok = PR.place_scores(R.xy[idx], R.terrain[idx], R.xy[qi], R.terrain[qi])
    if eligible_only:
        if not ok.any():
            return None
        idx, score = idx[ok], score[ok]
    score = score - alpha * (R.ep[qi] - R.ep[idx]) + TIE * R.gtime(idx)
    return int(idx[int(np.argmax(score))])


def fast_pool(R: PS.Records, e: int, t: int) -> np.ndarray:
    s0 = R.start[e]
    return np.arange(s0, s0 + max(t - GAP + 1, 0))


def unified_pool(R: PS.Records, e: int, t: int) -> np.ndarray:
    return np.concatenate([np.arange(0, R.start[e]), fast_pool(R, e, t)])


def latest_match(R: PS.Records, past: np.ndarray, qi: int) -> int | None:
    """Token of the latest past dwell observation that matches the query's place."""
    if len(past) == 0:
        return None
    _, ok = PR.place_scores(R.xy[past], R.terrain[past], R.xy[qi], R.terrain[qi])
    m = past[ok]
    return None if len(m) == 0 else int(R.token[m[int(np.argmax(R.gtime(m)))]])


def shifted(R: PS.Records, seq: PS.WorldSequence, k: int) -> PS.Records:
    """Start-pose translation error: one integer offset in [-k, k]^2 per episode (DESIGN-r2 §4 D6)."""
    xy = R.xy.copy()
    for e in range(len(seq.episodes)):
        rng = random.Random(derive_seed(seq.namespace, "offset", seq.world_index, e, k))
        dx, dy = rng.randint(-k, k), rng.randint(-k, k)
        xy[R.ep == e] += (dx, dy)
    return PS.Records(R.ep, R.t, xy, R.terrain, R.token, R.truth_cell, R.start)


def token_permutation(seq: PS.WorldSequence) -> dict[int, int]:
    """One fixed token permutation per world, unrelated to the truth (the G-perm control)."""
    toks = list(spec.F1_TOKENS)
    return dict(zip(toks, random.Random(derive_seed(seq.namespace, "perm", seq.world_index)).sample(toks, len(toks))))


# --- one world ----------------------------------------------------------------------
def analyse_world(seq: PS.WorldSequence, *, offset: int = 0, full: bool = True) -> tuple[dict[str, list], dict[str, Any]]:
    """Answer every event of one world sequence; return (event columns, world log).

    ``offset`` adds the start-pose translation error of DESIGN-r2 D6. ``full`` adds the
    in-process contract checks and the evidence log (versions, observations, queries).
    """
    R = PS.records_of(seq)
    if offset:
        R = shifted(R, seq, offset)
    n_ep = len(seq.episodes)
    ends = list(R.start[1:]) + [len(R.ep)]
    G = PR.PromotionStore(rollback=True)
    GNR = PR.PromotionStore(rollback=False)
    truth_store = PR.TruthKeyedStore(rollback=True)
    perm = token_permutation(seq)
    past: list[int] = []
    cols: dict[str, list] = {k: [] for k in FIELDS}
    obs_by_ep: list[np.ndarray] = []
    checkpoints: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    fast_events: list[list[int]] = []

    def push(**kw):
        for k in FIELDS:
            cols[k].append(kw.get(k, -1))

    for e in range(n_ep):
        s0, s1 = R.start[e], ends[e]
        ep = seq.episodes[e]
        op = np.array(past, dtype=np.int64)
        if e >= 1:
            for c, t in PS.first_arrivals(seq, e):
                qi = s0 + t
                assert R.t[qi] == t and R.ep[qi] == e
                answer = ep.regime[c]
                shown = int(R.token[qi])
                latest = latest_match(R, op, qi)
                latest = shown if latest is None else latest
                g_item, g_slow = G.answer(R.xy[qi], R.terrain[qi])
                _, q_tie = G.match_tied(R.xy[qi], R.terrain[qi], slow_only=True)
                g = latest if g_slow is None else g_slow
                _, gnr = GNR.answer(R.xy[qi], R.terrain[qi])
                j_any = G.match(R.xy[qi], R.terrain[qi], slow_only=False)
                mode = latest if j_any is None else PR.mode_vote([k for _, k in G.items[j_any].votes])
                f = top1(R, fast_pool(R, e, t), qi, eligible_only=True)
                at_cell = op[(R.truth_cell[op] == np.array(c)).all(1)] if len(op) else op
                lt = int(R.token[at_cell[int(np.argmax(R.gtime(at_cell)))]]) if len(at_cell) else shown
                gt = truth_store.answer(c)
                own = np.flatnonzero((R.ep == e) & (R.truth_cell == np.array(c)).all(1))
                pred = {
                    "C": shown, "L": latest, "G": g, "GNR": latest if gnr is None else gnr, "MODE": mode,
                    "GP": perm.get(g, g), "SR": g if f is None else int(R.token[f]), "LT": lt, "GT": lt if gt is None else gt,
                }
                push(
                    kind=KIND_QUERY, world=seq.world_index, episode=e, t=t, answer=answer, shown=shown,
                    decoy=int(ep.decoy[c]), relocated=int(e >= PS.RELOCATION_EPISODE and c in seq.relocated),
                    tok_before=seq.before[c], tok_after=seq.after[c], first_ok=int(len(own) > 0 and int(R.t[own[0]]) == t),
                    g_slow=int(g_slow is not None), query_tie=int(q_tie), sr_fast=int(f is not None),
                    g_item_on_cell=int(g_item is not None and tuple(R.truth_cell[G.items[g_item].tag]) == c),
                    **{f"pred_{k}": v for k, v in pred.items()},
                )
                if full:
                    queries.append({"episode": e, "t": t, "version": G.head, "xy": R.xy[qi].tolist(), "terrain": R.terrain[qi].tolist(),
                                    "shown": shown, "answer": answer, "decoy": int(ep.decoy[c]),
                                    "relocated": int(e >= PS.RELOCATION_EPISODE and c in seq.relocated),
                                    "pred_G": g, "pred_L": latest, "slow": g_slow})

        # Within-episode readouts. C goes through the frozen phase 2 retrieval, G through the
        # tier-routed FAST pool, U(alpha) through the unified pool.
        frozen = EpisodicStore()
        for s in ep.raw["steps"]:
            frozen.add_step(s)
        for ev in ep.raw["events"]:
            if ev["bucket"] != spec.BUCKET_LONG or not ev["swapped"]:
                continue
            t = int(ev["t"])
            qi = s0 + t
            ranked = rank_candidates(frozen, t, mode="both", lam=LAM, gap=GAP)
            c_pred = int(ranked[0][0].observed_token) if ranked else 0
            g = top1(R, fast_pool(R, e, t), qi)
            uni = unified_pool(R, e, t)
            u = {name: top1(R, uni, qi, alpha=a) for name, a in ALPHAS.items()}
            f = top1(R, fast_pool(R, e, t), qi, eligible_only=True)
            if f is not None:
                sr = int(R.token[f])
            else:
                _, slow = G.answer(R.xy[qi], R.terrain[qi])
                lm = latest_match(R, op, qi)
                sr = slow if slow is not None else (lm if lm is not None else int(R.token[qi]))
            fast_events.append([e, t, int(ev["answer"])])
            push(
                kind=KIND_FAST, world=seq.world_index, episode=e, t=t, answer=int(ev["answer"]), shown=int(R.token[qi]),
                decoy=0, relocated=0, first_ok=1, g_slow=0, g_item_on_cell=0, query_tie=0, sr_fast=int(f is not None),
                u0_past=int(u["U0"] is not None and R.ep[u["U0"]] < e),
                pred_C=c_pred, pred_G=0 if g is None else int(R.token[g]), pred_SR=sr,
                **{f"pred_{name}": 0 if r is None else int(R.token[r]) for name, r in u.items()},
            )

        obs = np.array([s0 + i for i in PR.dwell_starts(R.xy[s0:s1], R.token[s0:s1])], dtype=np.int64)
        obs_by_ep.append(obs)
        G.absorb(e, R.xy[obs], R.terrain[obs], R.token[obs], tags=obs.tolist())
        GNR.absorb(e, R.xy[obs], R.terrain[obs], R.token[obs])
        truth_store.absorb(R.truth_cell[obs].tolist(), R.token[obs].tolist())
        if full:
            checkpoints.append(json.loads(json.dumps(G.state())))
        past += obs.tolist()

    log: dict[str, Any] = {"world": seq.world_index, "items": item_diagnostics(seq, R, G)}
    if full:
        observations = [[int(R.ep[i]), int(R.t[i]), float(R.xy[i][0]), float(R.xy[i][1]), R.terrain[i].tolist(), int(R.token[i])] for o in obs_by_ep for i in o]
        log.update(
            versions=G.versions,
            observations=observations,
            queries=queries,
            fast_events=fast_events,
            checks=reproducibility_checks(G, checkpoints, obs_by_ep, R, queries),
        )
    return cols, log


def reproducibility_checks(store, checkpoints, obs_by_ep, R, queries) -> dict[str, Any]:
    """In-process K1/K3: version-log integrity, re-answers from version records, restore-and-replay."""
    by_hash = {v["hash"]: json.loads(json.dumps(v)) for v in store.versions}
    chain = PR.verify_chain(store.versions)
    snap_bad = [q["episode"] for q in queries if q["version"] not in by_hash or PR.answer_from_snapshot(by_hash[q["version"]], q["xy"], q["terrain"]) != q["slow"]]
    final_state = json.loads(json.dumps(store.state()))
    replay_bad = []
    for k in range(len(checkpoints) - 1):
        s = PR.PromotionStore.restore(checkpoints[k])
        for e in range(k + 1, len(obs_by_ep)):
            o = obs_by_ep[e]
            s.absorb(e, R.xy[o], R.terrain[o], R.token[o])
        if json.loads(json.dumps(s.state())) != final_state:
            replay_bad.append(k)
    return {"chain": chain, "snapshot_mismatch": snap_bad, "replay_mismatch": replay_bad, "n_queries": len(queries), "n_checkpoints": len(checkpoints)}


def item_diagnostics(seq: PS.WorldSequence, R: PS.Records, store: PR.PromotionStore) -> dict[str, int]:
    """Truth-side counts about the items (diagnostic only)."""
    persistent = set(seq.persistent)
    slow = [it for it in store.items if it.slow is not None]
    on = [tuple(int(v) for v in R.truth_cell[it.tag]) for it in slow]
    mixed = sum(len({tuple(int(v) for v in R.truth_cell[m]) for m in it.members}) > 1 for it in store.items)
    return {
        "items": len(store.items),
        "slow": len(slow),
        "slow_off_persistent": sum(c not in persistent for c in on),
        "persistent_with_several_slow": sum(on.count(c) > 1 for c in persistent),
        "mixed_items": int(mixed),
        "versions": len(store.versions) - 1,
        **{k: int(store.diag[k]) for k in ("writes_matched", "write_ties", "votes", "vote_ties")},
    }


# --- statistics ---------------------------------------------------------------------
def to_arrays(cols: dict[str, list]) -> dict[str, np.ndarray]:
    return {k: np.asarray(v, dtype=np.int64) for k, v in cols.items()}


def event_sets(ev: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    q = ev["kind"] == KIND_QUERY
    fast = ev["kind"] == KIND_FAST
    return {
        "fast": fast,
        "fast_e1": fast & (ev["episode"] >= 1),
        "query": q,
        "decoy": q & (ev["decoy"] == 1),
        "decoy_stable": q & (ev["decoy"] == 1) & (ev["relocated"] == 0),
        "relocated": q & (ev["relocated"] == 1),
        "clean": q & (ev["decoy"] == 0),
    }


def correct(ev: dict[str, np.ndarray], policy: str) -> np.ndarray:
    return (ev[f"pred_{policy}"] == ev["answer"]).astype(np.float64)


def paired(ev: dict[str, np.ndarray], mask: np.ndarray, a: str, b: str, *, n_boot: int = BOOT_N, seed: int = BOOT_SEED, m: int = N_COMPARISONS) -> dict[str, Any]:
    """Accuracy difference a − b on the masked events; bootstrap resamples whole worlds.

    Reports the 95% interval and a Bonferroni interval over ``m`` registered comparisons."""
    world = ev["world"][mask]
    if len(world) == 0:
        return {"delta": None, "ci_low": None, "ci_high": None, "bonf_low": None, "bonf_high": None, "n_events": 0, "n_worlds": 0, "acc_a": None, "acc_b": None}
    d = correct(ev, a)[mask] - correct(ev, b)[mask]
    worlds, idx = np.unique(world, return_inverse=True)
    n_w = np.bincount(idx, minlength=len(worlds)).astype(np.float64)
    d_w = np.bincount(idx, weights=d, minlength=len(worlds))
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(worlds), size=(n_boot, len(worlds)))
    boot = d_w[draws].sum(1) / n_w[draws].sum(1)
    tail = (1 - LEVEL) / 2
    lo, hi = np.quantile(boot, [tail, 1 - tail])
    blo, bhi = np.quantile(boot, [tail / m, 1 - tail / m])
    return {"delta": float(d.mean()), "ci_low": float(lo), "ci_high": float(hi), "bonf_low": float(blo), "bonf_high": float(bhi),
            "n_events": int(len(d)), "n_worlds": int(len(worlds)), "acc_a": float(correct(ev, a)[mask].mean()), "acc_b": float(correct(ev, b)[mask].mean())}


def log_linkage(ev: dict[str, np.ndarray], logs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """K6: the events the descriptive measures read are the events of the verified log, row by row."""
    q = ev["kind"] == KIND_QUERY
    f = ev["kind"] == KIND_FAST
    logged_q = [(lg["world"], x["episode"], x["t"], x["answer"], x["shown"], x["decoy"], x["relocated"], x["pred_G"], x["pred_L"]) for lg in logs for x in lg["queries"]]
    event_q = list(zip(*(ev[k][q].tolist() for k in ("world", "episode", "t", "answer", "shown", "decoy", "relocated", "pred_G", "pred_L"))))
    logged_f = [(lg["world"], e, t, a) for lg in logs for e, t, a in lg["fast_events"]]
    event_f = list(zip(*(ev[k][f].tolist() for k in ("world", "episode", "t", "answer"))))
    worlds = [lg["world"] for lg in logs]
    ok_q, ok_f = logged_q == event_q, logged_f == event_f
    return {"passed": bool(ok_q and ok_f and worlds == sorted(set(ev["world"].tolist())) and len(event_q) > 0),
            "queries_match": bool(ok_q), "fast_events_match": bool(ok_f), "n_queries": len(event_q), "n_fast": len(event_f)}


IDENTITY = ("kind", "world", "episode", "t", "answer", "shown", "decoy", "relocated", "tok_before", "tok_after", "first_ok")


def offsets_same_events(ev: dict[str, np.ndarray], offsets: dict[int, dict[str, np.ndarray]] | None) -> dict[str, Any]:
    """K7: every offset file holds the same events as the main run (only the predictions may differ)."""
    if not offsets:
        return {"passed": False, "differing": "no offset files"}
    bad = {str(k): [c for c in IDENTITY if c not in evk or not np.array_equal(evk[c], ev[c])] for k, evk in offsets.items()}
    return {"passed": bool(sorted(offsets) == sorted(OFFSETS) and not any(bad.values())), "differing": {k: v for k, v in bad.items() if v}}


def legality(ev: dict[str, np.ndarray], logs: Sequence[dict[str, Any]], *, stage: str | None, n_worlds: int,
             external: dict[str, Any] | None, external_gen: dict[str, Any] | None,
             offsets: dict[int, dict[str, np.ndarray]] | None = None) -> dict[str, Any]:
    """Contract gates K1–K6 of DESIGN-r2 §4."""
    s = event_sets(ev)
    q = s["query"]
    out: dict[str, Any] = {}
    chain = sum(len(lg["checks"]["chain"]) + len(lg["checks"]["snapshot_mismatch"]) for lg in logs)
    out["K1_versions"] = {"passed": bool(chain == 0 and sum(lg["checks"]["n_queries"] for lg in logs) > 0), "problems": int(chain)}
    n_q = int(q.sum())
    counts_ok = external is not None and external.get("worlds") == n_worlds and external.get("queries") == n_q
    out["K2_independent"] = {"passed": bool(external is not None and external.get("passed") is True and counts_ok), "report": external}
    gen_ok = (external_gen is not None and external_gen.get("passed") is True and external_gen.get("worlds") == n_worlds
              and external_gen.get("queries") == n_q and external_gen.get("fast_events") == int(s["fast"].sum()))
    out["K2b_generator"] = {"passed": bool(gen_ok), "report": external_gen}
    replay = sum(len(lg["checks"]["replay_mismatch"]) for lg in logs)
    out["K3_restore_replay"] = {"passed": bool(replay == 0 and all(lg["checks"]["n_checkpoints"] > 1 for lg in logs)), "problems": int(replay),
                                "checkpoints_replayed": int(sum(lg["checks"]["n_checkpoints"] - 1 for lg in logs))}
    stable = q & (ev["relocated"] == 0)
    reloc = s["relocated"]
    checks = {
        "decoy_iff_shown_differs": bool(((ev["shown"][q] != ev["answer"][q]) == (ev["decoy"][q] == 1)).all()),
        "stable_answer_is_episode0_value": bool((ev["answer"][stable] == ev["tok_before"][stable]).all()),
        "relocated_answer_is_new_value": bool((ev["answer"][reloc] == ev["tok_after"][reloc]).all() and (ev["tok_after"][reloc] != ev["tok_before"][reloc]).all()),
        "query_is_first_arrival": bool((ev["first_ok"][q] == 1).all()),
        "all_sets_present": bool(s["decoy"].any() and s["clean"].any() and s["fast"].any()),
    }
    out["K4_labels"] = {"passed": all(checks.values()), **checks}
    if stage is not None:
        have = {k: int(s[k].sum()) for k in EXPECTED_PER_100}
        band = {k: [EXPECTED_PER_100[k] * n_worlds / 100 * (1 - SAMPLE_BAND[k]), EXPECTED_PER_100[k] * n_worlds / 100 * (1 + SAMPLE_BAND[k])] for k in EXPECTED_PER_100}
        out["K5_samples"] = {"passed": all(band[k][0] <= have[k] <= band[k][1] for k in have), "have": have, "band": band}
    out["K6_events_match_log"] = log_linkage(ev, logs)
    if offsets is not None or stage is not None:  # a registered stage must carry its offset files
        out["K7_offsets_same_events"] = offsets_same_events(ev, offsets)
    out["valid"] = all(v["passed"] for v in out.values() if isinstance(v, dict))
    return out


def rate(ev, mask, col):
    return float(ev[col][mask].mean()) if mask.any() else None


def recovery_curve(ev: dict[str, np.ndarray], mask: np.ndarray) -> dict[str, Any]:
    curve = {}
    first = None
    for e in sorted(set(ev["episode"][mask].tolist())):
        m = mask & (ev["episode"] == e)
        row = {p: float(correct(ev, p)[m].mean()) for p in ("C", "L", "G", "GNR", "MODE")} | {"n": int(m.sum())}
        curve[str(e)] = row
        if first is None and row["G"] > row["C"]:
            first = e
    return {"by_episode": curve, "first_episode_G_beats_C": first}


def evaluate(ev: dict[str, np.ndarray], logs: Sequence[dict[str, Any]], *, stage: str | None, n_worlds: int,
             external: dict[str, Any] | None, external_gen: dict[str, Any] | None,
             offsets: dict[int, dict[str, np.ndarray]] | None = None) -> dict[str, Any]:
    s = event_sets(ev)
    legal = legality(ev, logs, stage=stage, n_worlds=n_worlds, external=external, external_gen=external_gen, offsets=offsets)
    desc = {name: paired(ev, s[sel], a, b) for name, sel, a, b in COMPARISONS}
    acc = {name: {p: float(correct(ev, p)[m].mean()) for p in POLICIES if (ev[f"pred_{p}"][m] >= 0).all()} | {"n": int(m.sum())} for name, m in s.items() if m.any()}
    items = {k: int(sum(lg["items"][k] for lg in logs)) for k in logs[0]["items"]} if logs else {}
    diag = {
        "accuracy": acc,
        "D2_U0_won_by_past": rate(ev, s["fast_e1"], "u0_past"),
        "D4_recovery": recovery_curve(ev, s["relocated"]),
        "D5_SR_fast_rate_queries": rate(ev, s["query"], "sr_fast"),
        "D5_SR_fast_rate_fast": rate(ev, s["fast"], "sr_fast"),
        "D8_items": items,
        "D8_query_tie_rate": rate(ev, s["query"] & (ev["g_slow"] == 1), "query_tie"),
        "D8_slow_hit_rate": rate(ev, s["query"], "g_slow"),
        "D8_slow_hit_on_cell": rate(ev, s["query"] & (ev["g_slow"] == 1), "g_item_on_cell"),
    }
    off = {}
    for k, evk in (offsets or {}).items():
        sk = event_sets(evk)
        off[str(k)] = {name: paired(evk, sk[sel], a, b) for name, sel, a, b in OFFSET_COMPARISONS}
    return {"valid": legal["valid"], "legality": legal, "descriptive": desc, "offsets": off, "diagnostics": diag,
            "n_comparisons": N_COMPARISONS}


def invalidated(result: dict[str, Any], reason: str) -> dict[str, Any]:
    out = dict(result)
    out["valid"] = False
    out["invalid_reason"] = reason
    return out
