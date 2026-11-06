#!/usr/bin/env python3
"""ainerzero.V9.A15 -- baseline freeze manifest v4 (r4: ADR-0012 / V9 post-10-20 deliverables absorption).

What changed from r3 (r1, r2, r3 evidence preserved verbatim):
1. Absorbs legitimate post-10-20 deliverables into the baseline manifest:
   - E1 Phase 2 & Phase 2-r2: checkpoints (npz), eval reports (json), registrations (prereg*.json, .sha256),
     dataset manifests (generator_identity.json, SHA256SUMS.txt, raw/manifest.json),
     sealed final datasets (sealed_final/** as raw bytes without parsing or read_once triggers),
     and control.sqlite3 (row-level RunStore).
   - S1 Phase 1, datasets, final-sealed: registrations, checkpoints (npz), reports, datasets, sealed_final.
   - Teachers: approved model weights and configs (t4-approved, da3) and benchmark runstore (runs.db).
   - OS metadata (.DS_Store) explicitly excluded with reason.
   - E1 intermediate trajectory JSONs (datasets/raw/**, evaluator/**, student/**) explicitly excluded with reason.
2. Single source of truth (RULES) strictly maintained; every file under artifacts/ has exactly one
   unambiguous disposition (unclassified == 0).
3. Selftest maintains all 22 r3 test cases and adds 2 new injection cases:
   - Injecting NOTES.md into an E1 phase2 checkpoint directory clone -> RED (unexpected_new_file);
   - Flipping one byte in an E1 phase2 sealed_final file clone -> RED (sha256_changed).
4. Pure CPU, zero network, zero GPU/MLX, zero writes to real artifacts tree.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re as _re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCHEMA = "ainerzero.v9.baseline_manifest.v4"
ROUND_DIR = Path("reports/V9-baseline/r4/r2")
DEFAULT_MANIFEST = ROUND_DIR / "baseline_manifest.json"
DEFAULT_INVENTORY = ROUND_DIR / "BASELINE_INVENTORY.md"
DEFAULT_SELFTEST = ROUND_DIR / "selftest.json"
DEFAULT_INTEGRITY = ROUND_DIR / "real_tree_integrity.json"

CHUNK = 1 << 20

# The two trees that are not model baselines. Registrations inside them are still pinned;
# everything else there is out of scope.
EXEMPT_ROOTS = ("artifacts/reports", "artifacts/spacetime")

# --------------------------------------------------------------------------- rules
RULES: list[dict] = [
    {
        "rule": "os_metadata",
        "action": "exclude",
        "reason": "os_metadata",
        "globs": ["artifacts/**/.DS_Store"],
        "in_exempt": True,
        "detail": "macOS Finder metadata files (.DS_Store), excluded from baseline.",
    },
    {
        "rule": "volatile_scratch",
        "action": "volatile",
        "globs": ["artifacts/**/tmp/**", "artifacts/**/tmp-*/**"],
        "in_exempt": True,
        "detail": "Test scratch: any path component named 'tmp' or 'tmp-*'. A later "
                  "test run may legitimately rewrite these bytes, so they are recorded "
                  "by name (observed volatile set) instead of being pinned.",
    },
    {
        "rule": "sqlite_transient",
        "action": "exclude",
        "reason": "sqlite_transient",
        "globs": ["artifacts/**/*-wal", "artifacts/**/*-shm"],
        "in_exempt": True,
        "detail": "SQLite -wal/-shm side files. They appear/disappear with ordinary "
                  "read/write activity, so they cannot be pinned. Presence is recorded, "
                  "content identity comes from entries_digest.",
    },
    {
        "rule": "registration",
        "action": "pin",
        "category": "registration",
        "globs": [
            "artifacts/**/*registration*.json",
            "artifacts/**/*registration*.md",
            "artifacts/v9/e1/phase2/prereg*.json",
            "artifacts/v9/e1/phase2/prereg*.json.sha256",
            "artifacts/v9/e1/phase2-r2/prereg*.json",
            "artifacts/v9/e1/phase2-r2/prereg*.json.sha256",
            "artifacts/v9/s1/**/*.sha256",
        ],
        "in_exempt": True,
        "detail": "Run / experiment registrations, pre-registrations and checksums, "
                  "wherever they live (including registrations archived under artifacts/reports/).",
    },
    {
        "rule": "runstore.file",
        "action": "pin",
        "category": "runstore.file",
        "globs": [
            "artifacts/control.sqlite3",
            "artifacts/control.sqlite3.bak-20261011",
            "artifacts/m0/control.sqlite3",
            "artifacts/run_store.db",
            "artifacts/v9/e1/phase2/control.sqlite3",
            "artifacts/v9/e1/phase2-r2/control.sqlite3",
            "artifacts/v9/s1/phase1/control.sqlite3",
            "artifacts/v9/teachers/benchmark/runs.db",
        ],
        "in_exempt": False,
        "detail": "RunStore databases. Identity is row-level (see policy.runstore); the "
                  "file sha256/size recorded here is secondary evidence only.",
    },
    {
        "rule": "checkpoint",
        "action": "pin",
        "category": "checkpoint",
        "globs": [
            "artifacts/**/*.safetensors",
            "artifacts/v9/e1/phase2/checkpoints/**",
            "artifacts/v9/e1/phase2-r2/checkpoints/**",
            "artifacts/v9/s1/phase1/runs/*/checkpoints/**",
            "artifacts/v9/s1/phase1/runs/*/params.npz",
            "artifacts/teachers/t4-approved/**",
            "artifacts/teachers/da3/**",
        ],
        "in_exempt": False,
        "detail": "Baseline checkpoints, model weights, and teacher weights are hashed as bytes; "
                  "no MLX / ORT / tensor library is imported and no checkpoint is loaded.",
    },
    {
        "rule": "checkpoint.meta",
        "action": "pin",
        "category": "checkpoint.meta",
        "globs": [
            "artifacts/pilot/*/checkpoints/*/manifest.json",
            "artifacts/pilot/*/checkpoints/*/metadata.json",
            "artifacts/m0/*/checkpoints/midpoint/manifest.json",
            "artifacts/m0/*/checkpoints/midpoint/metadata.json",
        ],
        "in_exempt": False,
        "detail": "Per-checkpoint manifest/metadata.",
    },
    {
        "rule": "m0.run",
        "action": "pin",
        "category": "m0.run",
        "globs": [
            "artifacts/m0/*/report.json",
            "artifacts/m0/*/events.jsonl",
            "artifacts/m0/*/config.yaml",
            "artifacts/m0/*/requested_config.yaml",
        ],
        "in_exempt": False,
        "detail": "M0 run-root report/events/config.",
    },
    {
        "rule": "run.config",
        "action": "pin",
        "category": "run.config",
        "globs": [
            "artifacts/pilot/*/report.json",
            "artifacts/pilot/*/updates.jsonl",
            "artifacts/pilot/*/fixed-batch.npz",
            "artifacts/pilot/*/training-pool.npz",
            "artifacts/pilot/*/training-schedule.npy",
            "artifacts/pilot/*/dataset.json",
        ],
        "in_exempt": False,
        "detail": "Pilot run-root data / report / config.",
    },
    {
        "rule": "run.updates",
        "action": "pin",
        "category": "run.updates",
        "globs": ["artifacts/pilot/*/updates-*.jsonl"],
        "in_exempt": False,
        "detail": "Per-checkpoint update logs.",
    },
    {
        "rule": "probe.meta",
        "action": "pin",
        "category": "probe.meta",
        "globs": [
            "artifacts/pilot/*/probes/*/manifest.json",
            "artifacts/pilot/*/probes/*/metadata.json",
        ],
        "in_exempt": False,
        "detail": "Probe bundles under a pilot run.",
    },
    {
        "rule": "dataset.c0",
        "action": "pin",
        "category": "dataset.c0",
        "globs": ["artifacts/c0/**"],
        "in_exempt": False,
        "detail": "C0 episode dataset directories, pinned wholesale.",
    },
    {
        "rule": "dataset.gridlab2d",
        "action": "pin",
        "category": "dataset.gridlab2d",
        "globs": ["artifacts/gridlab2d/**"],
        "in_exempt": False,
        "detail": "GridLab2D dataset directories, pinned wholesale.",
    },
    {
        "rule": "eval.report",
        "action": "pin",
        "category": "eval.report",
        "globs": [
            "artifacts/v9/e1/phase2/eval/**",
            "artifacts/v9/e1/phase2-r2/eval/**",
            "artifacts/v9/s1/phase1/*report*.json",
            "artifacts/v9/s1/phase1/*metrics*.json",
            "artifacts/v9/s1/phase1/dataset_ref.json",
            "artifacts/v9/s1/phase1/*/dataset_ref.json",
            "artifacts/v9/s1/phase1/runs/*/*.json",
            "artifacts/v9/s1/phase1/*/*.txt",
        ],
        "in_exempt": False,
        "detail": "Evaluation and execution reports across E1 and S1.",
    },
    {
        "rule": "dataset.sealed_final",
        "action": "pin",
        "category": "dataset.sealed_final",
        "globs": [
            "artifacts/v9/e1/phase2/datasets/generator_identity.json",
            "artifacts/v9/e1/phase2/datasets/SHA256SUMS.txt",
            "artifacts/v9/e1/phase2/datasets/raw/manifest.json",
            "artifacts/v9/e1/phase2/datasets/sealed_final/**",
            "artifacts/v9/s1/datasets/**",
            "artifacts/v9/s1/final-sealed/**",
        ],
        "in_exempt": False,
        "detail": "Sealed final datasets and dataset manifest deliverables. Hashed strictly as raw bytes.",
    },
    {
        "rule": "dataset.e1",
        "action": "pin",
        "category": "dataset.e1",
        "globs": [
            "artifacts/v9/e1/phase2/datasets/raw/P/**",
            "artifacts/v9/e1/phase2/datasets/raw/S/**",
            "artifacts/v9/e1/phase2/datasets/evaluator/**",
            "artifacts/v9/e1/phase2/datasets/student/**",
        ],
        "in_exempt": False,
        "detail": "E1 Phase 2 train/development datasets (raw, evaluator, student splits). "
                  "Pinned strictly by byte SHA256 to guarantee reproducibility of E1 checkpoints and dev results.",
    },
    {
        "rule": "teacher_cache",
        "action": "exclude",
        "reason": "derived_artifact",
        "globs": ["artifacts/**/*teacher-cache*.npz", "artifacts/**/*teacher-cache*.json"],
        "in_exempt": False,
        "detail": "Teacher caches (incl. probe-teacher-cache*) are derived artifacts; "
                  "their identity is carried by the upstream run registration.",
    },
    {
        "rule": "episode_data",
        "action": "exclude",
        "reason": "episode_data",
        "globs": ["artifacts/**/episodes/**"],
        "in_exempt": False,
        "detail": "Per-episode trajectory data; not part of the frozen baseline.",
    },
    {
        "rule": "runtime_lock",
        "action": "exclude",
        "reason": "runtime_lock",
        "globs": ["artifacts/locks/**"],
        "in_exempt": False,
        "detail": "Runtime lock files (m0-worker.lock). Ownership marker, not a baseline artifact.",
    },
]

# --------------------------------------------------------------------------- globs
def glob_match(pattern: str, path: str) -> bool:
    """Segment-wise glob with ``**`` = zero or more whole path segments."""
    pat = pattern.split("/")
    parts = path.split("/")

    def walk(i: int, j: int) -> bool:
        while True:
            if i == len(pat):
                return j == len(parts)
            if pat[i] == "**":
                if i == len(pat) - 1:
                    return True
                for k in range(j, len(parts) + 1):
                    if walk(i + 1, k):
                        return True
                return False
            if j == len(parts):
                return False
            if not _seg_match(pat[i], parts[j]):
                return False
            i += 1
            j += 1

    return walk(0, 0)


def _seg_match(pat: str, seg: str) -> bool:
    import fnmatch
    return fnmatch.fnmatchcase(seg, pat)


def in_exempt_root(rel: str) -> bool:
    return any(rel == root or rel.startswith(root + "/") for root in EXEMPT_ROOTS)


def volatile_prefix_present(root: Path, prefix: str) -> bool:
    """True when this volatile scratch directory still exists in `root`."""
    return (root / prefix).is_dir()


# --------------------------------------------------------------------------- helpers
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def disposition(rel: str) -> dict:
    """Exactly one disposition per path. Returns the rule that owns it."""
    exempt = in_exempt_root(rel)
    for rule in RULES:
        if exempt and not rule["in_exempt"]:
            continue
        if any(glob_match(g, rel) for g in rule["globs"]):
            return rule
    return {"rule": "out_of_scope" if exempt else "unclassified",
            "action": "out_of_scope" if exempt else "unclassified"}


def all_files(root: Path) -> list[str]:
    out: list[str] = []
    base = root / "artifacts"
    if not base.is_dir():
        return out
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            out.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/"))
    out.sort()
    return out


# --------------------------------------------------------------------------- scan
def scan(root: Path) -> dict:
    files: list[dict] = []
    excluded: list[dict] = []
    transient: list[dict] = []
    volatile_checkpoints: list[str] = []
    out_of_scope = {"patterns": list(EXEMPT_ROOTS),
                    "rule": "files under these roots are out of scope, except "
                            "registrations, which stay pinned",
                    "files_ignored": 0, "bytes_ignored": 0,
                    "pinned_inside": 0}
    unclassified: list[str] = []
    by_rule: dict[str, int] = {}
    volatile_paths: list[str] = []

    for rel in all_files(root):
        rule = disposition(rel)
        action = rule["action"]
        by_rule[rule["rule"]] = by_rule.get(rule["rule"], 0) + 1
        path = root / rel
        size = path.stat().st_size

        if action == "volatile":
            volatile_paths.append(rel)
            if rel.endswith(".safetensors"):
                volatile_checkpoints.append(rel)
        elif action == "out_of_scope":
            out_of_scope["files_ignored"] += 1
            out_of_scope["bytes_ignored"] += size
        elif action == "unclassified":
            unclassified.append(rel)
        elif action == "pin":
            files.append({"path": rel, "category": rule["category"], "rule": rule["rule"],
                          "size": size, "sha256": sha256_file(path)})
            if in_exempt_root(rel):
                out_of_scope["pinned_inside"] += 1
        elif action == "exclude":
            entry = {"path": rel, "reason": rule["reason"], "rule": rule["rule"],
                     "size": size, "detail": rule["detail"]}
            if rule["rule"] == "sqlite_transient":
                transient.append({"path": rel, "size": size})
            else:
                excluded.append(entry)

    files.sort(key=lambda e: e["path"])
    excluded.sort(key=lambda e: e["path"])
    transient.sort(key=lambda e: e["path"])
    volatile_checkpoints.sort()

    return {
        "files": files,
        "excluded_with_reason": excluded,
        "transient": transient,
        "volatile_checkpoints": volatile_checkpoints,
        "volatile_dirs": aggregate_volatile(volatile_paths),
        "volatile_paths": volatile_paths,
        "out_of_scope": out_of_scope,
        "unclassified": unclassified,
        "by_rule": by_rule,
    }


def volatile_prefix(rel: str) -> str:
    parts = rel.split("/")
    for i, p in enumerate(parts):
        if p == "tmp" or p.startswith("tmp-"):
            return "/".join(parts[:i + 1])
    return parts[0]


def aggregate_volatile(paths: list[str]) -> list[dict]:
    buckets: dict[str, list[str]] = {}
    for p in paths:
        buckets.setdefault(volatile_prefix(p), []).append(p)
    out: list[dict] = []
    for prefix in sorted(buckets):
        plist = sorted(buckets[prefix])
        out.append({"prefix": prefix, "files": len(plist), "paths_digest": digest(plist)})
    return out


# --------------------------------------------------------------------------- runstore
def open_runstore(path: Path, tmp: Path) -> tuple[sqlite3.Connection, str]:
    """Open a RunStore read-only without writing into the artifact tree."""
    wal = Path(str(path) + "-wal")
    wal_size = wal.stat().st_size if wal.exists() else 0
    if wal_size == 0:
        return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True), \
            "immutable=1 (empty WAL, no -shm/-wal write)"
    clone = tmp / ("rs-" + path.name)
    tmp.mkdir(parents=True, exist_ok=True)
    clone_path = clone
    if clone_path.exists():
        clone_path.unlink()
    shutil.copy2(path, clone_path)
    shutil.copy2(wal, Path(str(clone_path) + "-wal"))
    return sqlite3.connect(f"file:{clone_path}?mode=ro", uri=True), "temporary clone (WAL not empty)"


RUNSTORE_PATHS = tuple(g for rule in RULES if rule["rule"] == "runstore.file"
                       for g in rule["globs"])


def runstore_entries(root: Path, tmp: Path, checkpoint_paths: list[str],
                     volatile_paths: list[str] | None = None) -> dict:
    out: dict = {"databases": {}, "runs_with_checkpoints": {}}
    for rel in RUNSTORE_PATHS:
        path = root / rel
        if not path.is_file():
            continue
        con, how = open_runstore(path, tmp)
        con.row_factory = sqlite3.Row
        tables = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
        wal = Path(str(path) + "-wal")
        db_entry: dict = {"mode": how,
                          "wal_bytes": wal.stat().st_size if wal.exists() else 0,
                          "tables": {}}
        rows_all: list[dict] = []
        for table in sorted(tables):
            cols = [d[1] for d in con.execute(f'PRAGMA table_info("{table}")')]
            rows = [dict(zip(cols, r)) for r in con.execute(f'SELECT * FROM "{table}"')]
            rows.sort(key=lambda row: canonical(row))
            rows_all.append({"table": table, "columns": cols, "rows": rows})
            db_entry["tables"][table] = {"rows": len(rows), "digest": digest(rows)}
        db_entry["entries_digest"] = digest(rows_all)
        out["databases"][rel] = db_entry

        if rel == "artifacts/control.sqlite3":
            run_ids: dict[str, str | None] = {}
            volatile_only: list[str] = []
            runs_table = next((t for t in rows_all if t["table"] == "runs"), {"rows": []})
            for row in runs_table["rows"]:
                run_ids[row["run_id"]] = row.get("state")
            for run_id, state in sorted(run_ids.items()):
                hits = [p for p in checkpoint_paths if run_id in p]
                if hits:
                    out["runs_with_checkpoints"][run_id] = {"state": state, "checkpoints": hits}
                elif any(run_id in p for p in (volatile_paths or [])):
                    volatile_only.append(run_id)
            out["runs_with_checkpoints_only_in_scratch"] = sorted(volatile_only)
        con.close()
    out["entries_digest"] = digest({k: v["entries_digest"] for k, v in out["databases"].items()})
    return out


# --------------------------------------------------------------------------- policy
def policy_document() -> dict:
    """Generated from RULES so the prose cannot drift from the implementation."""
    pinned: list[dict] = []
    excluded: list[dict] = []
    volatile_globs: list[str] = []
    transient_globs: list[str] = []
    for rule in RULES:
        entry = {"rule": rule["rule"], "globs": list(rule["globs"]),
                 "applies_inside_out_of_scope_roots": bool(rule["in_exempt"])}
        if rule["action"] == "pin":
            entry["category"] = rule["category"]
            pinned.append(entry)
        elif rule["action"] == "volatile":
            volatile_globs.extend(rule["globs"])
        elif rule["action"] == "exclude" and rule["rule"] == "sqlite_transient":
            transient_globs.extend(rule["globs"])
        elif rule["action"] == "exclude":
            entry["reason"] = rule["reason"]
            excluded.append(entry)
    return {
        "scan_scope": "every file under artifacts/, except that under artifacts/reports/** "
                      "and artifacts/spacetime/** only registration files are in scope",
        "out_of_scope_roots": list(EXEMPT_ROOTS),
        "pinned": pinned,
        "pinned_claim": "every real-tree match of every glob in policy.pinned is either "
                        "listed in files[] with that glob's category, or is a volatile "
                        "match listed in volatile_checkpoints[]; check_policy() enforces "
                        "this and build/verify fail when it is untrue",
        "excluded": excluded,
        "volatile_rule": {"globs": volatile_globs,
                          "detail": "recorded by path in volatile_checkpoints[]; bytes are "
                                    "not pinned because test runs may rewrite them"},
        "transient": {"globs": transient_globs,
                      "detail": "presence recorded in transient[]; never pinned"},
        "unregistered_file_rule": "any file present in the real tree that is not in "
                                  "files[], excluded_with_reason[] or transient[] and that "
                                  "sits inside a pinned tree (a directory that holds a pinned "
                                  "file, or below it) turns verify RED with "
                                  "unexpected_new_file. Only volatile matches are exempt.",
        "runstore": {
            "primary_identity": "row-level entries_digest (sorted rows, canonical JSON)",
            "file_level": "sha256/size of the .sqlite3 file are recorded but are NOT red "
                          "criteria: when entries_digest is unchanged a sha/size change is "
                          "reported as warning runstore_file_sha_changed / "
                          "runstore_file_size_changed (legitimate VACUUM / WAL checkpoint)",
            "red_criteria": "entries_digest change on any database -> problem "
                            "runstore_entries_changed (tables listed)",
            "wal_shm": "artifacts/**/*-wal and *-shm are transient, never pinned",
        },
        "never_loaded": "checkpoints are hashed as bytes; MLX / ORT / torch are refused",
        "writes_to_artifact_tree": "none: build/verify/inventory write only below --out / "
                                   "--inventory paths, self-test writes only into the "
                                   "temporary case tree",
    }


def check_policy(root: Path, manifest: dict) -> dict:
    """Policy text vs manifest vs real tree. Returns violations and a summary."""
    pinned = {e["path"]: e for e in manifest["files"]}
    excluded = {e["path"] for e in manifest.get("excluded_with_reason", [])}
    transient = {e["path"] for e in manifest.get("transient", [])}
    violations: list[dict] = []
    checked_globs = 0
    matched_files = 0

    real = all_files(root)
    real_set = set(real)

    for rule in RULES:
        if rule["action"] != "pin":
            continue
        for glob in rule["globs"]:
            checked_globs += 1
            for rel in real:
                if not glob_match(glob, rel):
                    continue
                if in_exempt_root(rel) and not rule["in_exempt"]:
                    continue
                matched_files += 1
                hit = pinned.get(rel)
                if hit is None:
                    if disposition(rel)["action"] == "volatile":
                        continue
                    violations.append({"kind": "policy_claim_unmet", "glob": glob,
                                       "path": rel, "category": rule["category"],
                                       "detail": "policy claims this glob is pinned but the "
                                                 "path is not in files[]"})
                elif hit["category"] != rule["category"]:
                    violations.append({"kind": "policy_category_mismatch", "glob": glob,
                                       "path": rel, "expected": rule["category"],
                                       "actual": hit["category"]})

    for path, entry in pinned.items():
        rule = disposition(path)
        if rule["action"] != "pin":
            violations.append({"kind": "policy_entry_not_pinned", "path": path,
                               "disposition": rule["rule"]})
        elif rule["category"] != entry["category"] or rule["rule"] != entry.get("rule"):
            violations.append({"kind": "policy_entry_drift", "path": path,
                               "manifest": [entry.get("rule"), entry["category"]],
                               "policy": [rule["rule"], rule["category"]]})
    for path in excluded:
        if disposition(path)["action"] != "exclude":
            violations.append({"kind": "policy_exclusion_drift", "path": path})
    for path in transient:
        if disposition(path)["rule"] != "sqlite_transient":
            violations.append({"kind": "policy_transient_drift", "path": path})
    for path in manifest.get("volatile_checkpoints", []):
        if path in real_set and disposition(path)["action"] != "volatile":
            violations.append({"kind": "policy_volatile_drift", "path": path})

    missing_excluded = sorted(excluded - real_set)
    return {"checked_globs": checked_globs, "matched_files": matched_files,
            "violations": violations, "missing_excluded": missing_excluded,
            "policy_consistent": not violations}


# --------------------------------------------------------------------------- build
def build(root: Path, out_path: Path, tmp: Path) -> dict:
    scanned = scan(root)
    policy = policy_document()
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    manifest: dict = {
        "schema": SCHEMA,
        "round": "r4",
        "role": "read-only baseline freeze for ADR-0012 / V9 P0 "
                "(r4: post-10-20 deliverables absorption, exhaustive coverage)",
        "generated_at": now,
        "root": ".",
        "policy": policy,
        "counts": {
            "files_pinned": len(scanned["files"]),
            "bytes_pinned": sum(e["size"] for e in scanned["files"]),
            "by_category": {},
            "by_rule": scanned["by_rule"],
            "excluded_files": len(scanned["excluded_with_reason"]),
            "transient_files": len(scanned["transient"]),
            "volatile_checkpoints_observed": len(scanned["volatile_checkpoints"]),
            "out_of_scope_files_ignored": scanned["out_of_scope"]["files_ignored"],
            "unclassified_files": len(scanned["unclassified"]),
        },
        "files": scanned["files"],
        "excluded_with_reason": scanned["excluded_with_reason"],
        "transient": scanned["transient"],
        "volatile_checkpoints": scanned["volatile_checkpoints"],
        "volatile_dirs": scanned["volatile_dirs"],
        "out_of_scope": scanned["out_of_scope"],
        "unclassified": scanned["unclassified"],
        "runstore": runstore_entries(root, tmp,
                                     [e["path"] for e in scanned["files"]
                                      if e["category"] == "checkpoint"],
                                     scanned["volatile_paths"]),
    }
    for entry in scanned["files"]:
        cat = entry["category"]
        bucket = manifest["counts"]["by_category"].setdefault(
            cat, {"files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += entry["size"]
    manifest["manifest_digest"] = digest({k: v for k, v in manifest.items()
                                          if k not in ("generated_at", "manifest_digest")})

    checked = check_policy(root, manifest)
    manifest["policy_check"] = {"checked_globs": checked["checked_globs"],
                                "matched_files": checked["matched_files"],
                                "policy_consistent": checked["policy_consistent"]}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return {**manifest, "policy_violations": checked["violations"],
            "missing_excluded": checked["missing_excluded"]}


# --------------------------------------------------------------------------- verify
def pinned_dir_prefixes(files: list[dict]) -> set[str]:
    out: set[str] = set()
    for entry in files:
        parts = entry["path"].split("/")[:-1]
        for i in range(1, len(parts) + 1):
            out.add("/".join(parts[:i]))
    return out


def verify(root: Path, manifest_path: Path, tmp: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    problems: list[dict] = []
    warnings: list[dict] = []
    checked = 0

    expected = manifest.get("manifest_digest")
    recomputed = digest({k: v for k, v in manifest.items()
                         if k not in ("generated_at", "manifest_digest", "policy_check")})
    if expected != recomputed:
        problems.append({"kind": "manifest_digest", "detail":
                         f"manifest self-digest {expected} != {recomputed}"})

    pinned = {e["path"]: e for e in manifest["files"]}
    runstore_files = {p for p, e in pinned.items() if e["category"] == "runstore.file"}
    prefixes = pinned_dir_prefixes(manifest["files"])
    excluded = {e["path"] for e in manifest.get("excluded_with_reason", [])}
    transient = {e["path"] for e in manifest.get("transient", [])}
    recorded_volatile_checkpoints = set(manifest.get("volatile_checkpoints", []))

    for rel, entry in sorted(pinned.items()):
        path = root / rel
        if not path.is_file():
            problems.append({"kind": "missing", "path": rel})
            continue
        size = path.stat().st_size
        if rel in runstore_files:
            if size != entry["size"]:
                warnings.append({"kind": "runstore_file_size_changed", "path": rel,
                                 "expected": entry["size"], "actual": size,
                                 "note": "size change alone is not RED; see "
                                         "runstore_entries_changed for semantic check"})
            if sha256_file(path) != entry["sha256"]:
                warnings.append({"kind": "runstore_file_sha_changed", "path": rel,
                                 "expected": entry["sha256"],
                                 "note": "file sha change alone is not RED; see "
                                         "runstore_entries_changed"})
            checked += 1
            continue
        if size != entry["size"]:
            problems.append({"kind": "size_changed", "path": rel,
                             "expected": entry["size"], "actual": size})
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            problems.append({"kind": "sha256_changed", "path": rel,
                             "expected": entry["sha256"], "actual": actual})
        else:
            checked += 1

    real = all_files(root)
    real_set = set(real)
    seen_volatile: list[str] = []
    unclassified_outside: list[str] = []
    for rel in real:
        if rel in pinned or rel in excluded or rel in transient:
            continue
        rule = disposition(rel)
        if rule["action"] == "volatile":
            seen_volatile.append(rel)
            continue
        if rule["action"] == "out_of_scope":
            continue
        inside = any("/".join(rel.split("/")[:i]) in prefixes
                     for i in range(1, len(rel.split("/"))))
        if rule["action"] == "pin" or inside:
            problems.append({"kind": "unexpected_new_file", "path": rel,
                             "disposition": rule["rule"],
                             "inside_pinned_tree": inside,
                             "detail": "not in files[], excluded_with_reason[] or "
                                       "transient[]"})
        else:
            unclassified_outside.append(rel)

    for rel in unclassified_outside[:200]:
        warnings.append({"kind": "unclassified_file", "path": rel,
                          "note": "new file outside every pinned tree and matched by no "
                                  "exclusion rule; recorded, not RED (documented boundary)"})
    if len(unclassified_outside) > 200:
        warnings.append({"kind": "unclassified_file_truncated",
                         "remaining": len(unclassified_outside) - 200})

    want_dirs = {d["prefix"]: d for d in manifest.get("volatile_dirs", [])}
    got_dirs = {d["prefix"]: d for d in aggregate_volatile(seen_volatile)}
    for prefix in sorted(set(want_dirs) | set(got_dirs)):
        want, got = want_dirs.get(prefix), got_dirs.get(prefix)
        if want is None:
            warnings.append({"kind": "volatile_prefix_added", "path": prefix,
                             "files": got["files"],
                             "note": "new volatile scratch tree; never pinned by design"})
        elif got is None:
            if not volatile_prefix_present(root, prefix):
                continue
            warnings.append({"kind": "volatile_prefix_removed", "path": prefix,
                             "files": want["files"]})
        elif got["files"] != want["files"] or got["paths_digest"] != want["paths_digest"]:
            warnings.append({"kind": "volatile_scope_changed", "path": prefix,
                             "files_recorded": want["files"], "files_observed": got["files"],
                             "note": "volatile test scratch is recorded by name only; "
                                     "growth or shrink never turns verify red"})
    vanished_volatile = [rel for rel in sorted(recorded_volatile_checkpoints - real_set)
                         if volatile_prefix_present(root, volatile_prefix(rel))]
    for rel in vanished_volatile[:50]:
        warnings.append({"kind": "volatile_checkpoint_removed", "path": rel})

    for rel in sorted(excluded - real_set):
        warnings.append({"kind": "excluded_file_missing", "path": rel,
                         "note": "the excluded file recorded in the manifest no longer exists"})
    for rel in sorted(transient - real_set):
        warnings.append({"kind": "transient_file_missing", "path": rel})

    policy = check_policy(root, manifest)
    problems.extend(policy["violations"])

    store = runstore_entries(root, tmp,
                             [e["path"] for e in manifest["files"]
                              if e["category"] == "checkpoint"],
                             manifest.get("volatile_checkpoints", []))
    for run_id in store.get("runs_with_checkpoints_only_in_scratch", []):
        warnings.append({"kind": "run_checkpoint_only_in_scratch", "path": run_id})
    want_store = manifest.get("runstore", {})
    if store["entries_digest"] != want_store.get("entries_digest"):
        for rel, entry in sorted(store["databases"].items()):
            want = want_store.get("databases", {}).get(rel, {})
            if entry["entries_digest"] != want.get("entries_digest"):
                bad_tables = [t for t, v in entry["tables"].items()
                              if v["digest"] != want.get("tables", {}).get(t, {}).get("digest")]
                problems.append({"kind": "runstore_entries_changed", "path": rel,
                                 "tables": bad_tables})
    for run_id in manifest.get("runstore", {}).get("runs_with_checkpoints", {}):
        if not [e for e in manifest["files"]
                if e["category"] == "checkpoint" and run_id in e["path"]]:
            problems.append({"kind": "run_checkpoint_not_pinned", "path": run_id})

    return {"schema": manifest["schema"], "round": manifest.get("round"),
            "root": str(root), "manifest": str(manifest_path),
            "files_pinned": len(pinned), "files_ok": checked,
            "runstore_files": len(runstore_files),
            "policy_checked_globs": policy["checked_globs"],
            "policy_consistent": policy["policy_consistent"],
            "problems": problems, "warnings": warnings,
            "runs_with_checkpoints": len(manifest.get("runstore", {})
                                          .get("runs_with_checkpoints", {})),
            "verdict": "ok" if not problems else "RED"}


# --------------------------------------------------------------------------- inventory
UUID_RE = _re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def inventory(root: Path, manifest_path: Path, out_path: Path, tmp: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    runs = {}
    experiments = {}
    for p in RUNSTORE_PATHS:
        full_p = root / p
        if not full_p.is_file():
            continue
        try:
            con, _ = open_runstore(full_p, tmp)
            con.row_factory = sqlite3.Row
            tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
            if "runs" in tables:
                for r in con.execute("select * from runs"):
                    runs[r["run_id"]] = dict(r)
            if "experiments" in tables:
                for r in con.execute("select * from experiments"):
                    experiments[r["experiment_id"]] = dict(r)
            con.close()
        except Exception:
            pass

    counts = manifest["counts"]
    lines = ["# AinerZero V9 baseline inventory r4 (read-only freeze)", "",
             f"- manifest: `{manifest_path}` · digest `{manifest['manifest_digest']}`",
             f"- pinned: {counts['files_pinned']} files / "
             f"{counts['bytes_pinned'] / 1e6:.1f} MB · generated {manifest['generated_at']}",
             f"- excluded with an individual reason: {counts['excluded_files']} files; "
             f"transient (sqlite -wal/-shm): {counts['transient_files']}",
             f"- volatile test scratch recorded by name: "
             f"{counts['volatile_checkpoints_observed']} checkpoints",
             f"- out-of-scope files ignored: {counts['out_of_scope_files_ignored']} "
             f"(artifacts/reports/**, artifacts/spacetime/**)",
             f"- unclassified in-scope files: {counts['unclassified_files']}", "",
             "## Checkpoints (fallback baselines)", "",
             "| # | path | run_id | run state | experiment | bytes | sha256 |",
             "|---|---|---|---|---|---|---|"]
    by_run: dict[str, list[dict]] = {}
    for entry in manifest["files"]:
        if entry["category"] != "checkpoint":
            continue
        run_id = next((rid for rid in runs if rid in entry["path"]), None)
        if run_id is None:
            found = UUID_RE.search(entry["path"])
            run_id = found.group(0) if found else "(not in RunStore)"
        by_run.setdefault(run_id, []).append(entry)
    index = 0
    for run_id, items in sorted(by_run.items()):
        info = runs.get(run_id, {})
        for entry in items:
            index += 1
            lines.append(f"| {index} | `{entry['path']}` | `{run_id}` | "
                         f"{info.get('state', 'not in RunStore')} | "
                         f"{info.get('experiment_id') or ''} | {entry['size']} | "
                         f"`{entry['sha256'][:16]}` |")
    lines += ["", "## Pinned by category", ""]
    for cat, bucket in sorted(counts["by_category"].items()):
        lines.append(f"- `{cat}`: {bucket['files']} files / {bucket['bytes']} B")
    lines += ["", "## Pinned by rule (counts include out-of-scope registrations)", ""]
    for rule, count in sorted(counts["by_rule"].items()):
        lines.append(f"- `{rule}`: {count}")
    lines += ["", "## Excluded with an individual reason", ""]
    for exc in manifest["excluded_with_reason"][:200]:
        lines.append(f"- `{exc['path']}` · {exc['reason']} ({exc['rule']}) · {exc['detail']}")
    if len(manifest["excluded_with_reason"]) > 200:
        lines.append(f"- … {len(manifest['excluded_with_reason']) - 200} more")
    lines += ["", "## Transient (never pinned)", ""]
    for tr in manifest["transient"]:
        lines.append(f"- `{tr['path']}` · {tr['size']} B")
    lines += ["", "## Out of scope", "",
              f"- roots: {', '.join(manifest['out_of_scope']['patterns'])}",
              f"- ignored files: {manifest['out_of_scope']['files_ignored']} · "
              f"registrations pinned inside: {manifest['out_of_scope']['pinned_inside']}",
              f"- rule: {manifest['out_of_scope']['rule']}"]
    if manifest.get("volatile_checkpoints"):
        lines += ["", "## Volatile scratch checkpoints (recorded, not pinned)", ""]
        for path in manifest["volatile_checkpoints"][:20]:
            lines.append(f"- `{path}`")
        if len(manifest["volatile_checkpoints"]) > 20:
            lines.append(f"- … {len(manifest['volatile_checkpoints']) - 20} more")
    lines += ["", "## RunStore", ""]
    for db, entry in sorted(manifest["runstore"]["databases"].items()):
        tables = ", ".join(f"{t}={v['rows']}" for t, v in sorted(entry["tables"].items()))
        lines.append(f"- `{db}` · {entry['mode']} · entries_digest "
                     f"`{entry['entries_digest'][:16]}` · {tables}")
    lines += ["", f"- runs whose only checkpoint is volatile scratch: "
                  f"{manifest['runstore'].get('runs_with_checkpoints_only_in_scratch', []) or 'none'}",
              f"- experiments with a manifest_hash: "
              f"{sum(1 for e in experiments.values() if e.get('manifest_hash'))}/{len(experiments)}",
              f"- runs whose checkpoint is pinned: "
              f"{len(manifest['runstore']['runs_with_checkpoints'])}/{len(runs)} RunStore runs", "",
              "## How to re-verify", "", "```bash",
              "python3 scripts/v9_baseline_manifest_r4.py verify    # exit 0 = every pinned byte unchanged",
              "python3 scripts/v9_baseline_manifest_r4.py selftest  # exit 0 = every injected fault turned it red",
              "```", ""]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    return {"out": str(out_path), "checkpoints": sum(len(v) for v in by_run.values()),
            "runs": len(by_run), "registrations": counts["by_category"]
            .get("registration", {}).get("files", 0)}


# --------------------------------------------------------------------------- selftest
def _init_clonefile():
    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        cf = libc.clonefile
        cf.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.restype = ctypes.c_int
        return cf
    except Exception:
        return None

_CLONEFILE = _init_clonefile()


def clone_file(src: Path, dst: Path) -> None:
    """A real, independent copy: APFS clone when available, else a byte copy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if _CLONEFILE is not None:
        try:
            res = _CLONEFILE(str(src).encode("utf-8"), str(dst).encode("utf-8"), 0)
            if res == 0:
                try:
                    os.chmod(dst, 0o644)
                except OSError:
                    pass
                return
        except Exception:
            pass
    if subprocess.run(["cp", "-c", str(src), str(dst)], capture_output=True).returncode != 0:
        shutil.copy2(src, dst)
    try:
        os.chmod(dst, 0o644)
    except OSError:
        pass


