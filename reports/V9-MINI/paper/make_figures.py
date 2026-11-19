"""Draw the figures of the V9-mini paper draft from figures/fig_data.json (written by fig_data.py).

This script only draws: every number it plots is read from fig_data.json, which is computed from the registered
runs by fig_data.py and can be checked without matplotlib. Run it in the separate plotting environment so the
registered environment (.venv, MLX 0.32.2) stays untouched:

    .venv-fig/bin/python reports/V9-MINI/paper/make_figures.py   # environment: figures/requirements-plot.txt

Output: figures/fig{1..5}_*.pdf (vector, for the paper) and .png (for previews), light theme for print.
Colours follow one entity across figures: map_hybrid_self blue, latent_topo orange, map_analytic aqua,
map_hybrid magenta, map_memory green; latent_attn, random and references are neutral greys or ink.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
D = json.loads((FIG / "fig_data.json").read_text())

INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
COL = {"map_hybrid_self": "#2a78d6", "latent_topo": "#eb6834", "map_analytic": "#1baf7a",
       "map_hybrid": "#e87ba4", "map_memory": "#008300"}
ICE, WALL, FLOOR, OOB = "#b7d3f6", "#52514e", "#ffffff", "#e1e0d9"

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    "legend.fontsize": 7.5, "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.8, "axes.facecolor": SURFACE,
    "figure.facecolor": "white", "savefig.facecolor": "white", "pdf.fonttype": 42, "ps.fonttype": 42,
    "lines.linewidth": 2, "lines.markersize": 5,
})


def save(fig, name: str) -> None:
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight", metadata={"CreationDate": None})
    fig.savefig(FIG / f"{name}.png", bbox_inches="tight", dpi=200, metadata={"Software": None})
    plt.close(fig)
    print(f"wrote figures/{name}.pdf and .png")


def hgrid(ax) -> None:
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------- Figure 1: an m2 map with prefix, start and goals

def draw_cells(ax, grid, t, x0=0.0, y0=0.0, size=1.0) -> None:
    for y, row in enumerate(grid):
        for x, v in enumerate(row):
            if v == t["wall"]:
                c = WALL
            elif v == t["ice"]:
                c = ICE
            elif v == t["oob"]:
                c = OOB
            else:
                c = FLOOR
            ax.add_patch(Rectangle((x0 + x * size, y0 + y * size), size, size, facecolor=c, edgecolor=GRID if c != WALL else WALL,
                                   linewidth=0.3))
            if v == t["oob"]:
                ax.add_patch(Rectangle((x0 + x * size, y0 + y * size), size, size, fill=False, hatch="////",
                                       edgecolor=AXIS, linewidth=0))


def heading_arrow(ax, x, y, h, color, scale=0.32, lw=1.2) -> None:
    dx, dy = ((0, -1), (1, 0), (0, 1), (-1, 0))[h]
    ax.annotate("", xy=(x + dx * scale, y + dy * scale), xytext=(x - dx * scale, y - dy * scale),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw, mutation_scale=7))


def fig1() -> None:
    f = D["fig1"]
    t = f["cell_types"]
    grid = f["grid"]
    n = len(grid)
    fig, (ax, axv) = plt.subplots(1, 2, figsize=(6.8, 3.6), gridspec_kw={"width_ratios": [3.2, 1.25], "wspace": 0.08})
    draw_cells(ax, grid, t)
    for src, dst in f["portal_to"]:
        ax.add_patch(Rectangle((src[0] + 0.12, src[1] + 0.12), 0.76, 0.76, facecolor="#6250d6", edgecolor="white", lw=0.8))
        ax.add_patch(Rectangle((dst[0] + 0.12, dst[1] + 0.12), 0.76, 0.76, facecolor="white", edgecolor="#6250d6", lw=1.2))
        ax.add_patch(FancyArrowPatch((src[0] + 0.5, src[1] + 0.5), (dst[0] + 0.5, dst[1] + 0.5), connectionstyle="arc3,rad=0.25",
                                     arrowstyle="-|>", mutation_scale=8, color="#6250d6", lw=1.0, linestyle=(0, (3, 2))))
    # Draw the prefix as connected segments; a teleport (a jump that is not a straight run over open cells)
    # starts a new segment so no line is drawn across walls.
    segs, cur = [], [f["prefix_poses"][0][:2]]
    for p in f["prefix_poses"][1:]:
        (ax0, ay0), (bx, by) = cur[-1], p[:2]
        straight = (ax0 == bx or ay0 == by) and all(
            grid[ay0 + (by > ay0) * k - (by < ay0) * k][ax0 + (bx > ax0) * k - (bx < ax0) * k] != t["wall"]
            for k in range(abs(bx - ax0) + abs(by - ay0) + 1))
        if straight:
            cur.append(p[:2])
        else:
            segs.append(cur)
            cur = [p[:2]]
    segs.append(cur)
    for s in segs:
        ax.plot([c[0] + 0.5 for c in s], [c[1] + 0.5 for c in s], color=MUTED, lw=0.9, alpha=0.75,
                solid_capstyle="round", zorder=3)
    sx, sy, sh = f["start"]
    ax.plot(sx + 0.5, sy + 0.5, "o", ms=9, mfc=INK, mec="white", mew=1.2, zorder=5)
    heading_arrow(ax, sx + 0.5, sy + 0.5, sh, "white", scale=0.25, lw=1.0)
    k = f["highlight_goal"]
    for i, g in enumerate(f["goals"]):
        gx, gy, gh = g["pose"]
        if i == k:
            ax.plot(gx + 0.5, gy + 0.5, "*", ms=15, mfc=COL["map_hybrid_self"], mec="white", mew=1.0, zorder=6)
        else:
            ax.plot(gx + 0.5, gy + 0.5, "o", ms=6, mfc="white", mec=INK, mew=1.0, zorder=5)
    ax.set_xlim(0, n)
    ax.set_ylim(n, 0)
    ax.set_aspect("equal")
    ax.axis("off")
    hg = f["goals"][k]
    ax.set_title(f"Held-out map {f['layout_seed']} (world m2): 400-step prefix, start and goals", loc="left", color=INK)

    view = f["goal_view"]
    draw_cells(axv, view, t)
    for y, row in enumerate(view):
        for x, v in enumerate(row):
            if v == t["portal"]:
                axv.add_patch(Rectangle((x + 0.12, y + 0.12), 0.76, 0.76, facecolor="#6250d6", edgecolor="white", lw=0.8))
    c = len(view) // 2
    axv.plot(c + 0.5, c + 0.5, "*", ms=15, mfc=COL["map_hybrid_self"], mec="white", mew=1.0)
    heading_arrow(axv, c + 0.5, c - 0.55, 0, INK, scale=0.3)
    axv.set_xlim(0, len(view))
    axv.set_ylim(len(view), 0)
    axv.set_aspect("equal")
    axv.axis("off")
    axv.set_title("Goal observation\n(5×5 egocentric view, ahead = up)", loc="left", color=INK)
    lab = ("map_hybrid_self", "map_analytic", "latent_topo", "latent_attn")
    res = "\n".join(f"{a}: {'reached' if hg['success'][a] else 'failed'}" for a in lab)
    axv.text(0, len(view) + 0.4, f"Starred goal: d* = {hg['d_star']}, law-relevant.\n{res}", va="top", ha="left",
             fontsize=7.2, color=INK2, linespacing=1.4)

    handles = [
        Rectangle((0, 0), 1, 1, facecolor=WALL), Rectangle((0, 0), 1, 1, facecolor=ICE, edgecolor=GRID),
        Rectangle((0, 0), 1, 1, facecolor="#6250d6"), Rectangle((0, 0), 1, 1, facecolor="white", edgecolor="#6250d6"),
        plt.Line2D([], [], color=MUTED, lw=0.9), plt.Line2D([], [], marker="o", ls="", mfc=INK, mec="white", ms=7),
        plt.Line2D([], [], marker="*", ls="", mfc=COL["map_hybrid_self"], mec="white", ms=11),
        plt.Line2D([], [], marker="o", ls="", mfc="white", mec=INK, ms=6),
        Rectangle((0, 0), 1, 1, facecolor=OOB, hatch="////", edgecolor=AXIS)]
    names = ["wall", "ice (slide)", "teleporter entrance", "teleporter exit", "exploration prefix", "start (end of prefix)",
             "goal shown on the right", "other goals on this map", "not visible (view)"]
    fig.legend(handles, names, loc="lower center", ncol=5, frameon=False, bbox_to_anchor=(0.5, -0.09),
               handlelength=1.4, columnspacing=1.2)
    save(fig, "fig1_map")


# ---------------------------------------------------------------- Figure 2: the metric-map agent

def box(ax, x, y, w, h, title, body, fc="white", ec=AXIS, tc=INK) -> None:
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.006,rounding_size=0.02", fc=fc, ec=ec, lw=1.0))
    ax.text(x + 0.012, y + h - 0.025, title, ha="left", va="top", fontsize=7.4, fontweight="bold", color=tc)
    ax.text(x + 0.012, y + h - 0.095, body, ha="left", va="top", fontsize=6.2, color=INK2, linespacing=1.35)


def arrow(ax, a, b, color=INK2, style="-|>", ls="-", rad=0.0) -> None:
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=9, color=color, lw=1.0, linestyle=ls,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2))


def fig2() -> None:
    fig, ax = plt.subplots(figsize=(6.8, 3.3))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    blue = COL["map_hybrid_self"]
    top, th = 0.56, 0.42
    box(ax, 0.0, top, 0.13, th, "Observation", "5×5 egocentric\nview + compass\nheading\n\nprefix, then\nthe episode;\ngoal view once")
    box(ax, 0.16, top, 0.26, th, "Odometry & localization",
        "predict the next pose with the\nforward model; check the view\nagainst known map cells.\n"
        "On a surprise: search the ray;\nelse open a fragment, filter\ncandidates, merge back at\n≥ 20 agreeing cells")
    box(ax, 0.45, top, 0.2, th, "Memory of this map",
        "own metric grid, written\nfrom the views\n\nevent memory (all but\nmap_analytic): where a\nforward move really\nended; where a\nteleporter led")
    box(ax, 0.68, top, 0.22, th, "Planner",
        "breadth-first search on\nthe pose graph under the\nforward model; goal found\nby matching the goal view.\n"
        "When lost: plan in the\nfragment or explore its\nfrontier")
    box(ax, 0.16, 0.02, 0.49, 0.4, "Forward model (differs between map agents)",
        "input: the 6 cells ahead (unknown, wall, ice, teleporter,\nfloor)\n"
        "prior: walls block, forward moves one cell, unknown is free\n"
        "gate m(x): is the prior wrong for this input?\n"
        "residual r(x): what happens instead (fit on events only)\n"
        "output: r(x) if m(x) = 1, else the prior\n"
        "learned across maps: ice slides, teleporters teleport", fc="#f3f8fe", ec=blue)
    box(ax, 0.68, 0.02, 0.22, 0.4, "Offline training",
        "random walks on 200\ntraining maps per seed.\nLabels:\n• true poses (map_hybrid)\n"
        "• own localization, no\n  ground truth\n  (map_hybrid_self)", ec=blue)
    arrow(ax, (0.13, 0.77), (0.16, 0.77))
    arrow(ax, (0.42, 0.77), (0.45, 0.77))
    arrow(ax, (0.65, 0.77), (0.68, 0.77))
    arrow(ax, (0.9, 0.77), (0.94, 0.77))
    ax.text(0.945, 0.77, "action", fontsize=6.5, color=INK2, va="center")
    arrow(ax, (0.68, 0.22), (0.65, 0.22), color=blue)
    arrow(ax, (0.27, 0.42), (0.27, 0.56), color=blue)
    arrow(ax, (0.63, 0.42), (0.75, 0.56), color=blue, rad=-0.2)
    ax.text(0.28, 0.49, "predicted moves", fontsize=6.2, color=blue, va="center")
    ax.text(0.455, 0.49, "transitions for search", fontsize=6.2, color=blue, va="center")
    save(fig, "fig2_agent")


# ---------------------------------------------------------------- Figure 3: success per agent (M5)

GROUPS = [("Reference", ["oracle", "topo_oracle_ctrl"]),
          ("Metric map", ["map_hybrid_self", "map_hybrid", "map_analytic"]),
          ("Learned memory", ["latent_topo", "latent_euclid", "latent_attn", "latent_learned", "graph_memory", "gru_belief"]),
          ("", ["random"])]


def fig3() -> None:
    d = D["fig3"]
    order, ypos, y = [], [], 0.0
    for gname, arms in GROUPS:
        for a in arms:
            order.append((gname, a))
            ypos.append(y)
            y += 1
        y += 0.6
    fig, axes = plt.subplots(1, 2, figsize=(6.8, 3.9), sharey=True, gridspec_kw={"wspace": 0.08})
    for ax, w in zip(axes, ("m1", "m2")):
        for (gname, a), yy in zip(order, ypos):
            for kind, off, filled in (("long", -0.16, True), ("short", 0.16, False)):
                v = d[w][a][kind]
                col = INK if filled else INK2
                ax.plot([v["lo"], v["hi"]], [yy + off] * 2, color=col, lw=1.2, solid_capstyle="round")
                ax.plot(v["rate"], yy + off, "o", ms=5.5, mfc=col if filled else "white", mec=col, mew=1.2, zorder=3)
        ax.set_xlim(-0.03, 1.03)
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
        ax.xaxis.grid(True, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        n_long = d[w]["oracle"]["long"]["n"]
        n_short = d[w]["oracle"]["short"]["n"]
        ax.set_title(f"World {w} ({'known laws' if w == 'm1' else 'hidden laws'})\n{n_short} short, {n_long} long episodes",
                     loc="left", color=INK)
        ax.set_xlabel("success rate (M5, pooled over 5 runs)")
        ax.tick_params(axis="y", length=0)
        ax.spines["left"].set_visible(False)
    axes[0].set_yticks(ypos)
    axes[0].set_yticklabels([a + (" (privileged)" if a in ("oracle", "topo_oracle_ctrl") else "") for _, a in order])
    axes[0].set_ylim(ypos[-1] + 0.8, -0.8)
    y0 = 0
    for gname, arms in GROUPS:
        if gname:
            axes[0].text(-0.62, ypos[y0] - 0.55, gname, transform=axes[0].get_yaxis_transform(), fontsize=7.5,
                         fontweight="bold", color=INK, ha="left", va="bottom")
        y0 += len(arms)
    h = [plt.Line2D([], [], marker="o", color=INK, mfc=INK, ms=5.5, lw=1.2),
         plt.Line2D([], [], marker="o", color=INK2, mfc="white", mec=INK2, ms=5.5, lw=1.2)]
    fig.legend(h, ["long goals (d* ≥ 20)", "short goals (4 ≤ d* ≤ 10)"], loc="lower center", ncol=2, frameon=False,
               bbox_to_anchor=(0.55, -0.06))
    save(fig, "fig3_success")


# ---------------------------------------------------------------- Figure 4: success against goal distance (M5)

F4 = [("map_hybrid_self", COL["map_hybrid_self"], "-", "o"), ("map_analytic", COL["map_analytic"], "-", "s"),
      ("latent_topo", COL["latent_topo"], "-", "D"), ("latent_attn", INK2, "--", "^"), ("random", MUTED, ":", "v")]


def fig4() -> None:
    d = D["fig4"]
    fig, axes = plt.subplots(1, 2, figsize=(6.8, 2.8), sharey=True, gridspec_kw={"wspace": 0.08})
    for ax, w in zip(axes, ("m1", "m2")):
        bins = d[w]
        ax.axvspan(10.8, 19.2, color=GRID, alpha=0.45, lw=0)
        ax.text(15, 0.5, "no goals with\n11 ≤ d* ≤ 19", ha="center", va="center", fontsize=6.8, color=INK2)
        for arm, col, ls, mk in F4:
            for part in (bins[:3], bins[3:]):
                ax.plot([b["mean_d"] for b in part], [b["rate"][arm] for b in part], ls=ls, marker=mk, color=col,
                        ms=4.5, lw=1.6 if ls == "-" else 1.3, mec="white", mew=0.6)
        ax.axhline(1.0, color=INK, lw=0.8, ls=(0, (1, 2)))
        ax.set_xlim(3, max(b["mean_d"] for b in bins) + 2)
        ax.set_ylim(-0.03, 1.06)
        ax.set_xlabel("shortest-path distance d* (actions), bin mean")
        ax.set_title(f"World {w} ({'known laws' if w == 'm1' else 'hidden laws'})", loc="left", color=INK)
        hgrid(ax)
    axes[0].set_ylabel("success rate")
    axes[0].text(34, 1.015, "oracle", fontsize=6.8, color=INK, va="bottom", ha="right")
    axes[0].text(34, 0.9, "map_hybrid_self and\nmap_analytic coincide", fontsize=6.6, color=INK2, va="top", ha="right")
    h = [plt.Line2D([], [], color=c, ls=ls, marker=m, ms=4.5, lw=1.6, mec="white", mew=0.6) for _, c, ls, m in F4]
    fig.legend(h, [a for a, *_ in F4], loc="lower center", ncol=5, frameon=False, bbox_to_anchor=(0.5, -0.14))
    save(fig, "fig4_distance")


# ---------------------------------------------------------------- Figure 5: localization split (M4, m2)

F5 = ["map_analytic", "map_memory", "map_hybrid", "map_hybrid_self"]


def fig5() -> None:
    d = D["fig5"]
    fig, ax = plt.subplots(figsize=(3.6, 2.6))
    groups = [("lost", f"lost at end of prefix\n(n = {d['lost']['n']})"), ("localized", f"localized\n(n = {d['localized']['n']})")]
    bw, gap = 0.2, 0.02
    for gi, (key, _) in enumerate(groups):
        for k, arm in enumerate(F5):
            x = gi + (k - 1.5) * (bw + gap)
            v = d[key]["rate"][arm]
            ax.bar(x, v, width=bw, color=COL[arm], edgecolor="white", linewidth=0)
            ax.text(x, v + 0.015, f"{v:.3f}", ha="center", va="bottom", fontsize=5.8, color=INK2)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([g for _, g in groups])
    ax.set_ylim(0, 1.08)
    ax.set_xlim(-0.55, 1.55)
    ax.set_ylabel("long-goal success (M4, m2)")
    hgrid(ax)
    h = [Rectangle((0, 0), 1, 1, color=COL[a]) for a in F5]
    ax.legend(h, F5, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.45, -0.22), columnspacing=1.0,
              handlelength=1.0)
    save(fig, "fig5_localization")


if __name__ == "__main__":
    fig1()
    fig2()
    fig3()
    fig4()
    fig5()
