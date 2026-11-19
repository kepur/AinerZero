"""Numbers for the V9-mini paper draft, generated from the registered runs only (M4, M5).

Reads reports/V9-MINI/{M4,M5}/{m1,m2}-s{0..4}/episodes.json and result.json, plus the registered
verdict files, and prints every number the draft uses that is not copied from a registered result report.
Success rates here are pooled over the five runs of a world (episodes of all runs together), which is the
convention of the M5 judge script; the M4 result report used the mean of per-seed rates, which can differ
in the third decimal. Gate statistics are not recomputed here: the draft cites them from
M4/M4-RESULT.md and M5/M5-RESULT.md, which were independently recomputed (A30, A34).

Usage: .venv/bin/python reports/V9-MINI/paper/make_tables.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
MS = ("M4", "M5")
WORLDS = ("m1", "m2")


def load(m: str, w: str):
    runs = []
    for s in range(5):
        d = ROOT / f"reports/V9-MINI/{m}/{w}-s{s}"
        runs.append((json.loads((d / "result.json").read_text()), json.loads((d / "episodes.json").read_text())))
    return runs


def pooled(runs, arm, pred):
    v = [r["success"] for _, e in runs for r in e[arm] if pred(r)]
    return float(np.mean(v)), len(v)


def main() -> int:
    out = {}
    for m in MS:
        for w in WORLDS:
            runs = load(m, w)
            arms = list(runs[0][1])
            res = {"arms": arms, "n_episodes": sum(len(e["oracle"]) for _, e in runs),
                   "n_layouts_long": len({(i, r["layout_seed"]) for i, (_, e) in enumerate(runs)
                                          for r in e["oracle"] if r["kind"] == "long"}),
                   "success": {}}
            subsets = {"short": lambda r: r["kind"] == "short", "long": lambda r: r["kind"] == "long"}
            if w == "m2":
                subsets["law_relevant"] = lambda r: bool(r["law_relevant"])
            for name, f in subsets.items():
                res["success"][name] = {}
                for a in arms:
                    p, n = pooled(runs, a, f)
                    res["success"][name][a] = p
                res["success"][name]["_n"] = n
            meta = runs[0][0]["meta"]
            res["code_sha256"] = sorted({r["meta"]["code_sha256"][:8] for r, _ in runs})
            res["mlx"] = sorted({r["meta"]["mlx"] for r, _ in runs})
            res["wall_sec_total"] = round(sum(r["meta"]["wall_sec"] for r, _ in runs))
            res["wm_params"] = sorted({r["train"]["params"] for r, _ in runs})
            if m == "M5":
                res["topo_params"] = sorted({r["topo"]["params"] for r, _ in runs})
                res["attn_params"] = sorted({r["attn"]["params"] for r, _ in runs})
                res["attn_train_sec"] = [round(r["attn"]["train_sec"]) for r, _ in runs]
            if w == "m2":
                res["m3_label_agreement"] = [round(r["m3_label_quality"]["label_agreement_with_truth"], 4) for r, _ in runs]
                res["prediction"] = [{k: round(v, 4) for k, v in r["prediction"].items() if isinstance(v, float)} for r, _ in runs]
            if m == "M5":
                # Width of the H1s interval when maps are clusters vs when episodes are treated as independent
                # (illustration for the protocol section; 4000 resamples, default_rng(0) for both).
                a = np.array([r["success"] for _, e in runs for r in e["map_hybrid_self"] if r["kind"] == "long"], float)
                b = np.array([r["success"] for _, e in runs for r in e["latent_topo"] if r["kind"] == "long"], float)
                keys = [(i, r["layout_seed"]) for i, (_, e) in enumerate(runs) for r in e["oracle"] if r["kind"] == "long"]
                d = a - b
                uniq = {k: j for j, k in enumerate(sorted(set(keys)))}
                g = np.array([uniq[k] for k in keys])
                s1 = np.bincount(g, weights=d, minlength=len(uniq))
                c = np.bincount(g, minlength=len(uniq)).astype(float)
                bi = np.random.default_rng(0).integers(0, len(uniq), (4000, len(uniq)))
                lo_c, hi_c = np.percentile(s1[bi].sum(1) / c[bi].sum(1), [2.5, 97.5])
                be = np.random.default_rng(0).integers(0, len(d), (4000, len(d)))
                lo_e, hi_e = np.percentile(d[be].mean(1), [2.5, 97.5])
                res["h1s_width"] = {"cluster": round(float(hi_c - lo_c), 4), "episode": round(float(hi_e - lo_e), 4),
                                    "ratio_episode_to_cluster": round(float((hi_e - lo_e) / (hi_c - lo_c)), 3)}
            out[f"{m}-{w}"] = res
            if "h1s_width" in res:
                print(f"\n[{m} {w}] H1s interval width: by map cluster {res['h1s_width']['cluster']}, "
                      f"by episode {res['h1s_width']['episode']}, ratio {res['h1s_width']['ratio_episode_to_cluster']}")
            print(f"\n===== {m} {w}: {res['n_episodes']} episodes; long-goal clusters (run x layout) {res['n_layouts_long']}; "
                  f"code {res['code_sha256']}; MLX {res['mlx']}; wall {res['wall_sec_total']} s; world-model params {res['wm_params']}")
            if m == "M5":
                print(f"  topo params {res['topo_params']}; attn params {res['attn_params']}; attn train sec {res['attn_train_sec']}")
            if w == "m2":
                print(f"  self-supervised label agreement with truth: {res['m3_label_agreement']}")
            for name in subsets:
                print(f"  {name} (n={res['success'][name]['_n']})")
                for a in arms:
                    print(f"    {a:18s} {res['success'][name][a]:.3f}")
    print("\n" + json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