def make_case_tree(root: Path, manifest: dict, dest: Path) -> dict:
    """Materialise a throw-away case root as REAL copies (never symlinks)."""
    copied = 0
    for entry in manifest["files"]:
        clone_file(root / entry["path"], dest / entry["path"])
        copied += 1
    for entry in manifest["excluded_with_reason"]:
        clone_file(root / entry["path"], dest / entry["path"])
        copied += 1
    for entry in manifest["transient"]:
        src = root / entry["path"]
        if src.is_file():
            clone_file(src, dest / entry["path"])
            copied += 1
    symlinks = 0
    same_inode = 0
    for base in (dest / "artifacts/pilot", dest / "artifacts/m0", dest / "artifacts/v9"):
        if not base.exists():
            continue
        for dirpath, _d, names in os.walk(base):
            for name in names:
                p = Path(dirpath) / name
                if p.is_symlink():
                    symlinks += 1
                elif p.stat().st_ino == (root / p.relative_to(dest)).stat().st_ino:
                    same_inode += 1
    return {"files_copied": copied, "symlinks": symlinks,
            "same_inode_as_real_tree": same_inode,
            "real_copies": symlinks == 0 and same_inode == 0}


def real_tree_integrity(root: Path, manifest_path: Path, label: str) -> dict:
    """Re-hash the pinned set of the REAL tree (no writes anywhere)."""
    manifest = json.loads(manifest_path.read_text())
    mismatches: list[dict] = []
    checked = 0
    r2_subset_checked = 0
    for entry in manifest["files"]:
        path = root / entry["path"]
        if not path.is_file():
            mismatches.append({"path": entry["path"], "kind": "missing"})
            continue
        size = path.stat().st_size
        actual = sha256_file(path)
        checked += 1
        if entry["category"] != "runstore.file":
            r2_subset_checked += 1
        if size != entry["size"] or actual != entry["sha256"]:
            mismatches.append({"path": entry["path"], "kind": "changed",
                               "expected_size": entry["size"], "actual_size": size,
                               "expected_sha": entry["sha256"], "actual_sha": actual})
    return {"label": label, "checked": checked,
            "checked_non_runstore": r2_subset_checked,
            "mismatches": mismatches,
            "content_unchanged": not mismatches}


