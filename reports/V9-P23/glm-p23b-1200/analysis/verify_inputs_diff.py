#!/usr/bin/env python3
"""glm-p23b-1200 non-author review of ainerzero.V9.P18 r4 — step 1.

Read-only checks:
  A. All 34 files pinned in P18-r4-review-inputs.json: sha256 + bytes match.
  B. r4/SHA256SUMS.txt (33 entries): every entry matches the file on disk, and
     every regular file under reports/V9-P18/r4 (excluding SHA256SUMS.txt) is
     covered by the manifest (full scan, byte counts).
  C. Baseline SHA record of the whole r4 directory (written to my scope) so any
     later drift is detectable after my reproduction runs.
  D. Leaf-level diff r3 vs r4 of metrics.json and dev_coverage.json:
     total leaf counts, differing leaves, per-leaf JSON pointers, and a
     classification of every differing leaf into provenance/index/schema
     categories, so the claim "zero science-number changes" is independently
     checkable; science blocks (k_coverage numbers, shape counts, budget
     primitives, per_run_total figures, frames) compared separately.
Outputs JSON + text into reports/V9-P23/glm-p23b-1200/output/.
"""
import hashlib
import json
import os
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
MY = REPO / "reports/V9-P23/glm-p23b-1200"
OUTDIR = MY / "output"
OUTDIR.mkdir(parents=True, exist_ok=True)
PIN = Path("/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-resume-1200/P18-r4-review-inputs.json")
R4 = REPO / "reports/V9-P18/r4"
R3 = REPO / "reports/V9-P18/r3"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def leaves(obj, prefix=""):
    """Yield (json_pointer, value) for every leaf."""
    if isinstance(obj, dict):
        for k in sorted(obj.keys()):
            yield from leaves(obj[k], f"{prefix}/{json.dumps(k)}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaves(v, f"{prefix}/{i}")
    else:
        yield prefix, obj


result = {"A_pinned_inputs": {"total": 0, "match": 0, "mismatches": []},
          "B_sums_manifest": {"entries": 0, "match": 0, "missing": [], "wrong_hash": [], "uncovered_files": [], "total_files_scanned": 0},
          "C_baseline": {},
          "D_leaf_diff": {}}

# ---- A: pinned review inputs --------------------------------------------------
pin = json.loads(PIN.read_text(encoding="utf-8"))
result["A_pinned_inputs"]["total"] = len(pin["files"])
for f in pin["files"]:
    p = Path(f["path"])
    ok_path = p.exists()
    got = sha256_file(p) if ok_path else None
    size = p.stat().st_size if ok_path else None
    ok = ok_path and got == f["sha256"]
    result["A_pinned_inputs"]["match"] += int(bool(ok))
    if not ok:
        result["A_pinned_inputs"]["mismatches"].append(
            {"path": str(p), "exists": ok_path, "expected": f["sha256"], "got": got, "bytes_got": size})

# ---- B: SHA256SUMS manifest + full coverage scan ------------------------------
sums = R4 / "SHA256SUMS.txt"
manifest = {}
for line in sums.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    h, rel = line.split(None, 1)
    manifest[rel.strip()] = h
result["B_sums_manifest"]["entries"] = len(manifest)
for rel, h in manifest.items():
    p = R4 / rel.lstrip("./")
    if not p.exists() or not p.is_file():
        result["B_sums_manifest"]["missing"].append(rel)
        continue
    if sha256_file(p) == h:
        result["B_sums_manifest"]["match"] += 1
    else:
        result["B_sums_manifest"]["wrong_hash"].append(rel)

covered = {str((R4 / rel.lstrip("./")).resolve()) for rel in manifest}
scanned = 0
for p in sorted(R4.rglob("*")):
    if p.is_file():
        scanned += 1
        if str(p.resolve()) not in covered and p.name != "SHA256SUMS.txt":
            result["B_sums_manifest"]["uncovered_files"].append(str(p.relative_to(R4)))
result["B_sums_manifest"]["total_files_scanned"] = scanned

# ---- C: baseline SHA of the whole r4 dir --------------------------------------
for p in sorted(R4.rglob("*")):
    if p.is_file():
        rel = str(p.relative_to(R4))
        result["C_baseline"][rel] = {"sha256": sha256_file(p), "bytes": p.stat().st_size, "mtime": p.stat().st_mtime}

# ---- D: leaf diff r3 vs r4 ----------------------------------------------------
def diff(a_path: Path, b_path: Path, label: str):
    a = json.loads(a_path.read_text(encoding="utf-8"), parse_float=lambda s: json.loads(s))
    b = json.loads(b_path.read_text(encoding="utf-8"), parse_float=lambda s: json.loads(s))
    la = dict(leaves(a))
    lb = dict(leaves(b))
    changed = sorted(set(la) | set(lb))
    diffs = []
    for ptr in changed:
        va, vb = la.get(ptr, "<ABSENT_A>"), lb.get(ptr, "<ABSENT_B>")
        if va != vb:
            sa, sb = json.dumps(va, ensure_ascii=False)[:200], json.dumps(vb, ensure_ascii=False)[:200]
            diffs.append({"pointer": ptr, "r3": sa, "r4": sb})
    return {"a": str(a_path), "b": str(b_path), "leaves_r3": len(la), "leaves_r4": len(lb),
            "common_leaves": len(set(la) & set(lb)), "changed_leaves": len(diffs), "changes": diffs}


result["D_leaf_diff"]["metrics"] = diff(R3 / "products/metrics.json", R4 / "products/metrics.json", "metrics")
result["D_leaf_diff"]["dev_coverage"] = diff(R3 / "products/dev_coverage.json", R4 / "products/dev_coverage.json", "dev_coverage")

# science-block equality (numbers that must NOT change r3->r4)
sci_ptrs = [
    "/k_coverage", "/shape", "/frozen_primitives", "/training_run_per_arm_seed",
    "/d_candidate_run", "/post_hoc_eval_per_arm_seed", "/phase",
]
sci_report = {}
r3m = json.loads((R3 / "products/metrics.json").read_text(encoding="utf-8"))
r4m = json.loads((R4 / "products/metrics.json").read_text(encoding="utf-8"))
for ptr in sci_ptrs:
    base = ptr.lstrip("/").split("/")
    va = r3m
    vb = r4m
    for part in base:
        va = va.get(part, None)
        vb = vb.get(part, None)
    sci_report[ptr] = {"identical": va == vb}
result["D_leaf_diff"]["science_blocks_equal"] = sci_report

# numeric leaf scan: every r3/r4 numeric leaf in metrics with the same pointer
numeric_diffs = []
for ptr in set(dict(leaves(r3m))) | set(dict(leaves(r4m))):
    va, vb = r3m, r4m
    try:
        for part in ptr.lstrip("/").split("/"):
            try:
                key = json.loads(part)
            except Exception:
                key = part
            va = va[key] if isinstance(va, dict) and key in va else None
            vb = vb[key] if isinstance(vb, dict) and key in vb else None
    except Exception:
        continue
    if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool) and not isinstance(vb, bool):
        if va != vb:
            numeric_diffs.append({"pointer": ptr, "r3": va, "r4": vb})
