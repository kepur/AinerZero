"""Independent r11 -> r12 leaf diff (reviewer's own implementation, P35).

Flattens both frozen documents to dotted leaf paths and reports every differing
leaf.  The allow-list is the card's rule: only experiment_id, source binding and
time-derived fields may differ.
"""
import json, sys

R11 = "artifacts/v9/s1/phase1/r11/pre_registration.json"
R12 = "artifacts/v9/s1/phase1/r12/pre_registration.json"
ALLOW_EXACT = {"experiment_id", "created_unix"}
ALLOW_PREFIX = (
    "source_identity.package_files.",
    "source_identity.package_map_digest",
    "source_identity.spec.sha256",
)


def flatten(node, prefix=""):
    out = {}
    if isinstance(node, dict):
        for k, v in node.items():
            out.update(flatten(v, f"{prefix}{k}." if not prefix else f"{prefix}{k}."))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1] if prefix else ""] = node
    return out


def main():
    a = json.load(open(R11, encoding="utf-8"))
    b = json.load(open(R12, encoding="utf-8"))
    fa, fb = flatten(a), flatten(b)
    only_a = sorted(set(fa) - set(fb))
    only_b = sorted(set(fb) - set(fa))
    changed = []
    for key in sorted(set(fa) & set(fb)):
        if fa[key] != fb[key]:
            changed.append({"leaf": key, "r11": fa[key], "r12": fb[key]})

    def allowed(leaf):
        if leaf in ALLOW_EXACT:
            return True
        return any(leaf.startswith(p) for p in ALLOW_PREFIX)

    outside = [row["leaf"] for row in changed if not allowed(row["leaf"])]
    payload = {
        "r11": R11,
        "r12": R12,
        "r11_leaf_count": len(fa),
        "r12_leaf_count": len(fb),
        "leaves_only_in_r11": only_a,
        "leaves_only_in_r12": only_b,
        "changed_leaf_count": len(changed),
        "changed_leaves": changed,
        "allowlist": {"exact": sorted(ALLOW_EXACT), "prefix": list(ALLOW_PREFIX)},
        "changed_outside_allowlist": outside,
        "identical": not only_a and not only_b and not changed,
    }
    # grouped equality of the scientific blocks the card names explicitly
    for block in ("training_protocol", "timing", "data_identity", "metrics",
                  "evaluation", "stop_rules", "arms", "resource_limits", "dataset"):
        payload[f"block_equal.{block}"] = a.get(block) == b.get(block)
    print(json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=False))
    return 0 if not outside and not only_a and not only_b else 2


if __name__ == "__main__":
    raise SystemExit(main())
