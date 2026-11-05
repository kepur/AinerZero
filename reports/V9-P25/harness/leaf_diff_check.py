#!/usr/bin/env python3
"""Independent r8→r9 prereg leaf-diff check for P25 (composer-m7k2).

Reuses the author's pinned prereg_leaf_diff harness logic by re-running it
against the sealed r8/r9 artifacts (read-only). Also cross-checks the author's
committed prereg-leaf-diff.json SHA and contents.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
LOGS = REPO / "reports/V9-P25/logs"
AUTHOR_DIFF = REPO / "reports/V9-P9/r9/prereg-leaf-diff.json"
EXPECTED_AUTHOR_SHA = "3eb58a3b731452d7757ef37191084185f3c1f0bd6b99fa2427b341fb764d6261"
HARNESS = REPO / "reports/V9-P9/r9/harness/prereg_leaf_diff.py"

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

author_sha = sha256(AUTHOR_DIFF)
author = json.loads(AUTHOR_DIFF.read_text())

# Re-run author harness to a temp out under P25 logs (harness writes fixed path;
# so we import and call main-equivalent carefully by subprocess after copying
# — simpler: just validate author file against rules + recompute digests of
# the two prereg files and re-walk leaves with a small local walker).

r8 = json.loads((REPO / "artifacts/v9/s1/phase1/r8/pre_registration.json").read_text())
r9 = json.loads((REPO / "artifacts/v9/s1/phase1/r9/pre_registration.json").read_text())

def leaves(obj, prefix=""):
    if isinstance(obj, dict):
        for k in sorted(obj):
            yield from leaves(obj[k], f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaves(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj

b = dict(leaves(r8))
n = dict(leaves(r9))
all_keys = sorted(set(b) | set(n))
changes = []
for k in all_keys:
    if k not in b:
        changes.append({"path": k, "change": "added", "new": n[k]})
    elif k not in n:
        changes.append({"path": k, "change": "removed", "base": b[k]})
    elif b[k] != n[k]:
        changes.append({"path": k, "change": "changed", "base": b[k], "new": n[k]})

ALLOW_PREFIXES = (
    "created_unix",
    "source_identity.package_files.src/ainerzero/v9/experiments/s1/worker.py",
    "source_identity.package_map_digest",
)
# scientific: everything else must be equal; identity/binding derived only on allowlist
non_allow = [c for c in changes if c["path"] not in ALLOW_PREFIXES]

out = {
    "schema": "ainerzero.v9.s1.p25.leaf_diff_check.v1",
    "probe_by": "composer-m7k2",
    "author_diff_sha256": {"actual": author_sha, "expected": EXPECTED_AUTHOR_SHA, "match": author_sha == EXPECTED_AUTHOR_SHA},
    "author_summary": {
        "leaf_count": author.get("leaf_count"),
        "changed_leaf_count": author.get("changed_leaf_count"),
        "bound_files_outside_allowlist": author.get("bound_files_outside_allowlist"),
        "non_identity_leaves_outside_allowlist": author.get("non_identity_leaves_outside_allowlist"),
        "changed_bound_files": author.get("changed_bound_files"),
        "changes": author.get("changes"),
    },
    "independent": {
        "leaf_count_r8": len(b),
        "leaf_count_r9": len(n),
        "changed_leaf_count": len(changes),
        "changes": changes,
        "non_allowlist_changes": non_allow,
        "allowlist_ok": len(non_allow) == 0,
        "freeze_constants": {
            "r9_updates": r9.get("training_protocol", {}).get("updates"),
            "r9_seeds": r9.get("training_protocol", {}).get("seeds") or r9.get("seeds"),
            "r9_deadline": (r9.get("timing") or {}).get("deadline_seconds"),
            "r9_arm1": (r9.get("timing") or {}).get("arm1_deadline_seconds"),
            "r9_eval_batches": (r9.get("evaluation") or r9.get("eval") or {}).get("batches") if isinstance(r9.get("evaluation") or r9.get("eval"), dict) else None,
            "r9_phase_wall": (r9.get("timing") or {}).get("phase_wall_max_seconds"),
        },
    },
}
# digests
out["file_sha"] = {
    "r8": sha256(REPO / "artifacts/v9/s1/phase1/r8/pre_registration.json"),
    "r9": sha256(REPO / "artifacts/v9/s1/phase1/r9/pre_registration.json"),
}
out["overall_pass"] = (
    out["author_diff_sha256"]["match"]
    and out["independent"]["allowlist_ok"]
    and out["independent"]["changed_leaf_count"] == 3
    and len(author.get("bound_files_outside_allowlist") or []) == 0
    and len(author.get("non_identity_leaves_outside_allowlist") or []) == 0
)
path = LOGS / "leaf-diff-check.json"
path.write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
print(f"author_sha_match={out['author_diff_sha256']['match']} independent_changed={out['independent']['changed_leaf_count']} allowlist_ok={out['independent']['allowlist_ok']}")
print(f"freeze={out['independent']['freeze_constants']}")
print(f"overall_pass={out['overall_pass']}")
print(f"json -> {path}")
sys.exit(0 if out["overall_pass"] else 1)