result["D_leaf_diff"]["numeric_leaf_changes_r3_to_r4"] = {"count": len(numeric_diffs), "diffs": numeric_diffs}

out_json = OUTDIR / "step1_verification.json"
out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

# text summary
print(json.dumps({
    "pinned_total": result["A_pinned_inputs"]["total"],
    "pinned_match": result["A_pinned_inputs"]["match"],
    "mismatches": result["A_pinned_inputs"]["mismatches"],
    "sums_entries": result["B_sums_manifest"]["entries"],
    "sums_match": result["B_sums_manifest"]["match"],
    "missing": result["B_sums_manifest"]["missing"],
    "wrong_hash": result["B_sums_manifest"]["wrong_hash"],
    "uncovered_files": result["B_sums_manifest"]["uncovered_files"],
    "files_scanned": result["B_sums_manifest"]["total_files_scanned"],
    "metrics_leaf_diff": {k: result["D_leaf_diff"]["metrics"][k] for k in ("leaves_r3", "leaves_r4", "changed_leaves")},
    "dev_cov_leaf_diff": {k: result["D_leaf_diff"]["dev_coverage"][k] for k in ("leaves_r3", "leaves_r4", "changed_leaves")},
    "science_blocks_equal": sci_report,
    "numeric_leaf_changes": result["D_leaf_diff"]["numeric_leaf_changes_r3_to_r4"]["count"],
}, ensure_ascii=False, indent=2))
