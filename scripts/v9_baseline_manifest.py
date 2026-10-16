#!/usr/bin/env python3
"""ainerzero.V9.A2 -- baseline freeze manifest: read-only hash inventory + re-verification.

Purpose (ADR-0012 / V9_LANDING_PLAN section 3, P0 gate "基线哈希可复验"):

    Pin the identity of the existing fallback baselines -- experiment checkpoints
    (m0 / C0 / pilot / D candidate / GridLab runs), the C0 and GridLab2D episode
    datasets, the registration documents and the central RunStore entries -- so that
    any later V9 structure can be accepted against a baseline that provably has not
    moved.

Hard rules honoured by this tool:

* **pure CPU, no MLX / no ORT / no model loading**. Only ``hashlib``, ``json``,
  ``sqlite3``, ``pathlib``; checkpoints are hashed as bytes, never deserialised.
* **read-only**. Nothing under the artifact tree is created, moved, rewritten or
  deleted. The RunStore is opened with ``immutable=1`` when its WAL is empty, so
  SQLite does not even touch the ``-shm``/``-wal`` side files; if the WAL is not
  empty the database is cloned to a temporary directory and read there instead.
* **deterministic**. File entries are sorted by path; the manifest carries a
  ``manifest_digest`` over everything except ``generated_at`` and itself, so two
  builds over an unchanged tree agree bit for bit.

Usage
-----
    python3 scripts/v9_baseline_manifest.py build  [--root .] [--out reports/V9-baseline/baseline_manifest.json]
    python3 scripts/v9_baseline_manifest.py verify [--root .] [--manifest ...] [--json]
    python3 scripts/v9_baseline_manifest.py selftest [--root .]
    python3 scripts/v9_baseline_manifest.py inventory [--root .] [--inventory OUT.md]

``verify`` exits 0 when every pinned artifact still matches, and **non-zero** when any
file is changed, missing, or when a new file appears in a pinned scope. ``selftest``
injects each of those faults into a throw-away symlinked copy of the tree (the real
tree is never written) and fails unless every injected fault turns the verifier red.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

SCHEMA = "ainerzero.v9.baseline_manifest.v1"
DEFAULT_MANIFEST = Path("reports/V9-baseline/baseline_manifest.json")

#: directories pinned wholesale (episode datasets of the C0 and GridLab2D baselines)
DATASET_DIRS = ("artifacts/c0", "artifacts/gridlab2d")

#: RunStore databases; `-wal`/`-shm` are deliberately NOT pinned (transient side files)
RUNSTORE_FILES = ("artifacts/control.sqlite3", "artifacts/control.sqlite3.bak-20261011",
                  "artifacts/m0/control.sqlite3", "artifacts/run_store.db")

CHECKPOINT_SUFFIXES = (".safetensors",)
REGISTRATION_SUFFIXES = (".json", ".md")

CHUNK = 1 << 20


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


def is_volatile(rel: Path) -> bool:
    """Test scratch: any path component named ``tmp`` or ``tmp-*``.

    Those trees hold pytest fixtures that a later test run may legitimately rewrite
    (216 of the 353 ``*.safetensors`` files live there), so they are recorded as
    observed-but-excluded instead of being pinned.
    """
    return any(part == "tmp" or part.startswith("tmp-") for part in rel.parts)


def is_registration(rel: Path) -> bool:
    name = rel.name.lower()
    return (("registration" in name or name == "preregistration.json")
            and rel.suffix in REGISTRATION_SUFFIXES)


def rel_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


# --------------------------------------------------------------------------- scanning
def scan(root: Path) -> dict:
    """Enumerate the pinned artifact set and the volatile set that is deliberately skipped."""
    files: list[dict] = []
    volatile_checkpoints: list[str] = []

    for path in sorted((root / "artifacts").rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if is_volatile(rel):
            if rel.suffix in CHECKPOINT_SUFFIXES:
                volatile_checkpoints.append(rel.as_posix())
            continue
        if rel.suffix in CHECKPOINT_SUFFIXES:
            files.append({"path": rel.as_posix(), "category": "checkpoint"})
        elif is_registration(rel):
            files.append({"path": rel.as_posix(), "category": "registration"})

    for directory in DATASET_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        category = "dataset.c0" if directory.endswith("c0") else "dataset.gridlab2d"
        for path in sorted(base.rglob("*")):
            if path.is_file():
                files.append({"path": rel_posix(path, root), "category": category})

    for rel in RUNSTORE_FILES:
        path = root / rel
        if path.is_file():
            files.append({"path": rel, "category": "runstore.file"})

    files.sort(key=lambda e: e["path"])
    for entry in files:
        path = root / entry["path"]
        entry["size"] = path.stat().st_size
        entry["sha256"] = sha256_file(path)
    return {"files": files, "volatile_checkpoints": sorted(volatile_checkpoints)}


# --------------------------------------------------------------------------- runstore
def open_runstore(path: Path, tmp: Path) -> tuple[sqlite3.Connection, str]:
    """Open a RunStore read-only without writing to the artifact tree."""
    wal = Path(str(path) + "-wal")
    wal_size = wal.stat().st_size if wal.exists() else 0
    if wal_size == 0:
        con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        return con, "immutable=1 (empty WAL, no -shm/-wal write)"
    clone = tmp / path.name
    shutil.copy2(path, clone)
    shutil.copy2(wal, Path(str(clone) + "-wal"))
    con = sqlite3.connect(f"file:{clone}?mode=ro", uri=True)
    return con, "temporary clone (WAL was not empty)"


def runstore_entries(root: Path, tmp: Path, checkpoint_paths: list[str],
                     volatile_paths: list[str] | None = None) -> dict:
    """Row-level digests in RunStore order -- stable across VACUUM / WAL checkpoints."""
    out: dict = {"databases": {}, "runs_with_checkpoints": {}}
    for rel in RUNSTORE_FILES:
        path = root / rel
        if not path.is_file():
            continue
        con, how = open_runstore(path, tmp)
        con.row_factory = sqlite3.Row
        tables = [r[0] for r in con.execute("select name from sqlite_master where type='table' "
                                            "and name not like 'sqlite_%'")]
        db_entry: dict = {"mode": how, "wal_bytes": (Path(str(path) + "-wal").stat().st_size
                                                     if Path(str(path) + "-wal").exists() else 0),
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
            run_ids = {}
            volatile_only: list[str] = []
            for row in next((t for t in rows_all if t["table"] == "runs"), {"rows": []})["rows"]:
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


# --------------------------------------------------------------------------- build
def build(root: Path, out_path: Path, tmp: Path) -> dict:
    scanned = scan(root)
    manifest = {
        "schema": SCHEMA,
        "role": "read-only baseline freeze for ADR-0012 / V9 P0",
        "generated_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S%z"),
        "root": ".",
        "policy": {
            "pinned": ["artifacts/**/*.safetensors (excluding volatile test scratch)",
                       "artifacts/**/*registration*.{json,md} and preregistration.json",
                       "artifacts/c0/**", "artifacts/gridlab2d/**",
                       "artifacts/control.sqlite3 (+ .bak), artifacts/m0/control.sqlite3, "
                       "artifacts/run_store.db"],
            "excluded_volatile_rule": "any path component named 'tmp' or starting with 'tmp-'",
            "excluded_transient": ["artifacts/**/*-wal", "artifacts/**/*-shm"],
            "never_loaded": "checkpoints are hashed as bytes; no MLX / ORT / tensor library import",
        },
        "counts": {
            "files_total": len(scanned["files"]),
            "bytes_total": sum(e["size"] for e in scanned["files"]),
            "by_category": {},
            "volatile_checkpoints_observed": len(scanned["volatile_checkpoints"]),
        },
        "files": scanned["files"],
        "volatile_checkpoints": scanned["volatile_checkpoints"],
        "runstore": runstore_entries(root, tmp, [e["path"] for e in scanned["files"]
                                                if e["category"] == "checkpoint"],
                                     scanned["volatile_checkpoints"]),
    }
    for entry in scanned["files"]:
        key = entry["category"]
        bucket = manifest["counts"]["by_category"].setdefault(key, {"files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += entry["size"]
    manifest["manifest_digest"] = digest({k: v for k, v in manifest.items()
                                          if k not in ("generated_at", "manifest_digest")})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return manifest


# --------------------------------------------------------------------------- verify
def verify(root: Path, manifest_path: Path, tmp: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    problems: list[dict] = []
    ok = 0

    expected_digest = manifest.get("manifest_digest")
    recomputed_digest = digest({k: v for k, v in manifest.items()
                                if k not in ("generated_at", "manifest_digest")})
    if expected_digest != recomputed_digest:
        problems.append({"kind": "manifest_digest", "detail":
                         f"manifest self-digest {expected_digest} != {recomputed_digest}"})

    pinned = {e["path"]: e for e in manifest["files"]}
    for rel, entry in sorted(pinned.items()):
        path = root / rel
        if not path.is_file():
            problems.append({"kind": "missing", "path": rel})
            continue
        if path.stat().st_size != entry["size"]:
            problems.append({"kind": "size_changed", "path": rel,
                             "expected": entry["size"], "actual": path.stat().st_size})
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            problems.append({"kind": "sha256_changed", "path": rel,
                             "expected": entry["sha256"], "actual": actual})
        else:
            ok += 1

    # new files inside a pinned scope must not slip in unnoticed
    found = {e["path"] for e in scan(root)["files"]}
    for extra in sorted(found - set(pinned)):
        problems.append({"kind": "unexpected_new_file", "path": extra})

    warnings: list[dict] = []
    store = runstore_entries(root, tmp, [e["path"] for e in manifest["files"]
                                        if e["category"] == "checkpoint"],
                             manifest.get("volatile_checkpoints", []))
    for run_id in store.get("runs_with_checkpoints_only_in_scratch", []):
        warnings.append({"kind": "run_checkpoint_only_in_scratch", "path": run_id})
    if store["entries_digest"] != manifest["runstore"]["entries_digest"]:
        for rel, entry in sorted(store["databases"].items()):
            want = manifest["runstore"]["databases"].get(rel, {})
            if entry["entries_digest"] != want.get("entries_digest"):
                bad_tables = [t for t, v in entry["tables"].items()
                              if v["digest"] != want.get("tables", {}).get(t, {}).get("digest")]
                problems.append({"kind": "runstore_entries_changed", "path": rel,
                                 "tables": bad_tables})
    for run_id, info in manifest["runstore"].get("runs_with_checkpoints", {}).items():
        hashes = [e["path"] for e in manifest["files"]
                  if e["category"] == "checkpoint" and run_id in e["path"]]
        if not hashes:
            problems.append({"kind": "run_checkpoint_not_pinned", "path": run_id})

    return {"schema": manifest["schema"], "root": str(root), "manifest": str(manifest_path),
            "files_pinned": len(pinned), "files_ok": ok, "problems": problems, "warnings": warnings,
            "runs_with_checkpoints": len(manifest["runstore"].get("runs_with_checkpoints", {})),
            "verdict": "ok" if not problems else "RED"}


# --------------------------------------------------------------------------- inventory
UUID_RE = __import__("re").compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def inventory(root: Path, manifest_path: Path, out_path: Path, tmp: Path) -> dict:
    """Human-readable inventory: every pinned checkpoint mapped to its RunStore run."""
    manifest = json.loads(manifest_path.read_text())
    con, _ = open_runstore(root / "artifacts/control.sqlite3", tmp)
    con.row_factory = sqlite3.Row
    runs = {r["run_id"]: dict(r) for r in con.execute("select * from runs")}
    experiments = {r["experiment_id"]: dict(r) for r in con.execute("select * from experiments")}
    con.close()

    lines = ["# AinerZero V9 baseline inventory (read-only freeze)", "",
             f"- manifest: `{manifest_path}` · digest `{manifest['manifest_digest']}`",
             f"- pinned: {manifest['counts']['files_total']} files / "
             f"{manifest['counts']['bytes_total'] / 1e6:.1f} MB · generated {manifest['generated_at']}",
             f"- volatile test scratch observed and excluded: "
             f"{manifest['counts']['volatile_checkpoints_observed']} checkpoints", "",
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
        exp = info.get("experiment_id") or ""
        for entry in items:
            index += 1
            lines.append(f"| {index} | `{entry['path']}` | `{run_id}` | "
                         f"{info.get('state', 'not in RunStore')} | {exp} | {entry['size']} | "
                         f"`{entry['sha256'][:16]}` |")
    lines += ["", "## C0 / GridLab2D episode datasets", ""]
    for entry in manifest["files"]:
        if entry["category"].startswith("dataset."):
            lines.append(f"- `{entry['path']}` · {entry['size']} B · `{entry['sha256'][:16]}`")
    lines += ["", "## Registrations", ""]
    regs = [e for e in manifest["files"] if e["category"] == "registration"]
    lines.append(f"{len(regs)} registration / pre-registration documents pinned "
                 f"({sum(e['size'] for e in regs) / 1e6:.1f} MB); first 10:")
    for entry in regs[:10]:
        lines.append(f"- `{entry['path']}` · `{entry['sha256'][:16]}`")
    lines += ["", "## RunStore", ""]
    for db, entry in sorted(manifest["runstore"]["databases"].items()):
        tables = ", ".join(f"{t}={v['rows']}" for t, v in sorted(entry["tables"].items()))
        lines.append(f"- `{db}` · {entry['mode']} · entries_digest `{entry['entries_digest'][:16]}` · {tables}")
    lines += ["", f"- runs whose only checkpoint is volatile scratch: "
                  f"{manifest['runstore'].get('runs_with_checkpoints_only_in_scratch', []) or 'none'}",
              f"- experiments with a manifest_hash: "
                  f"{sum(1 for e in experiments.values() if e.get('manifest_hash'))}/{len(experiments)}",
              f"- runs whose checkpoint is pinned: {len(manifest['runstore']['runs_with_checkpoints'])}"
              f"/{len(runs)} RunStore runs", "",
              "## How to re-verify", "", "```bash",
              "python3 scripts/v9_baseline_manifest.py verify    # exit 0 = every pinned byte unchanged",
              "python3 scripts/v9_baseline_manifest.py selftest  # exit 0 = every injected fault turned it red",
              "```", ""]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    return {"out": str(out_path), "checkpoints": sum(len(v) for v in by_run.values()),
            "runs": len(by_run), "registrations": len(regs)}


# --------------------------------------------------------------------------- selftest
def clone(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if subprocess.run(["cp", "-c", str(src), str(dst)], capture_output=True).returncode != 0:
        shutil.copy2(src, dst)


def make_symlink_tree(root: Path, manifest_path: Path, dest: Path) -> None:
    """Materialise a throw-away root: symlinks for pinned files, clones for databases."""
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["files"]:
        src, dst = root / entry["path"], dest / entry["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        if entry["category"] == "runstore.file":
            clone(src, dst)
        else:
            os.symlink(src.resolve(), dst)


def selftest(root: Path, manifest_path: Path, work: Path) -> int:
    """Inject each fault into a symlinked copy; every one must turn `verify` red."""
    results: list[dict] = []

    def run_case(name: str, tamper) -> dict:
        case_root = work / name
        if case_root.exists():
            shutil.rmtree(case_root)
        make_symlink_tree(root, manifest_path, case_root)
        case_manifest = case_root / "manifest.json"
        shutil.copy2(manifest_path, case_manifest)
        detail = tamper(case_root, case_manifest) if tamper else "no fault injected"
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                               "verify", "--root", str(case_root),
                               "--manifest", str(case_manifest), "--json"],
                              capture_output=True, text=True)
        body = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
        results.append({"case": name, "exit": proc.returncode, "fault": detail,
                        "problems": [p["kind"] for p in body.get("problems", [])][:4],
                        "stderr": proc.stderr.strip()[-200:]})
        return results[-1]

    run_case("clean", None)
    for case in results:
        if case["case"] == "clean" and case["exit"] != 0:
            print(json.dumps(results, ensure_ascii=False, indent=1))
            print("selftest: the clean copy must verify green", file=sys.stderr)
            return 1

    checkpoints = [e["path"] for e in json.loads(manifest_path.read_text())["files"]
                   if e["category"] == "checkpoint"]

    def tamper_sha(case_root: Path, _):
        """Flip one byte of a checkpoint, keeping its size: only the SHA can catch this."""
        target = case_root / checkpoints[0]
        data = bytearray(target.read_bytes())
        data[len(data) // 2] ^= 0x01
        target.unlink()
        target.write_bytes(bytes(data))
        return f"flipped one byte of {Path(checkpoints[0]).name} (size unchanged)"

    def tamper_swap(case_root: Path, _):
        """Overwrite one baseline checkpoint with another pinned checkpoint's bytes."""
        donor, victim = checkpoints[0], checkpoints[-1]
        data = (case_root / donor).read_bytes()
        target = case_root / victim
        target.unlink()
        target.write_bytes(data)
        return f"copied {Path(donor).name} over {Path(victim).name} (baseline swap)"

    def tamper_size(case_root: Path, _):
        entry = next(e for e in json.loads(manifest_path.read_text())["files"]
                     if e["category"] == "registration")
        target = case_root / entry["path"]
        target.unlink()
        target.write_bytes(b"{}")
        return f"truncated a registration document: {entry['path']}"

    def tamper_missing(case_root: Path, _):
        entry = next(e for e in json.loads(manifest_path.read_text())["files"]
                     if e["category"].startswith("dataset."))
        (case_root / entry["path"]).unlink()
        return f"deleted a dataset file: {entry['path']}"

    def tamper_extra(case_root: Path, _):
        entry = next(e for e in json.loads(manifest_path.read_text())["files"]
                     if e["category"] == "checkpoint")
        extra = case_root / Path(entry["path"]).parent / "smuggled-extra.safetensors"
        extra.write_bytes(b"not in the manifest")
        return f"added an unpinned checkpoint next to {Path(entry['path']).name}"

    def tamper_runstore(case_root: Path, _):
        db = case_root / "artifacts/control.sqlite3"
        con = sqlite3.connect(str(db))
        con.execute("UPDATE runs SET state='completed_forged' WHERE run_id=(SELECT run_id FROM "
                    "runs ORDER BY run_id LIMIT 1)")
        con.commit()
        changed = con.total_changes
        con.close()
        return f"UPDATE runs SET state='completed_forged' on one row ({changed} row)"

    def tamper_manifest(case_root: Path, case_manifest: Path):
        doc = json.loads(case_manifest.read_text())
        doc["files"][0]["sha256"] = "0" * 64
        case_manifest.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        return "edited the stored sha of files[0] in the manifest copy"

    run_case("checkpoint_byte_flip", tamper_sha)
    run_case("checkpoint_swapped", tamper_swap)
    run_case("registration_truncated", tamper_size)
    run_case("dataset_file_deleted", tamper_missing)
    run_case("checkpoint_smuggled_in", tamper_extra)
    run_case("runstore_row_forged", tamper_runstore)
    run_case("manifest_self_edited", tamper_manifest)

    blind = [r["case"] for r in results if r["case"] != "clean" and r["exit"] == 0]
    print(json.dumps({"selftest": results, "blind": blind}, ensure_ascii=False, indent=1))
    if blind:
        print(f"selftest: {len(blind)} injected fault(s) NOT detected: {blind}", file=sys.stderr)
        return 1
    print(f"selftest: clean copy green, all {len(results) - 1} injected faults detected",
          file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("build", "verify", "selftest", "inventory"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--inventory", type=Path,
                        default=Path("reports/V9-baseline/BASELINE_INVENTORY.md"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if "mlx" in sys.modules or "torch" in sys.modules or "onnxruntime" in sys.modules:
        print("refusing to run: a model runtime is already imported", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="v9-baseline-") as tmpdir:
        tmp = Path(tmpdir)
        if args.command == "build":
            manifest = build(root, args.out, tmp)
            summary = {"command": "build", "root": str(root), "out": str(args.out),
                       "files": manifest["counts"]["files_total"],
                       "bytes": manifest["counts"]["bytes_total"],
                       "by_category": manifest["counts"]["by_category"],
                       "volatile_checkpoints_observed":
                           manifest["counts"]["volatile_checkpoints_observed"],
                       "manifest_digest": manifest["manifest_digest"]}
            print(json.dumps(summary, indent=1, ensure_ascii=False) if args.json
                  else f"build: {summary['files']} files / {summary['bytes']} bytes -> {args.out}\n"
                       f"       manifest_digest {summary['manifest_digest'][:16]} "
                       f"({summary['volatile_checkpoints_observed']} volatile checkpoints excluded)")
            return 0

        if args.command == "verify":
            result = verify(root, args.manifest, tmp)
            if args.json:
                print(json.dumps(result, indent=1, ensure_ascii=False))
            else:
                print(f"verify: {result['files_ok']}/{result['files_pinned']} pinned files match, "
                      f"verdict {result['verdict']}")
                for problem in result["problems"][:20]:
                    print(f"  - {problem['kind']}: {problem.get('path', '')}")
            return 0 if result["verdict"] == "ok" else 1

        if args.command == "inventory":
            result = inventory(root, args.manifest, args.inventory, tmp)
            print(json.dumps(result, indent=1, ensure_ascii=False) if args.json
                  else f"inventory: {result['checkpoints']} checkpoints over {result['runs']} runs, "
                       f"{result['registrations']} registrations -> {result['out']}")
            return 0

        return selftest(root, args.manifest, tmp)


if __name__ == "__main__":
    sys.exit(main())
