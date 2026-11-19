"""Independent recomputation of V9-mini paper figures 1, 3, 4 and 5.

Does not import fig_data, make_figures, make_tables or check_draft.
Figure 1 is regenerated with ainerzero.v9.mini.world.make_layout and
ainerzero.v9.mini.evaluate.make_tasks. Figures 3–5 are pooled from the
registered episodes.json files. Every printed number is computed here.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(ROOT / "src"))

from ainerzero.v9.mini import evaluate as evaluate_mod  # noqa: E402
from ainerzero.v9.mini import world as world_mod  # noqa: E402

PAPER = ROOT / "reports/V9-MINI/paper"
FIG_JSON = PAPER / "figures" / "fig_data.json"
SHORT_BINS = ((4, 5), (6, 7), (8, 10))
LONG_BINS = ((20, 20), (21, 22), (23, 25), (26, 29), (30, 99))
FIG4_ARMS = ("oracle", "map_hybrid_self", "map_analytic", "latent_topo", "latent_attn", "random")
FIG5_ARMS = ("oracle", "map_hybrid", "map_hybrid_self", "map_memory", "map_analytic")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_runs(milestone: str, world: str) -> list[dict]:
    runs = []
    for seed in range(5):
        path = ROOT / f"reports/V9-MINI/{milestone}/{world}-s{seed}/episodes.json"
        runs.append(json.loads(path.read_text()))
    return runs


def episodes(runs, arm, pred):
    return [(i, rec) for i, ep in enumerate(runs) for rec in ep[arm] if pred(rec)]


def cluster_interval(items):
    """Pooled rate and 95% percentile interval. Clusters are (run, layout_seed).

    Cluster ids are the rank of the sorted unique keys. 4000 resamples with
    numpy.random.default_rng(0), freshly seeded for this call.
    """
    keys = [(i, rec["layout_seed"]) for i, rec in items]
    y = np.array([rec["success"] for _, rec in items], dtype=float)
    order = {key: j for j, key in enumerate(sorted(set(keys)))}
    group = np.array([order[key] for key in keys])
    n_groups = len(order)
    success_sum = np.bincount(group, weights=y, minlength=n_groups)
    counts = np.bincount(group, minlength=n_groups).astype(float)
    draw = np.random.default_rng(0).integers(0, n_groups, size=(4000, n_groups))
    rates = success_sum[draw].sum(1) / counts[draw].sum(1)
    lo, hi = np.percentile(rates, [2.5, 97.5])
    return {
        "rate": float(y.mean()),
        "lo": float(lo),
        "hi": float(hi),
        "n": int(y.size),
        "clusters": int(n_groups),
    }


def fig3(runs_by_world):
    out = {}
    for world, runs in runs_by_world.items():
        out[world] = {}
        for arm in runs[0]:
            out[world][arm] = {}
            for kind in ("short", "long"):
                out[world][arm][kind] = cluster_interval(
                    episodes(runs, arm, lambda rec, k=kind: rec["kind"] == k)
                )
    return out


def fig4(runs_by_world):
    out = {}
    for world, runs in runs_by_world.items():
        bins = []
        for lo, hi in SHORT_BINS + LONG_BINS:
            chosen = episodes(runs, "oracle", lambda rec, a=lo, b=hi: a <= rec["d_star"] <= b)
            distances = [rec["d_star"] for _, rec in chosen]
            rates = {}
            for arm in FIG4_ARMS:
                vals = [rec["success"] for _, rec in episodes(
                    runs, arm, lambda rec, a=lo, b=hi: a <= rec["d_star"] <= b
                )]
                rates[arm] = float(np.mean(vals))
            bins.append({
                "bin": [lo, hi],
                "n": len(distances),
                "mean_d": float(np.mean(distances)),
                "rate": rates,
            })
        out[world] = bins
    return out


def fig5(runs):
    out = {}
    for name, flag in (("lost", True), ("localized", False)):
        keep = [
            (i, j)
            for i, ep in enumerate(runs)
            for j, rec in enumerate(ep["map_hybrid"])
            if rec["kind"] == "long" and bool(rec["lost_at_start"]) is flag
        ]
        out[name] = {
            "n": len(keep),
            "clusters": len({(i, runs[i]["map_hybrid"][j]["layout_seed"]) for i, j in keep}),
            "rate": {
                arm: float(np.mean([runs[i][arm][j]["success"] for i, j in keep]))
                for arm in FIG5_ARMS
            },
        }
    long_rows = [rec for ep in runs for rec in ep["map_hybrid"] if rec["kind"] == "long"]
    failures = [rec for rec in long_rows if not rec["success"]]
    out["share_lost_among_long"] = out["lost"]["n"] / len(long_rows)
    out["share_lost_among_map_hybrid_long_failures"] = float(
        np.mean([bool(rec["lost_at_start"]) for rec in failures])
    )
    out["n_long"] = len(long_rows)
    out["n_long_failures"] = len(failures)
    all_rows = [rec for ep in runs for rec in ep["map_hybrid"]]
    out["n_all"] = len(all_rows)
    out["share_lost_among_all"] = float(np.mean([bool(rec["lost_at_start"]) for rec in all_rows]))
    lost_flag_values = sorted({repr(rec["lost_at_start"]) for rec in all_rows})
    out["lost_at_start_values"] = lost_flag_values
    return out


def walk_mismatches(got, exp, path, mismatches):
    if isinstance(exp, dict):
        if not isinstance(got, dict):
            mismatches.append((path, got, exp))
            return
        for key in exp:
            walk_mismatches(got.get(key, "<MISSING>"), exp[key], f"{path}.{key}", mismatches)
        return
    if isinstance(exp, list):
        if got != exp:
            mismatches.append((path, got, exp))
        return
    if isinstance(exp, float):
        if got != exp:
            mismatches.append((path, got, exp))
        return
    if got != exp:
        mismatches.append((path, got, exp))


def ice_components(grid, ice_value):
    height, width = grid.shape
    seen = np.zeros_like(grid, dtype=bool)
    count = 0
    cells = 0
    for y in range(height):
        for x in range(width):
            if grid[y, x] != ice_value or seen[y, x]:
                continue
            count += 1
            stack = [(y, x)]
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                cells += 1
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < height and 0 <= nx < width and not seen[ny, nx] and grid[ny, nx] == ice_value:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
    return count, cells


def regenerate_fig1(published):
    result = json.loads((ROOT / "reports/V9-MINI/M5/m2-s0/result.json").read_text())
    eval_seed0 = result["meta"]["eval_seed0"]
    cfg = world_mod.Config(**result["meta"]["world"])
    preset = result["meta"]["preset"]
    runs = load_runs("M5", "m2")
    run0 = runs[0]
    n_layouts = len({rec["layout_seed"] for rec in run0["oracle"]})
    chosen = None
    satisfying = []
    for index in range(n_layouts):
        seed = eval_seed0 + index
        idxs = [j for j, rec in enumerate(run0["oracle"]) if rec["layout_seed"] == seed]
        hits = [
            j for j in idxs
            if run0["oracle"][j]["kind"] == "long"
            and run0["oracle"][j]["law_relevant"]
            and run0["map_hybrid_self"][j]["success"]
            and not run0["latent_topo"][j]["success"]
        ]
        if hits:
            satisfying.append({"index": index, "seed": seed, "n_hits": len(hits), "first_hit": hits[0]})
            if chosen is None:
                chosen = (index, seed, idxs, hits)
    index, seed, idxs, hits = chosen
    tasks = [
        task for task in evaluate_mod.make_tasks(
            cfg, index + 1, preset["prefix"], preset["n_short"], preset["n_long"], eval_seed0=eval_seed0
        )
        if task["layout_seed"] == seed
    ]
    if len(tasks) != len(idxs):
        episode_mismatches.append({"len_tasks": len(tasks), "len_logged": len(idxs)})
    layout = world_mod.make_layout(seed, cfg)
    highlight = idxs.index(hits[0])
    goal = tasks[highlight]["goal"]
    arms = ("map_hybrid_self", "map_analytic", "latent_topo", "latent_attn")
    goals = []
    episode_mismatches = []
    for task, j in zip(tasks, idxs):
        logged = run0["oracle"][j]
        if (task["kind"], task["d_star"], bool(task["law_relevant"])) != (
            logged["kind"], logged["d_star"], bool(logged["law_relevant"])
        ):
            episode_mismatches.append({"j": j, "task": {
                "kind": task["kind"], "d_star": task["d_star"], "law_relevant": bool(task["law_relevant"])
            }, "oracle": {
                "kind": logged["kind"], "d_star": logged["d_star"], "law_relevant": bool(logged["law_relevant"])
            }})
        if logged["success"] != 1:
            episode_mismatches.append({"j": j, "oracle_success": logged["success"]})
        for arm in arms:
            if run0[arm][j]["layout_seed"] != seed or run0[arm][j]["d_star"] != task["d_star"]:
                episode_mismatches.append({"j": j, "arm": arm, "layout_seed": run0[arm][j]["layout_seed"]})
        goals.append({
            "pose": list(task["goal"]),
            "kind": task["kind"],
            "d_star": task["d_star"],
            "law_relevant": bool(task["law_relevant"]),
            "success": {arm: run0[arm][j]["success"] for arm in arms},
        })
    cells = [(g["pose"][0], g["pose"][1]) for g in goals]
    cell_counts = Counter(cells)
    shared = [cell for cell, n in cell_counts.items() if n > 1]
    grid = layout.grid
    ice_n, ice_cells = ice_components(grid, world_mod.ICE)
    got = {
        "run": "M5/m2-s0",
        "layout_seed": seed,
        "layout_index": index,
        "grid": grid.tolist(),
        "portal_to": [[list(a), list(b)] for a, b in layout.portal_to.items()],
        "cell_types": {
            "wall": world_mod.WALL, "oob": world_mod.OOB, "ice": world_mod.ICE,
            "portal": world_mod.PORTAL, "floor0": world_mod.FLOOR0,
        },
        "prefix_poses": [list(p) for p in tasks[0]["prefix_poses"]],
        "start": list(tasks[0]["start"]),
        "goals": goals,
        "highlight_goal": highlight,
        "goal_view": world_mod.ego_view(layout, goal).tolist(),
    }
    field_mismatches = []
    for key in ("run", "layout_seed", "layout_index", "grid", "portal_to", "cell_types",
                "prefix_poses", "start", "goals", "highlight_goal", "goal_view"):
        if got[key] != published[key]:
            if key in ("grid", "prefix_poses", "goal_view", "goals", "portal_to"):
                field_mismatches.append(key)
            else:
                field_mismatches.append({"key": key, "got": got[key], "published": published[key]})
    prefix_steps = len(got["prefix_poses"]) - 1
    starred = goals[highlight]
    return {
        "eval_seed0": eval_seed0,
        "world_cfg": result["meta"]["world"],
        "preset_prefix": preset["prefix"],
        "preset_n_short": preset["n_short"],
        "preset_n_long": preset["n_long"],
        "n_layouts": n_layouts,
        "n_maps_satisfying_rule": len(satisfying),
        "satisfying_seeds": [row["seed"] for row in satisfying],
        "chosen_is_first": satisfying[0]["seed"] == seed,
        "layout_seed": seed,
        "layout_index": index,
        "n_tasks_regenerated": len(tasks),
        "n_logged_for_seed": len(idxs),
        "episode_mismatches": episode_mismatches,
        "field_mismatches": field_mismatches,
        "grid_shape": list(grid.shape),
        "n_portal_pairs": len(layout.portal_to),
        "n_portal_cells": int((grid == world_mod.PORTAL).sum()),
        "n_ice_components": ice_n,
        "n_ice_cells": ice_cells,
        "n_goals": len(goals),
        "n_short": sum(g["kind"] == "short" for g in goals),
        "n_long": sum(g["kind"] == "long" for g in goals),
        "shared_cells": shared,
        "n_goals_on_shared_cells": sum(cell_counts[c] for c in shared),
        "prefix_steps": prefix_steps,
        "start_is_last_prefix_pose": got["start"] == got["prefix_poses"][-1],
        "goal_view_shape": [len(got["goal_view"]), len(got["goal_view"][0])],
        "highlight_goal": highlight,
        "highlight_d_star": starred["d_star"],
        "highlight_law_relevant": starred["law_relevant"],
        "highlight_kind": starred["kind"],
        "highlight_success": starred["success"],
        "highlight_pose": starred["pose"],
        "published_selection_rule": published.get("selection_rule"),
    }


def distance_gaps(runs_by_world):
    """Count d* values that the figure-4 bins do not cover."""
    out = {}
    for world, runs in runs_by_world.items():
        counts = Counter(rec["d_star"] for rec in runs[0]["oracle"] for _ in [0])
        # recount across runs
        counts = Counter()
        for ep in runs:
            for rec in ep["oracle"]:
                counts[rec["d_star"]] += 1
        between = sum(n for d, n in counts.items() if 11 <= d <= 19)
        below = sum(n for d, n in counts.items() if d < 4)
        above = sum(n for d, n in counts.items() if d > 99)
        out[world] = {
            "n_episodes": sum(counts.values()),
            "n_dstar_11_to_19": between,
            "n_dstar_below_4": below,
            "n_dstar_above_99": above,
            "min_d": min(counts),
            "max_d": max(counts),
        }
    return out


def caption_facts(f3, f4, f5):
    """Print the exact quantities named by the new captions and sentences."""
    lines = []
    m1_long = {arm: f3["m1"][arm]["long"]["rate"] for arm in ("map_hybrid_self", "map_hybrid", "map_analytic")}
    lines.append(f"fig3_m1_long_map_hybrid_self {m1_long['map_hybrid_self']:.10f}")
    lines.append(f"fig3_m1_long_map_hybrid {m1_long['map_hybrid']:.10f}")
    lines.append(f"fig3_m1_long_map_analytic {m1_long['map_analytic']:.10f}")
    lines.append(f"fig3_m1_three_map_agents_equal {len(set(m1_long.values())) == 1}")
    for world in ("m1", "m2"):
        lines.append(
            f"fig3_{world}_oracle_short_n {f3[world]['oracle']['short']['n']} "
            f"long_n {f3[world]['oracle']['long']['n']} "
            f"long_clusters {f3[world]['oracle']['long']['clusters']}"
        )
    for world in ("m1", "m2"):
        topo_short = f4[world][0]["rate"]["latent_topo"]
        long_bins = f4[world][3:]
        topo_long = [b["rate"]["latent_topo"] for b in long_bins]
        lines.append(f"fig4_{world}_latent_topo_bin_4_5 {topo_short:.10f}")
        lines.append(f"fig4_{world}_latent_topo_long_max {max(topo_long):.10f}")
        lines.append(f"fig4_{world}_latent_topo_long_min {min(topo_long):.10f}")
        for b in f4[world]:
            label = f"{b['bin'][0]}-{b['bin'][1]}"
            lines.append(
                f"fig4_{world}_bin {label} n {b['n']} mean_d {b['mean_d']:.10f} "
                f"map_hybrid_self {b['rate']['map_hybrid_self']:.10f} "
                f"map_analytic {b['rate']['map_analytic']:.10f} "
                f"latent_topo {b['rate']['latent_topo']:.10f} "
                f"oracle {b['rate']['oracle']:.10f} "
                f"latent_attn {b['rate']['latent_attn']:.10f} "
                f"random {b['rate']['random']:.10f}"
            )
        coincide = all(b["rate"]["map_hybrid_self"] == b["rate"]["map_analytic"] for b in f4[world])
        oracle_one = all(b["rate"]["oracle"] == 1.0 for b in f4[world])
        ns = [b["n"] for b in f4[world]]
        lines.append(f"fig4_{world}_self_equals_analytic_all_bins {coincide}")
        lines.append(f"fig4_{world}_oracle_all_bins_1 {oracle_one}")
        lines.append(f"fig4_{world}_n_min {min(ns)} n_max {max(ns)} ns {ns}")
    # bins other than 26-29 and >=30 for the m1 caption range
    m1_main = [b["n"] for b in f4["m1"] if b["bin"] not in ([26, 29], [30, 99])]
    lines.append(f"fig4_m1_n_excluding_26_29_and_ge30 min {min(m1_main)} max {max(m1_main)} values {m1_main}")
    lines.append(f"fig4_m2_n_min {min(b['n'] for b in f4['m2'])} max {max(b['n'] for b in f4['m2'])}")
    b20 = next(b for b in f4["m2"] if b["bin"] == [20, 20])
    b30 = next(b for b in f4["m2"] if b["bin"] == [30, 99])
    lines.append(
        f"fig4_m2_d20 map_hybrid_self {b20['rate']['map_hybrid_self']:.10f} "
        f"map_analytic {b20['rate']['map_analytic']:.10f}"
    )
    lines.append(
        f"fig4_m2_ge30 map_hybrid_self {b30['rate']['map_hybrid_self']:.10f} "
        f"map_analytic {b30['rate']['map_analytic']:.10f}"
    )
    gap20 = b20["rate"]["map_hybrid_self"] - b20["rate"]["map_analytic"]
    gap30 = b30["rate"]["map_hybrid_self"] - b30["rate"]["map_analytic"]
    lines.append(f"fig4_m2_gap_d20 {gap20:.10f} gap_ge30 {gap30:.10f} widens {gap30 > gap20}")
    # monotonic widening across long bins
    prev = None
    widen_steps = []
    for b in f4["m2"][3:]:
        gap = b["rate"]["map_hybrid_self"] - b["rate"]["map_analytic"]
        if prev is not None:
            widen_steps.append(gap >= prev)
        prev = gap
        lines.append(f"fig4_m2_gap_bin {b['bin'][0]}-{b['bin'][1]} {gap:.10f}")
    lines.append(f"fig4_m2_gap_nondecreasing {all(widen_steps)}")
    lines.append(f"fig5_lost_n {f5['lost']['n']} clusters {f5['lost']['clusters']}")
    lines.append(f"fig5_localized_n {f5['localized']['n']} clusters {f5['localized']['clusters']}")
    lines.append(f"fig5_n_long {f5['n_long']} sum_split {f5['lost']['n'] + f5['localized']['n']}")
    lines.append(f"fig5_share_lost_among_long {f5['share_lost_among_long']:.10f}")
    lines.append(
        f"fig5_share_lost_among_long_pct {100.0 * f5['lost']['n'] / f5['n_long']:.10f}"
    )
    lines.append(
        f"fig5_share_lost_among_map_hybrid_long_failures {f5['share_lost_among_map_hybrid_long_failures']:.10f}"
    )
    lines.append(f"fig5_share_lost_among_all {f5['share_lost_among_all']:.10f}")
    lines.append(f"fig5_n_all {f5['n_all']} n_long_failures {f5['n_long_failures']}")
    for name in ("lost", "localized"):
        for arm, rate in f5[name]["rate"].items():
            lines.append(f"fig5_{name}_{arm} {rate:.10f}")
    lost_h = f5["lost"]["rate"]["map_hybrid"]
    loc_h = f5["localized"]["rate"]["map_hybrid"]
    lost_a = f5["lost"]["rate"]["map_analytic"]
    loc_a = f5["localized"]["rate"]["map_analytic"]
    lines.append(f"fig5_gain_lost {lost_h - lost_a:.10f} gain_localized {loc_h - loc_a:.10f}")
    lines.append(f"fig5_gain_larger_when_lost {lost_h - lost_a > loc_h - loc_a}")
    # short/long latent_topo and latent_attn ranges named in §6.3 near the new sentence
    for world in ("m1", "m2"):
        lines.append(
            f"fig3_{world}_latent_topo_short {f3[world]['latent_topo']['short']['rate']:.10f} "
            f"long {f3[world]['latent_topo']['long']['rate']:.10f}"
        )
        lines.append(
            f"fig3_{world}_latent_attn_short {f3[world]['latent_attn']['short']['rate']:.10f} "
            f"long {f3[world]['latent_attn']['long']['rate']:.10f}"
        )
        lines.append(
            f"fig3_{world}_random_short {f3[world]['random']['short']['rate']:.10f} "
            f"long {f3[world]['random']['long']['rate']:.10f}"
        )
    return lines


def main() -> int:
    print(f"python {sys.version.split()[0]}")
    print(f"numpy {np.__version__}")
    published = json.loads(FIG_JSON.read_text())
    print(f"fig_data_json_sha256 {sha256_file(FIG_JSON)}")
    id_paths = []
    for milestone, worlds in (("M5", ("m1", "m2")), ("M4", ("m2",))):
        for world in worlds:
            for seed in range(5):
                path = ROOT / f"reports/V9-MINI/{milestone}/{world}-s{seed}/episodes.json"
                id_paths.append(path)
    id_paths.append(ROOT / "reports/V9-MINI/M5/m2-s0/result.json")
    for path in id_paths:
        print(f"sha256 {path.relative_to(ROOT)} {sha256_file(path)}")

    m5 = {"m1": load_runs("M5", "m1"), "m2": load_runs("M5", "m2")}
    m4_m2 = load_runs("M4", "m2")
    print(f"m5_m1_arms {sorted(m5['m1'][0])}")
    print(f"m5_m2_arms {sorted(m5['m2'][0])}")
    print(f"m4_m2_arms {sorted(m4_m2[0])}")

    # Same task identity across arms, which the figure-5 split assumes.
    align_bad = 0
    for ep in m4_m2:
        n = len(ep["map_hybrid"])
        for arm in FIG5_ARMS:
            if len(ep[arm]) != n:
                align_bad += 1
                continue
            for j in range(n):
                a, b = ep["map_hybrid"][j], ep[arm][j]
                if (a["layout_seed"], a["kind"], a["d_star"]) != (b["layout_seed"], b["kind"], b["d_star"]):
                    align_bad += 1
    print(f"fig5_arm_alignment_mismatches {align_bad}")

    got3 = fig3(m5)
    got4 = fig4(m5)
    got5 = fig5(m4_m2)
    mismatches = []
    walk_mismatches(got3, published["fig3"], "fig3", mismatches)
    walk_mismatches(got4, published["fig4"], "fig4", mismatches)
    # fig5 published object has no n_long extras; compare the published keys only
    published5 = {
        "lost": published["fig5"]["lost"],
        "localized": published["fig5"]["localized"],
        "share_lost_among_long": published["fig5"]["share_lost_among_long"],
        "share_lost_among_map_hybrid_long_failures": published["fig5"]["share_lost_among_map_hybrid_long_failures"],
    }
    got5_cmp = {
        "lost": got5["lost"],
        "localized": got5["localized"],
        "share_lost_among_long": got5["share_lost_among_long"],
        "share_lost_among_map_hybrid_long_failures": got5["share_lost_among_map_hybrid_long_failures"],
    }
    walk_mismatches(got5_cmp, published5, "fig5", mismatches)
    print(f"fig345_mismatches {len(mismatches)}")
    for path, got, exp in mismatches[:40]:
        print(f"MISMATCH {path} got {got!r} published {exp!r}")

    gaps = distance_gaps(m5)
    for world, info in gaps.items():
        print(
            f"dstar_coverage {world} n {info['n_episodes']} min {info['min_d']} max {info['max_d']} "
            f"below4 {info['n_dstar_below_4']} between_11_19 {info['n_dstar_11_to_19']} above99 {info['n_dstar_above_99']}"
        )
    print("CAPTION")
    for line in caption_facts(got3, got4, got5):
        print(line)

    print("FIG1")
    info = regenerate_fig1(published["fig1"])
    for key, value in info.items():
        if key == "satisfying_seeds":
            print(f"fig1_satisfying_seeds {value}")
        elif key == "episode_mismatches":
            print(f"fig1_episode_mismatches {len(value)}")
            for row in value[:20]:
                print(f"FIG1_EP {row}")
        elif key == "field_mismatches":
            print(f"fig1_field_mismatches {value}")
        else:
            print(f"fig1_{key} {value}")
    return 0 if not mismatches and not info["field_mismatches"] and not info["episode_mismatches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
