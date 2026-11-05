"""Why the S1 phase-1 place graphs form no topology edges (ainerzero.V9.P48 groundwork, tier-1 claude).

Read-only diagnostic on the DEVELOPMENT partition (never final): loads the frozen phase-1 checkpoints
(seed 0 of arm2/arm3/arm4, from the final pre-registration's inheritance cells), replays every dev
episode through ``MlxBackend.step_sequence`` on the MLX CPU device, and records per episode:
true visited cells / true edges, graph node count, directed vs mutual edges, self-loops, and the
cosine similarity of consecutive place keys.  It also scores two counterfactual readouts of the SAME
memory state (edge if either direction was walked; edge on node-pose adjacency) with the frozen
``metrics.topology_edge_metrics`` -- descriptive only, nothing here changes a registered metric.

No ledger, no run, no optimizer.  Writes only ./edge_formation.json next to this file.
"""
from __future__ import annotations

import collections
import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

import mlx.core as mx  # noqa: E402
import numpy as np  # noqa: E402

from ainerzero.v9.experiments.s1 import data, evaluation, metrics, runtime  # noqa: E402

mx.set_default_device(mx.cpu)
PHASE1 = REPO / "artifacts/v9/s1/phase1"
OUT = Path(__file__).resolve().parent / "edge_formation.json"
WALL_LIMIT_S = 600.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def graph_of(memory):
    graph = memory["graph"] if isinstance(memory, dict) and "graph" in memory else memory
    return graph if hasattr(graph, "edges") else None


def main() -> int:
    started = time.monotonic()
    ledger_before = sha256(PHASE1 / "control.sqlite3")
    prereg = json.loads((PHASE1 / "final/pre_registration.json").read_text(encoding="utf-8"))
    cells = {(c["arm_id"], int(c["seed"])): c for c in prereg["inheritance"]["cells"]}
    dataset_dir = data.resolve_dataset_dir(PHASE1)
    episodes = data.load_training_episodes(dataset_dir, "development")
    truth = evaluation.truth_index(data.load_truth_view(dataset_dir, "development"))
    sequences = [data.build_episode_sequence(e) for e in episodes]
    backend = runtime.MlxBackend()
    out = {"partition": "development", "ledger_sha256_before": ledger_before, "arms": {}}
    for arm in ("arm2", "arm3", "arm4"):
        cell = cells[(arm, 0)]
        params = PHASE1 / "runs" / cell["source_run_id"] / "params.npz"
        assert sha256(params) == cell["params_sha256"], f"{arm} params drift"
        model = backend.build_model(arm, seed=0)
        backend.load_params(model, params)
        rows = []
        for seq in sequences:
            if time.monotonic() - started > WALL_LIMIT_S:
                raise SystemExit("diagnostic wall limit reached")
            ep = truth[seq["episode_id"]]
            run = backend.step_sequence(model, seq)
            probe = backend.probe_graph(model, run["memory"], pose=run["pose"][-1])
            visited = evaluation.relative_cells(ep)
            true_edges = evaluation.relative_free_adjacency(ep)
            row = {"family": ep.family, "frames": len(seq["obs"]), "visited_cells": len(set(visited)),
                   "true_edges": len(true_edges), "probe_nodes": int(len(probe["positions"])),
                   "probe_edges": len(probe["edges"])}
            frozen = metrics.topology_edge_metrics(np.asarray(probe["positions"]).tolist(), sorted(probe["edges"]),
                                                   visited, true_edges)
            row["f1_frozen"] = frozen["f1"]
            g = graph_of(run["memory"])
            if g is not None:
                n = int(g.filled[0])
                e = np.asarray(g.edges[0, :n, :n])
                directed = {(i, j) for i in range(n) for j in range(n) if i != j and e[i, j] > 0}
                row.update({"directed_edges": len(directed), "self_loops": int(sum(e[i, i] > 0 for i in range(n))),
                            "mutual_edges": len({tuple(sorted(p)) for p in directed if (p[1], p[0]) in directed})})
                either = sorted({tuple(sorted(p)) for p in directed})
                row["f1_either_direction"] = metrics.topology_edge_metrics(
                    np.asarray(probe["positions"]).tolist(), either, visited, true_edges)["f1"]
                keys = [np.asarray(backend.probe_query(model, seq["obs"][t]), dtype=np.float64) for t in range(len(seq["obs"]))]
                sims = [float(a @ b / ((np.linalg.norm(a) + 1e-9) * (np.linalg.norm(b) + 1e-9))) for a, b in zip(keys, keys[1:])]
                row["consecutive_key_cosine"] = {"min": min(sims), "mean": float(np.mean(sims))} if sims else None
                row["threshold"] = float(g.match_threshold)
            rows.append(row)
        by_family = {}
        for fam in sorted({r["family"] for r in rows}):
            rs = [r for r in rows if r["family"] == fam]
            agg = {"episodes": len(rs)}
            for k in ("frames", "visited_cells", "true_edges", "probe_nodes", "probe_edges", "directed_edges",
                      "mutual_edges", "self_loops", "f1_frozen", "f1_either_direction"):
                vals = [r[k] for r in rs if k in r]
                if vals:
                    agg[k] = {"mean": float(np.mean(vals)), "min": float(np.min(vals)), "max": float(np.max(vals))}
            cos = [r["consecutive_key_cosine"]["min"] for r in rs if r.get("consecutive_key_cosine")]
            if cos:
                agg["consecutive_key_cosine_min"] = {"mean": float(np.mean(cos)), "min": float(np.min(cos))}
            agg["probe_nodes_histogram"] = dict(collections.Counter(r["probe_nodes"] for r in rs).most_common(6))
            by_family[fam] = agg
        out["arms"][arm] = {"run_id": cell["source_run_id"], "params_sha256": cell["params_sha256"], "by_family": by_family}
        print(arm, json.dumps({f: {k: v for k, v in a.items() if k in ("probe_nodes", "directed_edges", "mutual_edges", "f1_frozen", "f1_either_direction", "true_edges")} for f, a in by_family.items()}, default=str)[:1500])
    out["ledger_sha256_after"] = sha256(PHASE1 / "control.sqlite3")
    out["elapsed_s"] = time.monotonic() - started
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("elapsed", out["elapsed_s"], "ledger unchanged", out["ledger_sha256_after"] == ledger_before)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
