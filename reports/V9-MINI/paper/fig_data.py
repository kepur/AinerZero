"""Numbers behind the figures of the V9-mini paper draft. Reads only the registered runs (M4, M5).

Writes reports/V9-MINI/paper/figures/fig_data.json and prints a readable summary. Drawing is a separate
step (make_figures.py, plotting environment), so every plotted number can be checked here without matplotlib.

- fig1: one M5 held-out map of world m2 (run m2-s0), regenerated from its seed with the project's own task
  generator, with the exploration prefix, start and goals. The map is the first one of that run (lowest seed)
  that has a law-relevant long goal on which map_hybrid_self succeeded and latent_topo failed; it is an
  illustration, chosen by that rule, not a typical case. The regenerated tasks are checked against the
  registered episodes.json (layout seed, kind, d*, law-relevant flag, oracle success) before use.
- fig3: M5 short- and long-goal success per agent and world, pooled over the five runs, with 95% cluster-bootstrap
  intervals (clusters = run x held-out map, 4000 resamples, default_rng(0)). Descriptive; the gates are in Tables 2/4.
- fig4: M5 success by shortest-path distance d* in bins, pooled over the five runs.
- fig5: M4 world m2, long goals split by whether map_hybrid was still lost when the prefix ended.

Usage: .venv/bin/python reports/V9-MINI/paper/fig_data.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "figures" / "fig_data.json"
WORLDS = ("m1", "m2")
SHORT_BINS = ((4, 5), (6, 7), (8, 10))
LONG_BINS = ((20, 20), (21, 22), (23, 25), (26, 29), (30, 99))
FIG4_ARMS = ("oracle", "map_hybrid_self", "map_analytic", "latent_topo", "latent_attn", "random")
FIG5_ARMS = ("oracle", "map_hybrid", "map_hybrid_self", "map_memory", "map_analytic")


def load(m: str, w: str):
    return [json.loads((ROOT / f"reports/V9-MINI/{m}/{w}-s{s}/episodes.json").read_text()) for s in range(5)]


def rows(runs, arm, pred=lambda r: True):
    """(run index, record) for every episode of an arm that satisfies pred, in registered order."""
    return [(i, r) for i, e in enumerate(runs) for r in e[arm] if pred(r)]


def cluster_ci(items) -> tuple[float, float, float, int, int]:
    """Pooled success rate and its 95% cluster-bootstrap interval; clusters are (run, layout seed)."""
    keys = [(i, r["layout_seed"]) for i, r in items]
    y = np.array([r["success"] for _, r in items], float)
    uniq = {k: j for j, k in enumerate(sorted(set(keys)))}
    g = np.array([uniq[k] for k in keys])
    s1 = np.bincount(g, weights=y, minlength=len(uniq))
    c = np.bincount(g, minlength=len(uniq)).astype(float)
    bi = np.random.default_rng(0).integers(0, len(uniq), (4000, len(uniq)))
    lo, hi = np.percentile(s1[bi].sum(1) / c[bi].sum(1), [2.5, 97.5])
    return float(y.mean()), float(lo), float(hi), len(y), len(uniq)


def fig1() -> dict:
    from ainerzero.v9.mini import evaluate as E
    from ainerzero.v9.mini import world as W

    res = json.loads((ROOT / "reports/V9-MINI/M5/m2-s0/result.json").read_text())
    eval_seed0 = res["meta"]["eval_seed0"]
    cfg = W.Config(**res["meta"]["world"])
    pre = res["meta"]["preset"]
    e = load("M5", "m2")[0]
    n_layouts = len({r["layout_seed"] for r in e["oracle"]})

    def rule_hits(seed):
        idx = [j for j, r in enumerate(e["oracle"]) if r["layout_seed"] == seed]
        return idx, [j for j in idx if e["oracle"][j]["kind"] == "long" and e["oracle"][j]["law_relevant"]
                     and e["map_hybrid_self"][j]["success"] and not e["latent_topo"][j]["success"]]

    n_satisfying = sum(bool(rule_hits(eval_seed0 + i)[1]) for i in range(n_layouts))
    for i in range(n_layouts):
        seed = eval_seed0 + i
        idx, hits = rule_hits(seed)
        if hits:
            break
    else:
        raise SystemExit("no map satisfies the selection rule")
    # make_tasks draws layout i with rng seed eval_seed0 + 101 * i, so generate the first i + 1 maps.
    tasks = [t for t in E.make_tasks(cfg, i + 1, pre["prefix"], pre["n_short"], pre["n_long"], eval_seed0=eval_seed0)
             if t["layout_seed"] == seed]
    assert len(tasks) == len(idx), (len(tasks), len(idx))
    for t, j in zip(tasks, idx):
        r = e["oracle"][j]
        assert (t["kind"], t["d_star"], bool(t["law_relevant"]), r["success"]) == (r["kind"], r["d_star"], bool(r["law_relevant"]), 1), (t, r)
    layout = W.make_layout(seed, cfg)
    k = idx.index(hits[0])
    goal = tasks[k]["goal"]
    return {
        "run": "M5/m2-s0", "layout_seed": seed, "layout_index": i, "n_layouts": n_layouts, "n_satisfying_rule": n_satisfying,
        "selection_rule": "first map of M5/m2-s0 with a "
        "law-relevant long goal where map_hybrid_self succeeded and latent_topo failed",
        "grid": layout.grid.tolist(), "portal_to": [[list(a), list(b)] for a, b in layout.portal_to.items()],
        "cell_types": {"wall": W.WALL, "oob": W.OOB, "ice": W.ICE, "portal": W.PORTAL, "floor0": W.FLOOR0},
        "prefix_poses": [list(p) for p in tasks[0]["prefix_poses"]],
        "start": list(tasks[0]["start"]),
        "goals": [{"pose": list(t["goal"]), "kind": t["kind"], "d_star": t["d_star"], "law_relevant": bool(t["law_relevant"]),
                   "success": {a: e[a][j]["success"] for a in ("map_hybrid_self", "map_analytic", "latent_topo", "latent_attn")}}
                  for t, j in zip(tasks, idx)],
        "highlight_goal": k,
        "goal_view": W.ego_view(layout, goal).tolist(),
    }


def fig3() -> dict:
    out = {}
    for w in WORLDS:
        runs = load("M5", w)
        out[w] = {}
        for arm in runs[0]:
            out[w][arm] = {}
            for kind in ("short", "long"):
                p, lo, hi, n, ncl = cluster_ci(rows(runs, arm, lambda r, k=kind: r["kind"] == k))
                out[w][arm][kind] = {"rate": p, "lo": lo, "hi": hi, "n": n, "clusters": ncl}
    return out


def fig4() -> dict:
    out = {}
    for w in WORLDS:
        runs = load("M5", w)
        out[w + "_n_between_short_and_long"] = len(rows(runs, "oracle", lambda r: SHORT_BINS[-1][1] < r["d_star"] < LONG_BINS[0][0]))
        out[w] = []
        for a, b in SHORT_BINS + LONG_BINS:
            sel = lambda r, a=a, b=b: a <= r["d_star"] <= b
            ds = [r["d_star"] for _, r in rows(runs, "oracle", sel)]
            out[w].append({"bin": [a, b], "n": len(ds), "mean_d": float(np.mean(ds)),
                           "rate": {arm: float(np.mean([r["success"] for _, r in rows(runs, arm, sel)])) for arm in FIG4_ARMS}})
    return out


def fig5() -> dict:
    runs = load("M4", "m2")
    out = {}
    for name, flag in (("lost", True), ("localized", False)):
        # The split is defined by map_hybrid's own flag and applied to every agent on the same episodes.
        keep = [(i, j) for i, e in enumerate(runs) for j, r in enumerate(e["map_hybrid"])
                if r["kind"] == "long" and bool(r["lost_at_start"]) == flag]
        out[name] = {"n": len(keep), "clusters": len({(i, runs[i]["map_hybrid"][j]["layout_seed"]) for i, j in keep}),
                     "rate": {a: float(np.mean([runs[i][a][j]["success"] for i, j in keep])) for a in FIG5_ARMS}}
    n_long = sum(1 for e in runs for r in e["map_hybrid"] if r["kind"] == "long")
    fail = [r for e in runs for r in e["map_hybrid"] if r["kind"] == "long" and not r["success"]]
    out["share_lost_among_long"] = out["lost"]["n"] / n_long
    out["share_lost_among_map_hybrid_long_failures"] = float(np.mean([bool(r["lost_at_start"]) for r in fail]))
    return out


def main() -> int:
    data = {"fig1": fig1(), "fig3": fig3(), "fig4": fig4(), "fig5": fig5()}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1))
    f1 = data["fig1"]
    print(f"fig1: {f1['n_satisfying_rule']} of {f1['n_layouts']} maps of the run satisfy the selection rule")
    print(f"fig4: episodes with d* between the short and long ranges: m1 {data['fig4']['m1_n_between_short_and_long']}, "
          f"m2 {data['fig4']['m2_n_between_short_and_long']}")
    print(f"fig1: {f1['run']} layout {f1['layout_seed']} (index {f1['layout_index']}), {len(f1['goals'])} goals, "
          f"highlight goal {f1['highlight_goal']}: {f1['goals'][f1['highlight_goal']]}")
    for w in WORLDS:
        print(f"\nfig3 [{w}] success (pooled over 5 runs) [95% cluster-bootstrap interval]")
        for arm, v in data["fig3"][w].items():
            s, l = v["short"], v["long"]
            print(f"  {arm:18s} short {s['rate']:.3f} [{s['lo']:.3f}, {s['hi']:.3f}] n={s['n']}   "
                  f"long {l['rate']:.3f} [{l['lo']:.3f}, {l['hi']:.3f}] n={l['n']} clusters={l['clusters']}")
    for w in WORLDS:
        print(f"\nfig4 [{w}] success by d* bin")
        print("  bin      n    mean_d  " + "  ".join(f"{a[:14]:>14s}" for a in FIG4_ARMS))
        for b in data["fig4"][w]:
            print(f"  {b['bin'][0]:>2d}-{b['bin'][1]:<3d} {b['n']:5d}  {b['mean_d']:6.2f}  "
                  + "  ".join(f"{b['rate'][a]:14.3f}" for a in FIG4_ARMS))
    f5 = data["fig5"]
    print(f"\nfig5 M4 m2 long goals split by map_hybrid lost at the end of the prefix: "
          f"share lost {f5['share_lost_among_long']:.3f}; share of map_hybrid long failures that started lost "
          f"{f5['share_lost_among_map_hybrid_long_failures']:.3f}")
    for name in ("lost", "localized"):
        print(f"  {name:9s} n={f5[name]['n']} clusters={f5[name]['clusters']}  "
              + "  ".join(f"{a} {v:.3f}" for a, v in f5[name]["rate"].items()))
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