def _first(manifest: dict, **kw) -> dict:
    for entry in manifest["files"]:
        if all(entry.get(k) == v for k, v in kw.items()):
            return entry
    raise SystemExit(f"selftest: no manifest entry for {kw}")


def selftest(root: Path, manifest_path: Path, work: Path, out_path: Path | None) -> int:
    manifest = json.loads(manifest_path.read_text())
    results: list[dict] = []
    integrity_before = real_tree_integrity(root, manifest_path, "before")

    cat = {c: _first(manifest, category=c) for c in
           ("checkpoint", "checkpoint.meta", "m0.run", "run.config", "run.updates",
            "probe.meta", "dataset.c0", "dataset.gridlab2d", "registration")}

    def run_case(name: str, tamper, expect_red: bool = True, note: str = "") -> dict:
        case_root = work / name
        if case_root.exists():
            shutil.rmtree(case_root)
        copy_info = make_case_tree(root, manifest, case_root)
        case_manifest = case_root / "manifest.json"
        shutil.copy2(manifest_path, case_manifest)
        detail = tamper(case_root, case_manifest) if tamper else "no fault injected"
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                               "verify", "--root", str(case_root),
                               "--manifest", str(case_manifest), "--json"],
                              capture_output=True, text=True)
        body = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
        kinds = [p["kind"] for p in body.get("problems", [])]
        warn_kinds = [w["kind"] for w in body.get("warnings", [])]
        entry = {"case": name, "exit": proc.returncode, "fault": detail,
                 "expect_red": expect_red, "problems": kinds[:6],
                 "warnings": warn_kinds[:6],
                 "real_copy": copy_info["real_copies"], "note": note,
                 "stderr": proc.stderr.strip()[-200:]}
        if expect_red:
            entry["passed"] = proc.returncode != 0
        else:
            entry["passed"] = proc.returncode == 0
        results.append(entry)
        shutil.rmtree(case_root, ignore_errors=True)
        return entry

    # ---- controls
    run_case("clean_real_copy", None, expect_red=False,
             note="real-copy tree, no fault: must stay green (not an always-red harness)")

    # ---- content tampering, one per pinned category
    def tamper_byte_flip(case_root, _):
        target = case_root / cat["checkpoint"]["path"]
        data = bytearray(target.read_bytes())
        data[len(data) // 2] ^= 0x01
        target.write_bytes(bytes(data))
        return f"flipped one byte of {Path(cat['checkpoint']['path']).name} (size unchanged)"

    run_case("checkpoint_byte_flip", tamper_byte_flip)

    def tamper_swap(case_root, _):
        cps = [e for e in manifest["files"] if e["category"] == "checkpoint"]
        donor = cps[0]
        victim = next((e for e in reversed(cps)
                       if (root / e["path"]).stat().st_size != (root / donor["path"]).stat().st_size
                       or (root / e["path"]).read_bytes()[:4096]
                       != (root / donor["path"]).read_bytes()[:4096]), None)
        if victim is None:
            return "no distinct checkpoint pair available"
        target = case_root / victim["path"]
        target.write_bytes((case_root / donor["path"]).read_bytes())
        return (f"copied {Path(donor['path']).name} ({donor['size']} B) over "
                f"{Path(victim['path']).name} ({victim['size']} B)")

    run_case("checkpoint_swapped", tamper_swap)

    def make_truncator(key: str):
        def _t(case_root, _):
            rel = cat[key]["path"]
            target = case_root / rel
            target.write_bytes(b"{}")
            return f"truncated {rel} to b'{{}}'"
        return _t

    for key in ("checkpoint.meta", "m0.run", "run.config", "run.updates", "probe.meta",
                "dataset.c0", "dataset.gridlab2d", "registration"):
        run_case(f"tamper_{key.replace('.', '_')}", make_truncator(key))

    def tamper_missing(case_root, _):
        rel = cat["dataset.gridlab2d"]["path"]
        (case_root / rel).unlink()
        return f"deleted a dataset file: {rel}"

    run_case("dataset_file_deleted", tamper_missing)

    # ---- T3: unregistered files inside pinned trees must turn red
    def make_new_file(key: str, filename: str):
        def _t(case_root, _):
            parent = Path(cat[key]["path"]).parent
            target = case_root / parent / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("not part of the frozen baseline\n")
            return f"added {parent / filename}"
        return _t

    run_case("t3_notes_in_checkpoint_dir", make_new_file("checkpoint", "NOTES.md"),
             note="A4 T3: unregistered file in a pinned checkpoint directory")
    run_case("t3_notes_in_m0_run_root", make_new_file("m0.run", "NOTES.md"),
             note="unregistered file in an M0 run root")
    run_case("t3_notes_in_dataset_dir", make_new_file("dataset.c0", "NOTES.md"),
             note="unregistered file in a pinned dataset directory")
    run_case("t3_smuggled_safetensors", make_new_file("checkpoint", "smuggled-extra.safetensors"),
             note="new pinned-category file smuggled next to a baseline checkpoint")

    # ---- r4 mandatory additions:
    # 1. Injected NOTES.md in an E1 phase2 checkpoint directory
    def tamper_e1_notes(case_root, _):
        target = case_root / "artifacts/v9/e1/phase2/checkpoints/arm2_P_seed42/NOTES.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("not part of baseline\n")
        return "injected NOTES.md in E1 phase2 checkpoint directory"

    run_case("t3_e1_notes_in_checkpoint_dir", tamper_e1_notes,
             note="r4 addition: unregistered file injected into an E1 phase2 checkpoint directory")

    # 2. Flipped one byte in an E1 phase2 sealed_final file
    def tamper_sealed_final(case_root, _):
        target = case_root / "artifacts/v9/e1/phase2/datasets/sealed_final/P/3565d8e307cac2de0b5fbc4ade2be0910a1411357b23024f0fae47292b7181de/SEALED.json"
        data = bytearray(target.read_bytes())
        data[len(data) // 2] ^= 0x01
        target.write_bytes(bytes(data))
        return "flipped one byte in E1 phase2 sealed_final/P/.../SEALED.json"

    run_case("sealed_final_byte_flip", tamper_sealed_final,
             note="r4 addition: flipped one byte in sealed_final file")

    # ---- r4 r2 additions (pre-check remediation):
    # 3. Flipped one byte in an E1 evaluator development JSON
    def tamper_e1_evaluator(case_root, _):
        pattern = "artifacts/v9/e1/phase2/datasets/evaluator/P/development/*.json"
        matches = sorted(case_root.glob(pattern))
        assert matches, f"no matches for {pattern}"
        target = matches[0]
        data = bytearray(target.read_bytes())
        data[len(data) // 2] ^= 0x01
        target.write_bytes(bytes(data))
        return f"flipped one byte in E1 evaluator JSON {target.name}"

    run_case("r2_e1_evaluator_byte_flip", tamper_e1_evaluator,
             note="r2 addition: flipped one byte in an E1 evaluator development JSON")

    # 4. Deleted one file in E1 student train dataset
    def tamper_e1_student_delete(case_root, _):
        pattern = "artifacts/v9/e1/phase2/datasets/student/S/train/*.json"
        matches = sorted(case_root.glob(pattern))
        assert matches, f"no matches for {pattern}"
        target = matches[0]
        target.unlink()
        return f"deleted E1 student train file {target.name}"

    run_case("r2_e1_student_file_deleted", tamper_e1_student_delete,
             note="r2 addition: deleted one file in E1 student train dataset")

    # ---- documented boundaries that must NOT turn red
    def add_volatile(case_root, _):
        target = case_root / "artifacts/pilot/tmp-selftest-scratch/x.safetensors"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"scratch")
        return "added a *.safetensors under a tmp-* component (volatile rule)"

    run_case("volatile_scratch_allowed", add_volatile, expect_red=False,
             note="volatile rule exception, documented in policy")

    def add_out_of_scope(case_root, _):
        target = case_root / "artifacts/reports/some-new-report/report.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("out of scope\n")
        return "added a non-registration file under artifacts/reports/ (out of scope)"

    run_case("out_of_scope_report_allowed", add_out_of_scope, expect_red=False,
             note="artifacts/reports/** is declared out of scope")

    # ---- RunStore: VACUUM green / forged row red
    def vacuum_db(case_root, _):
        db = case_root / "artifacts/control.sqlite3"
        before = db.stat().st_size
        con = sqlite3.connect(str(db))
        con.execute("VACUUM")
        con.commit()
        con.close()
        for suffix in ("-wal", "-shm"):
            side = Path(str(db) + suffix)
            if side.exists():
                side.unlink()
        return (f"legitimate VACUUM on a real copy: {before} -> {db.stat().st_size} bytes")

    run_case("runstore_vacuum_allowed", vacuum_db, expect_red=False,
             note="policy: row digest unchanged -> file sha/size change is only a warning")

    def forge_row(case_root, _):
        db = case_root / "artifacts/control.sqlite3"
        con = sqlite3.connect(str(db))
        con.execute("UPDATE runs SET state='completed_forged' "
                    "WHERE run_id=(SELECT run_id FROM runs ORDER BY run_id LIMIT 1)")
        changed = con.total_changes
        con.commit()
        con.close()
        return f"UPDATE runs SET state='completed_forged' on one row ({changed} row)"

    run_case("runstore_row_forged", forge_row)

    def tamper_manifest(case_root, case_manifest):
        doc = json.loads(case_manifest.read_text())
        doc["files"][0]["sha256"] = "0" * 64
        case_manifest.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        return "edited the stored sha of files[0] in the manifest copy"

    run_case("manifest_self_edited", tamper_manifest)

    # ---- documented blind spot (honest disclosure, must stay green)
    def tamper_excluded(case_root, _):
        rel = manifest["excluded_with_reason"][0]["path"]
        target = case_root / rel
        target.write_bytes(target.read_bytes() + b"tampered")
        return f"appended bytes to excluded file {rel} (documented blind spot)"

    run_case("excluded_file_tamper_stays_green", tamper_excluded, expect_red=False,
             note="known limitation: files excluded with a reason are not hashed; a change "
                  "there is not detected by this manifest")

    integrity_after = real_tree_integrity(root, manifest_path, "after")

    faults = [r for r in results if r["expect_red"]]
    blind = [r["case"] for r in faults if not r["passed"]]
    controls = [r for r in results if not r["expect_red"]]
    red_controls = [r["case"] for r in controls if not r["passed"]]

    payload = {
        "selftest": results,
        "summary": {
            "cases_total": len(results),
            "faults_injected": len(faults),
            "faults_detected": len(faults) - len(blind),
            "faults_missed": blind,
            "controls_green": len(controls) - len(red_controls),
            "controls_unexpectedly_red": red_controls,
            "all_detected": not blind and not red_controls,
        },
        "real_tree_integrity": {"before": integrity_before, "after": integrity_after},
        "copy_mode": "APFS clone (clonefile / cp -c) / shutil.copy2 fallback, never a symlink",
    }
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(payload["summary"] | {
        "real_tree_before": integrity_before["content_unchanged"],
        "real_tree_after": integrity_after["content_unchanged"]},
        ensure_ascii=False, indent=1))
    if blind:
        print(f"selftest: {len(blind)} injected fault(s) NOT detected: {blind}", file=sys.stderr)
        return 1
    if red_controls:
        print(f"selftest: {len(red_controls)} control(s) unexpectedly RED: {red_controls}",
              file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify", "selftest", "inventory",
                                            "policy-check", "integrity"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--inventory", type=Path, default=None)
    parser.add_argument("--selftest-out", type=Path, default=None)
    parser.add_argument("--integrity-out", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if "mlx" in sys.modules or "torch" in sys.modules or "onnxruntime" in sys.modules:
        print("refusing to run: a model runtime is already imported", file=sys.stderr)
        return 2

    out = args.out or (root / DEFAULT_MANIFEST)
    manifest_path = args.manifest or out
    inv = args.inventory or (root / DEFAULT_INVENTORY)
    st_out = args.selftest_out or (root / DEFAULT_SELFTEST)
    integ_out = args.integrity_out or (root / DEFAULT_INTEGRITY)

    with tempfile.TemporaryDirectory(prefix="v9-baseline-r4-") as tmpdir:
        tmp = Path(tmpdir)
        if args.command == "build":
            manifest = build(root, out, tmp)
            summary = {"command": "build", "root": str(root), "out": str(out),
                       "files_pinned": manifest["counts"]["files_pinned"],
                       "bytes_pinned": manifest["counts"]["bytes_pinned"],
                       "by_category": manifest["counts"]["by_category"],
                       "excluded_files": manifest["counts"]["excluded_files"],
                       "transient_files": manifest["counts"]["transient_files"],
                       "volatile_checkpoints_observed":
                           manifest["counts"]["volatile_checkpoints_observed"],
                       "out_of_scope_files_ignored":
                           manifest["counts"]["out_of_scope_files_ignored"],
                       "unclassified_files": manifest["counts"]["unclassified_files"],
                       "policy_violations": len(manifest["policy_violations"]),
                       "manifest_digest": manifest["manifest_digest"]}
            print(json.dumps(summary, indent=1, ensure_ascii=False) if args.json
                  else f"build: {summary['files_pinned']} files / {summary['bytes_pinned']} bytes "
                       f"-> {out}\n"
                       f"       manifest_digest {summary['manifest_digest'][:16]} · "
                       f"excluded {summary['excluded_files']} · transient "
                       f"{summary['transient_files']} · volatile "
                       f"{summary['volatile_checkpoints_observed']} · out-of-scope "
                       f"{summary['out_of_scope_files_ignored']} · unclassified "
                       f"{summary['unclassified_files']} · policy violations "
                       f"{summary['policy_violations']}")
            if manifest["policy_violations"]:
                print(json.dumps(manifest["policy_violations"][:20], indent=1,
                                 ensure_ascii=False), file=sys.stderr)
                return 1
            return 0

        if args.command == "verify":
            result = verify(root, manifest_path, tmp)
            if args.json:
                print(json.dumps(result, indent=1, ensure_ascii=False))
            else:
                print(f"verify: {result['files_ok']}/{result['files_pinned']} pinned entries "
                      f"checked, policy globs {result['policy_checked_globs']}, "
                      f"verdict {result['verdict']}")
                for problem in result["problems"][:25]:
                    print(f"  - {problem['kind']}: "
                          f"{problem.get('path', problem.get('glob', problem.get('detail', '')))}")
                for warning in result["warnings"][:10]:
                    print(f"  WARNING: {warning['kind']}: {warning.get('path', '')}")
            return 0 if result["verdict"] == "ok" else 1

        if args.command == "inventory":
            result = inventory(root, manifest_path, inv, tmp)
            print(json.dumps(result, indent=1, ensure_ascii=False) if args.json
                  else f"inventory: {result['checkpoints']} checkpoints over {result['runs']} runs, "
                       f"{result['registrations']} registrations -> {result['out']}")
            return 0

        if args.command == "policy-check":
            manifest = json.loads(manifest_path.read_text())
            result = check_policy(root, manifest)
            print(json.dumps(result, indent=1, ensure_ascii=False))
            return 0 if result["policy_consistent"] else 1

        if args.command == "integrity":
            result = real_tree_integrity(root, manifest_path, "standalone")
            integ_out.parent.mkdir(parents=True, exist_ok=True)
            integ_out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
            print(json.dumps(result, indent=1, ensure_ascii=False) if args.json
                  else f"integrity: {result['checked']} pinned files re-hashed, "
                       f"{len(result['mismatches'])} mismatches -> {integ_out}")
            return 0 if result["content_unchanged"] else 1

        return selftest(root, manifest_path, tmp, st_out)


if __name__ == "__main__":
    sys.exit(main())
