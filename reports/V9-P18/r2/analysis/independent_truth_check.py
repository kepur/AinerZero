"""ainerzero.V9.P18 r2: independent truth-only recalculation (new implementation).

Purpose
-------
Cross-check the k-support coverage, per-family label balance and the
constant-predictor baselines that P18 r1 (truth_stats.py) and P19
(independent_checks.py) reported, using a *separate* pure-Python
implementation that does not import the frozen ``s1`` package at all.

This is NOT a re-run of the P18/P19 suite.  It reads only the frozen
development truth sidecar (read-only) and writes one JSON under
``reports/V9-P18/r2/analysis/``.

Semantics mirrored from the frozen r5 source (not imported):
  * relative_cell_path: per-step (x,z) rounded to int, minus first-pose origin
    (evaluation.py:75-94)
  * relative_free_adjacency: 4-neighbour edges between *visited* cells,
    skipping blocked cells and out-of-bounds targets, in the relative frame
    (evaluation.py:97-121)
  * split_support_query: support = first k transitions, query = next up to 8
    (metrics.py:504-519); empty split -> insufficient_data, never 0.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
DATASET = (
    REPO
    / "artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
)
OUT = Path(os.environ.get("V9P18R2_OUT", REPO / "reports/V9-P18/r2"))
K_VALUES = (0, 1, 2, 4, 8)
QUERY_LIMIT = 8  # code default in metrics.split_support_query; NOT in the frozen prereg


def relative_cell_path(row: dict) -> list[tuple[int, int]]:
    poses = [
        (float(step["agent_world_pose"]["position"][0]),
         float(step["agent_world_pose"]["position"][2]))
        for step in row["steps"]
    ]
    if not poses:
        return []
    ox, oz = int(round(poses[0][0])), int(round(poses[0][1]))
    return [(int(round(x)) - ox, int(round(z)) - oz) for x, z in poses]


def free_adjacency(row: dict, cells: list[tuple[int, int]]) -> set[tuple[tuple[int, int], tuple[int, int]]]:
    poses = row["steps"][0]["agent_world_pose"]["position"]
    origin = (int(round(float(poses[0]))), int(round(float(poses[2]))))
    world = row.get("world") or {}
    width, height = int(world["width"]), int(world["height"])
    blocked = {(int(x), int(z)) for x, z in world.get("blocked", [])}
    visited = set(cells)
    edges = set()
    for x, z in visited:
        for nx, nz in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
            if (nx, nz) not in visited:
                continue
            ax, az = x + origin[0], z + origin[1]
            bx, bz = nx + origin[0], nz + origin[1]
            if not (0 <= bx < width and 0 <= bz < height):
                continue
            if (ax, az) in blocked or (bx, bz) in blocked:
                continue
            edges.add(tuple(sorted(((x, z), (nx, nz)))))
    return edges


def split_support_query(n_transitions: int, k: int) -> tuple[list[int], list[int]]:
    total = int(n_transitions)
    support = min(max(int(k), 0), total)
    if support < int(k) or total - support < 1:
        return [], []
    return list(range(support)), list(range(support, min(total, support + QUERY_LIMIT)))


def main() -> int:
    rows = []
    with (DATASET / "truth/development.jsonl").open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    family = defaultdict(lambda: {"worlds": 0, "steps": Counter(), "transitions": 0,
                                  "distinct_cells": 0, "stay": 0, "adjacent": 0, "non_adjacent": 0})
    for row in rows:
        fam = row.get("family") or "unknown"
        cells = relative_cell_path(row)
        slot = family[fam]
        slot["worlds"] += 1
        slot["steps"][len(row["steps"])] += 1
        slot["transitions"] += max(len(row["steps"]) - 1, 0)
        slot["distinct_cells"] += len(set(cells))
        for a, b in zip(cells, cells[1:]):
            if a == b:
                slot["stay"] += 1
            elif abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1:
                slot["adjacent"] += 1
            else:
                slot["non_adjacent"] += 1

    per_k = {}
    for k in K_VALUES:
        worlds = queries = reachable = 0
        by_family = {}
        for row in rows:
            cells = relative_cell_path(row)
            edges = free_adjacency(row, cells)
            transitions = max(len(row["steps"]) - 1, 0)
            support, query = split_support_query(transitions, k)
            if not query:
                continue
            worlds += 1
            fam = row.get("family") or "unknown"
            slot = by_family.setdefault(fam, {"worlds": 0, "queries": 0, "true_edges": 0, "reachable": 0})
            slot["worlds"] += 1
            support_cells = set(cells[: len(support) + 1]) if support else set()
            for index in query:
                queries += 1
                slot["queries"] += 1
                edge = tuple(sorted((cells[index], cells[index + 1])))
                if edge in edges:
                    slot["true_edges"] += 1
                if cells[index + 1] in support_cells:
                    reachable += 1
                    slot["reachable"] += 1
        true_edges = sum(s["true_edges"] for s in by_family.values())
        per_k[str(k)] = {
            "worlds": worlds,
            "queries": queries,
            "by_family": dict(sorted(by_family.items())),
            "true_edges": true_edges,
            "constant_predictor_baselines": {
                "constant_true_accuracy": round(true_edges / queries, 6) if queries else None,
                "constant_false_accuracy": round(1 - true_edges / queries, 6) if queries else None,
                "diagnostic_only": True,
            },
            "reachable_in_support_memory": reachable,
            "reachable_fraction": round(reachable / queries, 6) if queries else None,
            "diagnostic_only": True,
        }

    payload = {
        "schema": "ainerzero.v9.p18r2.truth-check.v1",
        "task": "ainerzero.V9.P18",
        "revision": "r2",
        "executor": "deepseek-v41f-p8k2",
        "method": "independent pure-Python reimplementation; does not import the frozen s1 package",
        "input": {
            "truth_development_jsonl": str(DATASET / "truth/development.jsonl"),
            "source_semantics": [
                "evaluation.py:75-94 relative_cell_path",
                "evaluation.py:97-121 relative_free_adjacency",
                "metrics.py:504-519 split_support_query",
            ],
            "query_limit": QUERY_LIMIT,
            "query_limit_registered_in_prereg": False,
        },
        "development_worlds": len(rows),
        "family_summary": {fam: {
            "worlds": s["worlds"],
            "steps": dict(sorted(s["steps"].items())),
            "transitions": s["transitions"],
            "distinct_cells": s["distinct_cells"],
            "stay": s["stay"],
            "adjacent": s["adjacent"],
            "non_adjacent": s["non_adjacent"],
        } for fam, s in sorted(family.items())},
        "k_coverage": per_k,
        "note": "diagnostic cross-check only. family/constant-baseline numbers do not replace the "
                "frozen few_shot_unseen_transition metric and are not a capability result.",
    }

    (OUT / "analysis").mkdir(parents=True, exist_ok=True)
    (OUT / "analysis" / "independent_truth_check.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False)
    )
    print(json.dumps({k: payload[k] for k in ("development_worlds", "family_summary", "k_coverage")},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
