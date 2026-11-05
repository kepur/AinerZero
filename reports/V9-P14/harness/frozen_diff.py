#!/usr/bin/env python3
"""P14 review: r4 frozen identity reproduction + leaf-level diff against r3.

Read-only. Writes only into reports/V9-P14/.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
R3 = REPO / "reports/V9-P9/r3/pre_registration.json"
R4 = REPO / "reports/V9-P9/r4/pre_registration.json"
AUTH = REPO / "artifacts/v9/s1/phase1/pre_registration.json"
OUT = REPO / "reports/V9-P14"


def canonical(document) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def doc_sha(document) -> str:
    return hashlib.sha256(canonical(document)).hexdigest()


def flatten(node, prefix=""):
    out = {}
    if isinstance(node, dict):
        if not node:
            out[prefix] = {}
        for key, value in node.items():
            out.update(flatten(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(node, list):
        if not node:
            out[prefix] = []
        for index, value in enumerate(node):
            out.update(flatten(value, f"{prefix}[{index}]"))
    else:
        out[prefix] = node
    return out


def block_sha(document, key):
    return hashlib.sha256(canonical(document[key])).hexdigest()


def main() -> int:
    r3 = json.loads(R3.read_text(encoding="utf-8"))
    r4 = json.loads(R4.read_text(encoding="utf-8"))
    auth = json.loads(AUTH.read_text(encoding="utf-8"))

    f3, f4 = flatten(r3), flatten(r4)
    only_r3 = sorted(set(f3) - set(f4))
    only_r4 = sorted(set(f4) - set(f3))
    changed = sorted(k for k in set(f3) & set(f4) if f3[k] != f4[k])

    def group(path):
        return path.split(".")[0].split("[")[0]

    change_groups = {}
    for key in changed:
        change_groups[group(key)] = change_groups.get(group(key), 0) + 1

    immutable = [
        "arms",
        "training_protocol",
        "data_identity",
        "resource_limits",
        "metrics",
        "stop_rules",
        "budget_estimate",
    ]
    block_cmp = {}
    for key in immutable:
        present = key in r3 and key in r4
        same_bytes = canonical(r3.get(key)) == canonical(r4.get(key)) if present else False
        block_cmp[key] = {
            "present_in_both": present,
            "byte_identical": same_bytes,
            "r3_sha256": block_sha(r3, key) if key in r3 else None,
            "r4_sha256": block_sha(r4, key) if key in r4 else None,
        }

    # Frozen numeric identity: parameters / budget / seeds / steps / resource lines.
    numeric = {
        "arm_parameters": {
            arm: {
                "parameters": r4["arms"][arm].get("parameters"),
                "training_updates": r4["arms"][arm].get("training_updates"),
                "seeds": r4["arms"][arm].get("seeds"),
                "same_as_r3": canonical(r3["arms"][arm]) == canonical(r4["arms"][arm]),
            }
            for arm in sorted(r4["arms"])
        },
        "timing_r4": r4.get("timing"),
        "timing_same_leafwise": {
            k: (f3.get(f"timing.{k}") == f4.get(f"timing.{k}"))
            for k in sorted({k.split(".", 1)[1] for k in list(f3) + list(f4) if k.startswith("timing.")})
        },
        "resource_limits_r4": r4.get("resource_limits"),
        "metrics_block_r4": r4.get("metrics"),
        "stop_rules_r4": r4.get("stop_rules"),
        "budget_estimate_r4": r4.get("budget_estimate"),
        "updates_same": r3["training_protocol"].get("updates") == r4["training_protocol"].get("updates"),
        "seed_list_same": r3["training_protocol"].get("seeds") == r4["training_protocol"].get("seeds"),
        "resource_lines_same": canonical(r3["resource_limits"]) == canonical(r4["resource_limits"]),
        "metric_definitions_same": canonical(r3["metrics"]) == canonical(r4["metrics"]),
        "stop_rules_same": canonical(r3["stop_rules"]) == canonical(r4["stop_rules"]),
    }

    result = {
        "schema": "ainerzero.v9.p14.frozen-diff.v1",
        "inputs": {
            "r3": {"path": str(R3), "document_sha256": doc_sha(r3), "file_sha256": hashlib.sha256(R3.read_bytes()).hexdigest()},
            "r4": {"path": str(R4), "document_sha256": doc_sha(r4), "file_sha256": hashlib.sha256(R4.read_bytes()).hexdigest()},
            "authoritative": {
                "path": str(AUTH),
                "document_sha256": doc_sha(auth),
                "file_sha256": hashlib.sha256(AUTH.read_bytes()).hexdigest(),
            },
        },
        "claims": {
            "r3_document_sha256_expected": "ed39c97c5747daeb3f810658882dd5f9510b854e4f95048dad801205b1f55c94",
            "r4_document_sha256_expected": "6cbe7eada77d760860cae44490998e2b0a7ac223006471df411e7a9943c39842",
            "r4_file_sha256_expected": "e9f0844afef787d0e75eb12f5365660c7c8a3a99e918ca10962b60ec5aae64d9",
        },
        "leaf_diff": {
            "leaves_r3": len(f3),
            "leaves_r4": len(f4),
            "only_in_r3": only_r3,
            "only_in_r4": only_r4,
            "changed_leaf_paths": changed,
            "changed_leaf_count": len(changed),
            "changed_groups": change_groups,
            "values": {k: {"r3": f3.get(k), "r4": f4.get(k)} for k in changed},
        },
        "immutable_blocks": block_cmp,
        "numeric_identity": numeric,
    }

    checks = {
        "r4_document_sha_matches_claim": doc_sha(r4) == result["claims"]["r4_document_sha256_expected"],
        "r3_document_sha_matches_claim": doc_sha(r3) == result["claims"]["r3_document_sha256_expected"],
        "r4_file_sha_matches_claim": result["inputs"]["r4"]["file_sha256"] == result["claims"]["r4_file_sha256_expected"],
        "reports_copy_equals_authoritative": result["inputs"]["r4"]["file_sha256"] == result["inputs"]["authoritative"]["file_sha256"],
        "changed_groups_subset_of_claimed": set(change_groups) <= {"commands", "created_unix", "effective_metadata", "source_identity"},
        "all_immutable_blocks_byte_identical": all(v["byte_identical"] for v in block_cmp.values()),
        "all_arm_blocks_identical": all(v["same_as_r3"] for v in numeric["arm_parameters"].values()),
        "updates_identical": numeric["updates_same"],
        "seeds_identical": numeric["seed_list_same"],
        "resource_lines_identical": numeric["resource_lines_same"],
        "metric_definitions_identical": numeric["metric_definitions_same"],
        "stop_rules_identical": numeric["stop_rules_same"],
    }
    result["checks"] = checks
    result["verdict"] = "zero_substantive_difference" if all(checks.values()) else "difference_found"

    (OUT / "frozen-diff.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({"checks": checks, "changed_leaf_count": len(changed), "changed_groups": change_groups,
                      "changed": changed, "verdict": result["verdict"]}, indent=1))
    return 0 if result["verdict"] == "zero_substantive_difference" else 1


if __name__ == "__main__":
    raise SystemExit(main())
