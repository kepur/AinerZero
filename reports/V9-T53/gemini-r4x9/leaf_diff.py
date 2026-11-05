#!/usr/bin/env python3
"""Independent leaf-level diff checker for proposal.json vs pre-E18-1694ed30.

Verifies that ONLY the authorized subtrees were modified:
- amendment
- budget.view_accounting
- budget.cumulative_wall_seconds_max
- budget.wall_accounting
- open_items
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LOG_FILE = HERE / "logs" / "leaf_diff.log"

PREV_PATH = REPO / "reports" / "V9-T28" / "r2" / "pre-E18-1694ed30" / "proposal.json"
CUR_PATH = REPO / "reports" / "V9-T28" / "r2" / "proposal.json"

ALLOWED_PREFIXES = (
    ("amendment",),
    ("budget", "view_accounting"),
    ("budget", "cumulative_wall_seconds_max"),
    ("budget", "wall_accounting"),
    ("open_items",),
)


def traverse_leaves(node, current_path=()):
    if isinstance(node, dict):
        for key, val in node.items():
            yield from traverse_leaves(val, current_path + (str(key),))
    elif isinstance(node, (list, tuple)):
        for idx, val in enumerate(node):
            yield from traverse_leaves(val, current_path + (idx,))
    else:
        yield current_path, node


def main():
    prev_obj = json.loads(PREV_PATH.read_text(encoding="utf-8"))
    cur_obj = json.loads(CUR_PATH.read_text(encoding="utf-8"))

    prev_leaves = dict(traverse_leaves(prev_obj))
    cur_leaves = dict(traverse_leaves(cur_obj))

    all_paths = sorted(set(prev_leaves.keys()) | set(cur_leaves.keys()), key=lambda p: tuple(str(x) for x in p))

    changed = []
    for p in all_paths:
        v_prev = prev_leaves.get(p, "<ABSENT>")
        v_cur = cur_leaves.get(p, "<ABSENT>")
        if v_prev != v_cur:
            changed.append((p, v_prev, v_cur))

    log_lines = []
    log_lines.append(f"Total leaves in pre-E18: {len(prev_leaves)}")
    log_lines.append(f"Total leaves in E18: {len(cur_leaves)}")
    log_lines.append(f"Total leaves changed: {len(changed)}")

    unauthorized = []
    for path, v1, v2 in changed:
        # Check against allowed prefixes
        allowed = False
        for prefix in ALLOWED_PREFIXES:
            if len(path) >= len(prefix) and path[:len(prefix)] == prefix:
                allowed = True
                break
        if not allowed:
            unauthorized.append((path, v1, v2))

    log_lines.append(f"Unauthorized changes count: {len(unauthorized)}")
    if unauthorized:
        log_lines.append("UNAUTHORIZED CHANGES DETECTED:")
        for p, v1, v2 in unauthorized:
            log_lines.append(f"  Path: {p}")
            log_lines.append(f"    - Old: {v1}")
            log_lines.append(f"    + New: {v2}")
    else:
        log_lines.append("ALL CHANGED LEAVES FALL STRICTLY WITHIN AUTHORIZED PREFIXES.")

    log_lines.append("\nSummary of modifications by prefix:")
    for prefix in ALLOWED_PREFIXES:
        matching = [c for c in changed if len(c[0]) >= len(prefix) and c[0][:len(prefix)] == prefix]
        prefix_str = ".".join(str(x) for x in prefix)
        log_lines.append(f"  - {prefix_str}: {len(matching)} leaf change(s)")
        for p, v1, v2 in matching:
            path_str = ".".join(str(x) for x in p)
            v1_repr = repr(v1) if len(repr(v1)) < 60 else repr(v1)[:57] + "..."
            v2_repr = repr(v2) if len(repr(v2)) < 60 else repr(v2)[:57] + "..."
            log_lines.append(f"      {path_str}: {v1_repr} -> {v2_repr}")

    # Check that top level sections not allowed are byte-for-byte identical
    other_top_keys = [k for k in prev_obj if k not in ("amendment", "budget", "open_items")]
    log_lines.append(f"\nChecking untouched top-level keys: {other_top_keys}")
    for k in other_top_keys:
        assert prev_obj[k] == cur_obj[k], f"Top-level key {k} modified!"
    log_lines.append("All other top-level keys are identical.")

    # Check budget subkeys
    budget_modified_keys = sorted(k for k in prev_obj["budget"] if prev_obj["budget"][k] != cur_obj["budget"].get(k))
    log_lines.append(f"Modified budget subkeys: {budget_modified_keys}")
    assert budget_modified_keys == ["cumulative_wall_seconds_max", "view_accounting", "wall_accounting"], f"Unexpected budget changes: {budget_modified_keys}"

    result_text = "\n".join(log_lines)
    print(result_text)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(result_text + "\n", encoding="utf-8")

    if unauthorized:
        sys.exit(1)
    print("\nLEAF DIFF STATUS: PASS")


if __name__ == "__main__":
    main()
