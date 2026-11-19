"""Independent recomputation of V9-mini draft Tables 3 and 5.

Does not import make_tables.py or check_draft.py. Success rates pool every
episode of the five runs of a world. The law-relevant subset is not restricted
by short/long. The episodes row is an episode count.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
DRAFT = ROOT / "reports/V9-MINI/paper/DRAFT.md"
MS = ("M4", "M5")
WORLDS = ("m1", "m2")
COLS = [("m1", "short"), ("m1", "long"), ("m2", "short"), ("m2", "long"), ("m2", "law_relevant")]


def load(milestone: str, world: str):
    runs = []
    for seed in range(5):
        d = ROOT / f"reports/V9-MINI/{milestone}/{world}-s{seed}"
        episodes = json.loads((d / "episodes.json").read_text())
        result = json.loads((d / "result.json").read_text())
        runs.append((result, episodes))
    return runs


def pooled(runs, arm: str, pred) -> tuple[float, int]:
    values = [row["success"] for _, episodes in runs for row in episodes[arm] if pred(row)]
    if not values:
        return float("nan"), 0
    return float(np.mean(np.asarray(values, dtype=np.float64))), len(values)


def cell_text(value: float) -> str:
    if value == 0:
        return "0"
    return f"{value:.3f}"


def draft_table(title: str) -> list[list[str]]:
    text = DRAFT.read_text()
    start = text.index(title)
    rows = []
    for line in text[start:].splitlines()[1:]:
        if line.startswith("|"):
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
        elif rows:
            break
    return rows


def subset_fns(world: str) -> list[tuple[str, object]]:
    fns = [("short", lambda row: row["kind"] == "short"), ("long", lambda row: row["kind"] == "long")]
    if world == "m2":
        fns.append(("law_relevant", lambda row: bool(row["law_relevant"])))
    return fns


def main() -> int:
    print("python", sys.version.split()[0])
    print("numpy", np.__version__)
    print("pooling: all episodes of five runs; law_relevant ignores kind; episodes row is a count")
    computed = {}
    mismatches = 0
    for milestone in MS:
        for world in WORLDS:
            runs = load(milestone, world)
            arms = list(runs[0][1])
            block = {"arms": arms, "success": {}}
            print(f"\n===== {milestone} {world} arms={len(arms)}")
            for name, pred in subset_fns(world):
                block["success"][name] = {}
                print(f"  {name}")
                n_ref = None
                for arm in arms:
                    rate, n = pooled(runs, arm, pred)
                    block["success"][name][arm] = rate
                    if n_ref is None:
                        n_ref = n
                    elif n != n_ref:
                        print(f"    COUNT_MISMATCH {arm} n={n} ref={n_ref}")
                        mismatches += 1
                    print(f"    {arm} raw={rate:.16f} text={cell_text(rate)} n={n}")
                block["success"][name]["_n"] = n_ref
                print(f"    episodes n={n_ref}")
            oracle = runs[0][1]["oracle"]
            # cluster = (run index, layout) among this world's oracle episodes
            long_clusters = {
                (i, row["layout_seed"])
                for i, (_, episodes) in enumerate(runs)
                for row in episodes["oracle"]
                if row["kind"] == "long"
            }
            law_clusters = {
                (i, row["layout_seed"])
                for i, (_, episodes) in enumerate(runs)
                for row in episodes["oracle"]
                if row["law_relevant"]
            }
            n_eps = sum(len(episodes["oracle"]) for _, episodes in runs)
            block["n_episodes"] = n_eps
            block["n_long_clusters"] = len(long_clusters)
            block["n_law_clusters"] = len(law_clusters)
            print(f"  n_episodes={n_eps} long_clusters={len(long_clusters)} law_clusters={len(law_clusters)}")
            computed[f"{milestone}-{world}"] = block

    print("\n===== draft Tables 3 and 5, cell by cell")
    for title, milestone in (("**Table 3.", "M4"), ("**Table 5.", "M5")):
        rows = draft_table(title)
        print(f"{title} parsed_rows={len(rows)}")
        for row in rows[2:]:
            arm = row[0].replace(" (privileged)", "")
            for got, (world, subset) in zip(row[1:], COLS):
                block = computed[f"{milestone}-{world}"]["success"][subset]
                if arm == "episodes":
                    expect = str(block["_n"])
                else:
                    expect = cell_text(block[arm])
                ok = got == expect or (expect == "0" and got in ("0", "0.000"))
                flag = "OK" if ok else "MISMATCH"
                if not ok:
                    mismatches += 1
                print(f"  {flag} {milestone} {arm} {world}/{subset} draft={got} recompute={expect}")

    print("\n===== episode diagnostics used by the draft body")
    m4_m2 = load("M4", "m2")
    hybrid_long = [row for _, episodes in m4_m2 for row in episodes["map_hybrid"] if row["kind"] == "long"]
    analytic_long = [row for _, episodes in m4_m2 for row in episodes["map_analytic"] if row["kind"] == "long"]
    lost = [row for row in hybrid_long if row["lost_at_start"]]
    localized = [row for row in hybrid_long if not row["lost_at_start"]]
    print(f"M4 m2 map_hybrid long n={len(hybrid_long)} lost_at_start={len(lost)} localized={len(localized)}")
    print(f"M4 m2 map_hybrid long success lost={float(np.mean([r['success'] for r in lost])):.6f} localized={float(np.mean([r['success'] for r in localized])):.6f}")
    # analytic episodes are paired in the same order
    a_lost = [a["success"] for h, a in zip(hybrid_long, analytic_long) if h["lost_at_start"]]
    a_loc = [a["success"] for h, a in zip(hybrid_long, analytic_long) if not h["lost_at_start"]]
    print(f"M4 m2 map_analytic long success on hybrid-lost split lost={float(np.mean(a_lost)):.6f} localized={float(np.mean(a_loc)):.6f}")
    all_h = [row for _, episodes in m4_m2 for row in episodes["map_hybrid"]]
    lost_all = sum(bool(row["lost_at_start"]) for row in all_h)
    print(f"M4 m2 map_hybrid all episodes n={len(all_h)} lost_at_start={lost_all} fraction={lost_all / len(all_h):.6f}")
    fails = [row for row in hybrid_long if not row["success"]]
    fails_lost = sum(bool(row["lost_at_start"]) for row in fails)
    print(f"M4 m2 map_hybrid long failures n={len(fails)} lost_at_start={fails_lost} fraction={fails_lost / len(fails):.6f}")
    disagree = sum(int(h["success"] != a["success"]) for h, a in zip(hybrid_long, analytic_long))
    self_long = [row for _, episodes in m4_m2 for row in episodes["map_hybrid_self"] if row["kind"] == "long"]
    m1 = load("M4", "m1")
    h1 = [row for _, episodes in m1 for row in episodes["map_hybrid"] if row["kind"] == "long"]
    a1 = [row for _, episodes in m1 for row in episodes["map_analytic"] if row["kind"] == "long"]
    s1 = [row for _, episodes in m1 for row in episodes["map_hybrid_self"] if row["kind"] == "long"]
    print(f"M4 m1 long disagreements hybrid_vs_analytic={sum(int(h['success'] != a['success']) for h, a in zip(h1, a1))}")
    print(f"M4 m1 long disagreements self_vs_analytic={sum(int(h['success'] != a['success']) for h, a in zip(s1, a1))}")
    print(f"M4 m2 long disagreements hybrid_vs_analytic={disagree}")
    print(f"M4 m2 long disagreements self_vs_hybrid={sum(int(h['success'] != a['success']) for h, a in zip(self_long, hybrid_long))}")

    for world in WORLDS:
        runs = load("M5", world)
        rows = [row for _, episodes in runs for row in episodes["latent_topo"] if row["kind"] == "long"]
        ok = [row["relocalizations"] for row in rows if row["success"]]
        bad = [row["relocalizations"] for row in rows if not row["success"]]
        print(
            f"M5 {world} latent_topo long relocalizations "
            f"success_n={len(ok)} mean={float(np.mean(ok)):.6f} round1={round(float(np.mean(ok)), 1)} "
            f"fail_n={len(bad)} mean={float(np.mean(bad)):.6f} round1={round(float(np.mean(bad)), 1)}"
        )

    print("\n===== result.json fields cited by the draft")
    for milestone in MS:
        for world in WORLDS:
            runs = load(milestone, world)
            agreements = [run["m3_label_quality"]["label_agreement_with_truth"] for run, _ in runs]
            params = sorted({run["train"]["params"] for run, _ in runs})
            train_sec = [run["train"]["train_sec"] for run, _ in runs]
            py = sorted({run["meta"]["python"] for run, _ in runs})
            mlx = sorted({run["meta"]["mlx"] for run, _ in runs})
            machine = sorted({run["meta"]["machine"] for run, _ in runs})
            print(f"{milestone} {world} python={py} mlx={mlx} machine={machine} wm_params={params} wm_train_sec={train_sec}")
            print(f"  label_agreement={agreements}")
            if milestone == "M5":
                print(f"  topo_params={sorted({run['topo']['params'] for run, _ in runs})}")
                print(f"  attn_params={sorted({run['attn']['params'] for run, _ in runs})}")
                print(f"  attn_train_sec={[run['attn']['train_sec'] for run, _ in runs]}")

    print("\n===== products of registered preset constants")
    print(f"env_steps_world_model={200 * 4 * 200}")
    print(f"env_steps_attn={200 * 1 * 800}")
    print(f"grid_size={3 * (5 + 1) + 1}")
    print(f"obs_dim={5 * 5 * 13 + 4}")
    print(f"action_sequences={3 ** 3}")

    print("\n===== draft intervals in abstract, sections 3-8, appendix A")
    lines = DRAFT.read_text().splitlines()

    def in_scope(lineno: int) -> bool:
        # 1-based lines from the r0 draft: abstract 7-19, §3 starts at 74, appendix A at 420, notes at 436
        return (7 <= lineno <= 19) or (74 <= lineno <= 435)

    sources = []
    for rel in (
        "reports/V9-MINI/M4/M4-RESULT.md",
        "reports/V9-MINI/M5/M5-RESULT.md",
        "reports/V9-MINI/M4/analysis/judge.txt",
        "reports/V9-MINI/M5/analysis/judge.txt",
        "reports/V9-MINI/M4/analysis/summary-m1.txt",
        "reports/V9-MINI/M4/analysis/summary-m2.txt",
        "reports/V9-MINI/M5/analysis/summary-m1.txt",
        "reports/V9-MINI/M5/analysis/summary-m2.txt",
        "reports/V9-MINI/M5/analysis/A34-acceptance.md",
        "reports/V9-MINI/PLAN.md",
    ):
        sources.append((ROOT / rel).read_text())
    blob = "\n".join(sources)

    def norm(text: str) -> str:
        return text.replace("−", "-").replace(" ", "")

    signed = norm(blob)
    pat = re.compile(r"[+−-]?\d\.\d{3} \[[+−-]?\d\.\d{3}, [+−-]?\d\.\d{3}\]")
    seen = []
    for lineno, line in enumerate(lines, start=1):
        if not in_scope(lineno):
            continue
        for found in pat.findall(line):
            seen.append((lineno, found))
    print(f"interval_count={len(seen)}")
    for lineno, found in seen:
        verbatim = found in blob
        if verbatim:
            status = "VERBATIM"
        else:
            alt = re.sub(r"\[(\d)", r"[+\1", found).replace(", 0.", ", +0.")
            status = "SIGN_NORMALIZED" if norm(alt) in signed or norm(found) in signed else "NOT_FOUND"
            if status == "NOT_FOUND":
                mismatches += 1
        print(f"  {status} L{lineno} {found}")
    print(f"\nMISMATCH_COUNT={mismatches}")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
