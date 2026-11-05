"""Truth-only statistics for ainerzero.V9.P18.

No model, no backend, no MLX.  Everything here is computed from the frozen
development truth sidecar with the frozen ``metrics.split_support_query``
semantics, so the numbers do not depend on any substitute network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
SNAP = Path(
    "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot"
)
DATASET = (
    REPO
    / "artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
)
OUT = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-P19")
ISO = Path("/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/v9p19/iso")

K_VALUES = (0, 1, 2, 4, 8)


def main() -> int:
    sys.path.insert(0, str(ISO))
    from ainerzero.v9.experiments.s1 import data, evaluation, metrics

    truth = data.load_truth_view(DATASET, "development")

    rows = []
    for ep in truth:
        cells = evaluation.relative_cell_path(ep)
        edges = evaluation.relative_free_adjacency(ep)
        transitions = max(len(ep.steps) - 1, 0)
        rows.append(
            {
                "episode_id": ep.episode_id,
                "family": ep.family or "unknown",
                "steps": len(ep.steps),
                "transitions": transitions,
                "cells": cells,
                "edges": edges,
            }
        )

    per_k = {}
    for k in K_VALUES:
        worlds = 0
        queries = 0
        true_positive_class = 0
        reachable = 0
        by_family = {}
        support_written = 0
        for row in rows:
            support, query = metrics.split_support_query(row["transitions"], k)
            if not query:
                continue
            worlds += 1
            fam = row["family"]
            slot = by_family.setdefault(fam, {"worlds": 0, "queries": 0, "true_edges": 0, "reachable": 0})
            slot["worlds"] += 1
            # frames actually executed by step_sequence(stop=support[-1] + 1)
            support_written += max(len(support) - 1, 0)
            support_cells = set(row["cells"][: len(support) + 1]) if support else set()
            for index in query:
                queries += 1
                slot["queries"] += 1
                edge = tuple(sorted((row["cells"][index], row["cells"][index + 1])))
                if edge in row["edges"]:
                    true_positive_class += 1
                    slot["true_edges"] += 1
                if row["cells"][index + 1] in support_cells:
                    reachable += 1
                    slot["reachable"] += 1
        per_k[str(k)] = {
            "worlds": worlds,
            "queries": queries,
            "true_edge_rate": round(true_positive_class / queries, 6) if queries else None,
            "query_destination_already_in_support_memory": reachable,
            "destination_in_support_fraction": round(reachable / queries, 6) if queries else None,
            "support_transitions_actually_executed_per_world": (max(k - 1, 0) if k else 0),
            "support_transitions_requested_per_world": k,
            "by_family": dict(sorted(by_family.items())),
        }

    family_summary = {}
    transition_kind = {}
    for row in rows:
        slot = family_summary.setdefault(
            row["family"], {"worlds": 0, "steps": {}, "transitions": row["transitions"]}
        )
        slot["worlds"] += 1
        slot["steps"][str(row["steps"])] = slot["steps"].get(str(row["steps"]), 0) + 1
        slot["max_k_with_any_world"] = max(
            [k for k in K_VALUES if row["transitions"] >= k + 1] or [-1]
        )
        kind = transition_kind.setdefault(
            row["family"], {"stay": 0, "adjacent": 0, "non_adjacent": 0, "distinct_cells": 0}
        )
        cells = row["cells"]
        kind["distinct_cells"] += len(set(cells))
        for index in range(len(cells) - 1):
            a, b = cells[index], cells[index + 1]
            if a == b:
                kind["stay"] += 1
            elif abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1:
                kind["adjacent"] += 1
            else:
                kind["non_adjacent"] += 1

    payload = {
        "schema": "ainerzero.v9.p18.truth-stats.v1",
        "task": "ainerzero.V9.P18",
        "executor": "deepseek-p18a",
        "source": "frozen development truth sidecar, read-only",
        "development_worlds": len(rows),
        "total_transitions": sum(row["transitions"] for row in rows),
        "family_summary": dict(sorted(family_summary.items())),
        "transition_kind_by_family": dict(sorted(transition_kind.items())),
        "per_k": per_k,
        "note": "true_edge_rate is the class balance of the held-out query transitions; it is the "
        "accuracy a predictor that always answers 'no edge' would reach at k=0.",
    }
    (OUT / "analysis" / "truth_stats.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
