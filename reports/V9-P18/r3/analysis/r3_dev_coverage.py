#!/usr/bin/env python3
"""P18 r3 independent CPU recount of the S1 development partition (k support/query coverage).

Scope / limits
--------------
* Pure standard library.  Does NOT import the ``ainerzero`` package, does NOT import
  MLX, does NOT train, does NOT run a real evaluation, does NOT read the ``final``
  partition, does NOT generate data.
* The semantics re-implemented here are copied from the frozen r5 snapshot (read only)
  and each source is pinned by SHA256 in the output:
    - ``evaluation.py``  relative_cell_path        (per-step relative cell)
    - ``evaluation.py``  relative_free_adjacency   (true free-space edges)
    - ``metrics.py``     split_support_query       (support = first k transitions,
                                                    query = next <=8 transitions)
  ``query_limit=8`` exists only as a default argument in the frozen code and is NOT
  registered in the frozen pre-registration; that fact is recorded, not decided here.

Write-path policy (P18 r3 decision M1)
--------------------------------------
* The output directory must be given explicitly (``--out DIR`` or ``V9P18R3_OUT``).
  There is no hard-coded output root and no ``/tmp`` default.
* The script refuses to run if the output directory already exists and is non-empty,
  so a delivered r3 product can never be overwritten by a re-run.
* ``dev_coverage.json`` is byte-deterministic (no timestamps, no absolute paths), so two
  different new output directories can be compared for identity.
  ``run_meta.json`` is deliberately NOT deterministic: it records the actual output
  root, argv and wall-clock time for audit, and is excluded from identity claims.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

K_VALUES = (0, 1, 2, 4, 8)
QUERY_LIMIT = 8

REPO = Path(__file__).resolve().parents[4]  # .../AinerZero
SNAPSHOT = Path(
    "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot"
)
DATASET_DIGEST = "8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
DATASET = REPO / "artifacts/v9/s1/datasets" / DATASET_DIGEST
TRUTH_DEV = DATASET / "truth/development.jsonl"
MANIFEST = DATASET / "dataset_manifest.json"

SEMANTICS_SOURCES = [
    ("src/ainerzero/v9/experiments/s1/evaluation.py", "75-94", "relative_cell_path"),
    ("src/ainerzero/v9/experiments/s1/evaluation.py", "97-121", "relative_free_adjacency"),
    ("src/ainerzero/v9/experiments/s1/metrics.py", "504-519", "split_support_query"),
    ("src/ainerzero/v9/experiments/s1/evaluation.py", "296-360", "few_shot_report call order"),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_out(argv: list[str]) -> Path:
    out = None
    if "--out" in argv:
        index = argv.index("--out")
        if index + 1 >= len(argv):
            raise SystemExit("--out needs a directory argument")
        out = argv[index + 1]
    out = out or os.environ.get("V9P18R3_OUT")
    if not out:
        raise SystemExit("refusing to run: pass --out DIR or set V9P18R3_OUT (no implicit output root)")
    path = Path(out).expanduser().resolve()
    if path.exists() and any(path.iterdir()):
        raise SystemExit(f"refusing to run: output directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------------------
# frozen r5 semantics, re-implemented (no import of the package under test)
# --------------------------------------------------------------------------------------
def relative_cell_path(episode: dict) -> list[tuple[int, int]]:
    poses = [step["agent_world_pose"]["position"] for step in episode["steps"]]
    if not poses:
        return []
    ox = int(round(float(poses[0][0])))
    oz = int(round(float(poses[0][2])))
    return [(int(round(float(p[0]))) - ox, int(round(float(p[2]))) - oz) for p in poses]


def relative_cells(episode: dict) -> list[tuple[int, int]]:
    """Deduplicated consecutive stays, in visit order (as the frozen helper does)."""
    out: list[tuple[int, int]] = []
    for cell in relative_cell_path(episode):
        if not out or out[-1] != cell:
            out.append(cell)
    return out


def relative_free_adjacency(episode: dict) -> set[tuple[tuple[int, int], tuple[int, int]]]:
    poses = [step["agent_world_pose"]["position"] for step in episode["steps"]]
    if not poses:
        return set()
    ox = int(round(float(poses[0][0])))
    oz = int(round(float(poses[0][2])))
    world = episode["world"]
    width = int(world["width"])
    height = int(world["height"])
    blocked = {(int(x), int(z)) for x, z in world["blocked"]}
    visited = set(relative_cells(episode))
    edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for cell in visited:
        x, z = cell
        for nx, nz in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
            if (nx, nz) not in visited:
                continue
            ax, az = x + ox, z + oz
            bx, bz = nx + ox, nz + oz
            if not (0 <= bx < width and 0 <= bz < height):
                continue
            if (ax, az) in blocked or (bx, bz) in blocked:
                continue
            edges.add(tuple(sorted((cell, (nx, nz)))))
    return edges


def split_support_query(n_transitions: int, k: int, query_limit: int = QUERY_LIMIT):
    total = int(n_transitions)
    support = min(max(int(k), 0), total)
    if support < int(k) or total - support < 1:
        return [], []
    return list(range(support)), list(range(support, min(total, support + int(query_limit))))


# --------------------------------------------------------------------------------------
def main() -> int:
    out_dir = resolve_out(sys.argv[1:])
    started = datetime.datetime.now().astimezone()

    episodes = []
    with TRUTH_DEV.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                episodes.append(json.loads(line))

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    family_summary: dict[str, dict] = {}
    per_episode = []
    for episode in episodes:
        family = episode.get("family") or "unknown"
        cells = relative_cell_path(episode)
        edges = relative_free_adjacency(episode)
        steps = len(episode["steps"])
        transitions = max(steps - 1, 0)
        stay = adjacent = non_adjacent = 0
        for index in range(transitions):
            pair = tuple(sorted((cells[index], cells[index + 1])))
            if cells[index] == cells[index + 1]:
                stay += 1
            elif pair in edges:
                adjacent += 1
            else:
                non_adjacent += 1
        entry = family_summary.setdefault(
            family,
            {
                "worlds": 0,
                "steps_histogram": {},
                "transitions": 0,
                "stay": 0,
                "adjacent": 0,
                "non_adjacent": 0,
                "distinct_cells_total": 0,
                "distinct_cells_per_episode": [],
            },
        )
        entry["worlds"] += 1
        entry["steps_histogram"][str(steps)] = entry["steps_histogram"].get(str(steps), 0) + 1
        entry["transitions"] += transitions
        entry["stay"] += stay
        entry["adjacent"] += adjacent
        entry["non_adjacent"] += non_adjacent
        distinct = len(set(cells))
        entry["distinct_cells_total"] += distinct
        entry["distinct_cells_per_episode"].append(distinct)
        per_episode.append(
            {
                "episode_id": episode["episode_id"],
                "family": family,
                "steps": steps,
                "transitions": transitions,
                "distinct_cells": distinct,
                "stay": stay,
                "adjacent": adjacent,
                "non_adjacent": non_adjacent,
            }
        )

    for family, entry in family_summary.items():
        values = sorted(entry.pop("distinct_cells_per_episode"))
        entry["distinct_cells_min"] = values[0] if values else 0
        entry["distinct_cells_max"] = values[-1] if values else 0
        entry["distinct_cells_mean"] = round(sum(values) / len(values), 6) if values else 0.0

    # ---- k coverage -------------------------------------------------------------------
    k_coverage: dict[str, dict] = {}
    for k in K_VALUES:
        worlds = 0
        queries = 0
        true_edges = 0
        start_in_support = 0
        end_in_support = 0
        # diagnostic: under the as-coded exclusive stop (=k) the memory only holds k-1
        # transitions, i.e. cells[0..k-1].  Counted only to size the defect.
        as_coded_memory_hit = 0
        by_family: dict[str, dict] = {}
        for episode in episodes:
            family = episode.get("family") or "unknown"
            cells = relative_cell_path(episode)
            edges = relative_free_adjacency(episode)
            transitions = max(len(episode["steps"]) - 1, 0)
            support, query = split_support_query(transitions, k)
            if not query:
                continue
            worlds += 1
            queries += len(query)
            memory_cells = set(cells[: len(support) + 1]) if support else set()
            short_memory_cells = set(cells[: max(len(support) - 1, 0) + 1]) if support else set()
            fam = by_family.setdefault(
                family,
                {
                    "worlds": 0,
                    "queries": 0,
                    "true_edges": 0,
                    "query_start_cell_in_support": 0,
                    "query_end_cell_in_support": 0,
                },
            )
            fam["worlds"] += 1
            fam["queries"] += len(query)
            for index in query:
                true_edge = tuple(sorted((cells[index], cells[index + 1])))
                is_true = true_edge in edges
                true_edges += int(is_true)
                fam["true_edges"] += int(is_true)
                if cells[index] in memory_cells:
                    start_in_support += 1
                    fam["query_start_cell_in_support"] += 1
                if cells[index + 1] in memory_cells:
                    end_in_support += 1
                    fam["query_end_cell_in_support"] += 1
                if cells[index] in short_memory_cells:
                    as_coded_memory_hit += 1
        k_coverage[str(k)] = {
            "worlds_with_support_and_query": worlds,
            "queries": queries,
            "family_composition": sorted({f for f in by_family}),
            "by_family": dict(sorted(by_family.items())),
            "true_edges": true_edges,
            "true_edge_rate": round(true_edges / queries, 6) if queries else None,
            "constant_predict_true_accuracy": round(true_edges / queries, 6) if queries else None,
            "constant_predict_false_accuracy": round(1 - true_edges / queries, 6) if queries else None,
            "query_start_cell_in_support_memory": start_in_support,
            "query_start_cell_in_support_fraction": round(start_in_support / queries, 6) if queries else None,
            "query_end_cell_in_support_memory": end_in_support,
            "query_end_cell_in_support_fraction": round(end_in_support / queries, 6) if queries else None,
            "diagnostic_only": True,
            "note": (
                "constant-predictor baselines and memory-reachability counts are diagnostics; "
                "they do not replace the frozen metric few_shot_unseen_transition "
                "(accuracy and displacement error vs k)."
            ),
            "diagnostic_as_coded_short_memory_start_hit": as_coded_memory_hit,
        }

    # ---- support/query scope ----------------------------------------------------------
    ids = [e["episode_id"] for e in episodes]
    world_keys = [json.dumps(e["world_key"], sort_keys=True) for e in episodes]
    rounds = [int(e.get("round_index", 0)) for e in episodes]
    cross_episode_possible = 0
    for episode in episodes:
        transitions = max(len(episode["steps"]) - 1, 0)
        for k in K_VALUES:
            support, query = split_support_query(transitions, k)
            if not query:
                continue
            if min(support + query) < 0 or max(support + query) >= transitions:
                cross_episode_possible += 1
    support_query_scope = {
        "episodes": len(episodes),
        "unique_episode_ids": len(set(ids)),
        "unique_world_keys": len(set(world_keys)),
        "round_index_values": sorted(set(rounds)),
        "rounds_per_world_registered": manifest["counts"].get("rounds_per_world"),
        "support_and_query_index_outside_single_episode": cross_episode_possible,
        "cross_episode": False,
        "basis": [
            "metrics.split_support_query() returns index ranges over ONE episode's transitions",
            "evaluation.few_shot_report() loops per sequence and builds memory only from that",
            "  sequence (memory=None at the start of every world); nothing is carried across worlds",
            "each episode has round_index=0 and rounds_per_world=1, so one episode == one world",
        ],
        "held_out_semantics": (
            "query is the temporal continuation of the support prefix inside the same episode. "
            "It is NOT a spatially unvisited cell: for k>=1 a large share of query start cells is "
            "already inside the support memory (see query_start_cell_in_support_fraction)."
        ),
    }

    # ---- shape ------------------------------------------------------------------------
    steps_total = sum(e["steps"] for e in per_episode)
    transitions_total = sum(e["transitions"] for e in per_episode)
    shape = {
        "episodes": len(per_episode),
        "steps_total": steps_total,
        "transitions_total": transitions_total,
        "manifest_development_packets": manifest["counts"].get("development_packets"),
        "steps_total_equals_manifest_packets": steps_total == manifest["counts"].get("development_packets"),
        "steps_per_family": {
            family: sorted(entry["steps_histogram"].items()) for family, entry in sorted(family_summary.items())
        },
        "transitions_per_family": {
            family: entry["transitions"] for family, entry in sorted(family_summary.items())
        },
        "max_transitions_per_world": max(e["transitions"] for e in per_episode),
        "k8_needs_transitions": 9,
        "worlds_with_at_least_9_transitions": sum(1 for e in per_episode if e["transitions"] >= 9),
        "worlds_with_at_least_5_transitions": sum(1 for e in per_episode if e["transitions"] >= 5),
    }

    # ---- arithmetic that the r3 budget material reuses --------------------------------
    few_shot_step_sequence_calls = sum(
        k_coverage[str(k)]["worlds_with_support_and_query"] for k in (1, 2, 4)
    )
    few_shot_repaired_stop_frames = sum(
        k_coverage[str(k)]["worlds_with_support_and_query"] * (k + 1) for k in (1, 2, 4)
    )
    few_shot_transitions = sum(
        k_coverage[str(k)]["worlds_with_support_and_query"] * k for k in (1, 2, 4)
    )
    few_shot_probe_graph = sum(k_coverage[str(k)]["worlds_with_support_and_query"] for k in K_VALUES)
    derived = {
        "few_shot_step_sequence_calls": few_shot_step_sequence_calls,
        "few_shot_repaired_stop_frames": few_shot_repaired_stop_frames,
        "few_shot_transitions": few_shot_transitions,
        "few_shot_probe_graph_calls": few_shot_probe_graph,
        "few_shot_encode_calls": 2 * sum(k_coverage[str(k)]["queries"] for k in K_VALUES),
        "few_shot_queries_total": sum(k_coverage[str(k)]["queries"] for k in K_VALUES),
        "derivation": {
            "step_sequence_calls": "sum over k in {1,2,4} of worlds_with_support_and_query",
            "repaired_stop_frames": "sum over k in {1,2,4} of worlds_with_support_and_query * (k+1)",
            "transitions": "sum over k in {1,2,4} of worlds_with_support_and_query * k",
            "probe_graph_calls": "one probe_graph per world with a query, summed over all k",
            "encode_calls": "2 encodes per query transition, summed over all k",
        },
        "provenance": "arithmetic_r3 (derived from this file's k coverage, not measured)",
    }

    sources = []
    for rel, lines, what in SEMANTICS_SOURCES:
        path = SNAPSHOT / rel
        sources.append(
            {
                "file": rel,
                "lines": lines,
                "what": what,
                "sha256": sha256_file(path),
            }
        )

    payload = {
        "schema": "ainerzero.v9.p18r3.dev-coverage.v1",
        "task": "ainerzero.V9.P18",
        "revision": "r3",
        "executor": "deepseek-v41f-r3k9",
        "method": (
            "independent pure-Python reimplementation of the frozen r5 semantics; "
            "does not import the ainerzero package, does not import MLX"
        ),
        "query_limit": QUERY_LIMIT,
        "query_limit_registered_in_prereg": False,
        "dataset": {
            "dataset_digest": DATASET_DIGEST,
            "truth_development_sha256": sha256_file(TRUTH_DEV),
            "dataset_manifest_sha256": sha256_file(MANIFEST),
            "development_worlds": manifest["counts"].get("development_worlds"),
            "development_episodes": manifest["counts"].get("development_episodes"),
            "development_packets": manifest["counts"].get("development_packets"),
        },
        "semantics_sources": sources,
        "shape": shape,
        "family_summary": dict(sorted(family_summary.items())),
        "k_coverage": k_coverage,
        "support_query_scope": support_query_scope,
        "derived": derived,
        "checks": {
            "steps_total_equals_manifest_packets": shape["steps_total_equals_manifest_packets"],
            "one_episode_per_world": support_query_scope["unique_episode_ids"] == support_query_scope["episodes"]
            and support_query_scope["rounds_per_world_registered"] == 1,
            "no_index_outside_episode": cross_episode_possible == 0,
            "k8_worlds": k_coverage["8"]["worlds_with_support_and_query"],
            "k4_worlds": k_coverage["4"]["worlds_with_support_and_query"],
        },
    }

    target = out_dir / "dev_coverage.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    meta = {
        "script": "reports/V9-P18/r3/analysis/r3_dev_coverage.py",
        "script_sha256": sha256_file(Path(__file__)),
        "output_root": str(out_dir),
        "output_files": ["dev_coverage.json", "run_meta.json"],
        "argv": sys.argv,
        "python": sys.version.split()[0],
        "started_at": started.isoformat(),
        "finished_at": datetime.datetime.now().astimezone().isoformat(),
        "deterministic_artifacts": ["dev_coverage.json"],
        "note": "run_meta.json is audit metadata only and is not part of the byte-identity claim",
    }
    (out_dir / "run_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"wrote {target}")
    print(
        "k coverage worlds/queries: "
        + ", ".join(
            f"k={k}:{k_coverage[str(k)]['worlds_with_support_and_query']}/{k_coverage[str(k)]['queries']}"
            for k in K_VALUES
        )
    )
    print(
        "derived few-shot: calls=%d stop_frames=%d transitions=%d probe_graph=%d encode=%d"
        % (
            derived["few_shot_step_sequence_calls"],
            derived["few_shot_repaired_stop_frames"],
            derived["few_shot_transitions"],
            derived["few_shot_probe_graph_calls"],
            derived["few_shot_encode_calls"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
