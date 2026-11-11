#!/usr/bin/env python3
"""Read-only S5 inventory. Writes evidence next to this file. No downloads, no training."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import subprocess
import time
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
AZ = Path("/Users/mac/AinerWorkFlow/AinerZero")
AWZ = Path("/Users/mac/AinerWorkFlow/AnimeWorldZero")
FORGE = Path("/Users/mac/AinerWorkFlow/AinerForge")
RELAY = ["python3", "/Users/mac/AinerWorkFlow/AinerRelay/bin/relay"]

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".exr", ".tga", ".tif", ".tiff"}
VID_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
SKIP_DIR = {
    ".git",
    ".godot",
    "node_modules",
    "site-packages",
    "__pycache__",
    ".venv",
    ".venv-t4",
    ".venv-t6",
    "envs",
}


def write(name: str, text: str) -> None:
    (OUT / name).write_text(text, encoding="utf-8")


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 180) -> str:
    env = os.environ.copy()
    env["RELAY_SESSION_ID"] = "sess-12e205e2bafa"
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return f"$ {' '.join(cmd)}\nexit={p.returncode}\n{p.stdout}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def png_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as f:
            sig = f.read(24)
        if sig[:8] != b"\x89PNG\r\n\x1a\n" or sig[12:16] != b"IHDR":
            return None
        w, h = struct.unpack(">II", sig[16:24])
        return int(w), int(h)
    except OSError:
        return None


def jpeg_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as f:
            data = f.read(65536)
        if data[:2] != b"\xff\xd8":
            return None
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                return int(w), int(h)
            if marker == 0xD8 or marker == 0xD9:
                i += 2
                continue
            if i + 4 > len(data):
                break
            seg = struct.unpack(">H", data[i + 2 : i + 4])[0]
            i += 2 + seg
        return None
    except OSError:
        return None


def safetensors_header(path: Path) -> dict:
    with path.open("rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        if n > 5_000_000:
            return {"error": f"header_len={n}"}
        header = json.loads(f.read(n))
    meta = header.get("__metadata__", {})
    tensors = {}
    for k, v in header.items():
        if k == "__metadata__":
            continue
        if isinstance(v, dict) and "dtype" in v and "shape" in v:
            tensors[k] = {"dtype": v["dtype"], "shape": v["shape"]}
    return {
        "tensor_count": len(tensors),
        "metadata_keys": sorted(meta.keys()) if isinstance(meta, dict) else [],
        "tensors_head": dict(list(tensors.items())[:8]),
    }


def walk_media(root: Path, label: str) -> dict:
    counts: Counter[str] = Counter()
    bytes_total = 0
    files = 0
    samples = []
    if not root.exists():
        return {"label": label, "root": str(root), "exists": False}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR and not d.startswith(".venv")]
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext not in IMG_EXT and ext not in VID_EXT:
                continue
            p = Path(dirpath) / name
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            files += 1
            bytes_total += sz
            counts[ext] += 1
            if len(samples) < 8 and ext in {".png", ".jpg", ".jpeg"}:
                wh = png_size(p) if ext == ".png" else jpeg_size(p)
                samples.append({"path": str(p), "bytes": sz, "wh": wh})
    return {
        "label": label,
        "root": str(root),
        "exists": True,
        "files": files,
        "bytes": bytes_total,
        "by_ext": dict(counts),
        "samples": samples,
    }


def main() -> None:
    t0 = time.time()
    teachers = AZ / "artifacts" / "teachers"
    lines = []
    records = []
    for p in sorted(teachers.rglob("*")):
        if not p.is_file():
            continue
        if p.name == ".DS_Store":
            continue
        digest = sha256_file(p)
        rec = {"path": str(p.relative_to(AZ)), "bytes": p.stat().st_size, "sha256": digest}
        records.append(rec)
        lines.append(f"{digest}  {rec['bytes']:12d}  {rec['path']}")
    write("01-teacher-sha256.txt", "\n".join(lines) + "\n")
    (OUT / "01-teacher-sha256.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

    license_hits = []
    for base in [teachers, AZ / "envs" / "teachers" / "src" / "vjepa2-mlx", AZ / "envs" / "teachers" / "t6" / "Depth-Anything-3"]:
        if not base.exists():
            license_hits.append({"base": str(base), "missing": True})
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if "site-packages" in p.parts or ".venv" in p.parts:
                continue
            n = p.name.lower()
            if n.startswith("license") or n.startswith("licence") or n.startswith("copying") or n == "notice":
                license_hits.append({"path": str(p), "bytes": p.stat().st_size})
    write("02-license-files.json", json.dumps(license_hits, indent=2))

    # feature-like files under artifacts (not reports)
    feature_rows = []
    art = AZ / "artifacts"
    for dirpath, dirnames, filenames in os.walk(art):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR and d != "reports"]
        # artifacts/reports is huge historical; skip it. visual teacher caches would be under artifacts/v9 or teachers or pilot.
        for name in filenames:
            low = name.lower()
            if any(k in low for k in ("feature", "vjepa", "teacher-cache", "teacher_cache", "depth")):
                p = Path(dirpath) / name
                try:
                    feature_rows.append({"path": str(p.relative_to(AZ)), "bytes": p.stat().st_size})
                except OSError:
                    pass
    write("03-feature-name-hits.json", json.dumps(feature_rows, indent=2))

    pred_roots = [
        AZ / "reports" / "V9-T6" / "r4" / "predictions",
        AZ / "reports" / "V9-T35" / "predictions",
        AZ / "artifacts" / "v9" / "teachers",
    ]
    pred = []
    for root in pred_roots:
        if not root.exists():
            pred.append({"root": str(root), "exists": False})
            continue
        files = [p for p in root.rglob("*") if p.is_file() and p.suffix in {".safetensors", ".npz", ".npy", ".json"}]
        sample = None
        st = next((p for p in files if p.suffix == ".safetensors"), None)
        if st is not None:
            try:
                sample = {"path": str(st.relative_to(AZ)), "bytes": st.stat().st_size, "header": safetensors_header(st)}
            except Exception as e:  # noqa: BLE001
                sample = {"path": str(st), "error": str(e)}
        pred.append(
            {
                "root": str(root.relative_to(AZ)) if str(root).startswith(str(AZ)) else str(root),
                "exists": True,
                "n_files": len(files),
                "bytes": sum(p.stat().st_size for p in files),
                "suffixes": dict(Counter(p.suffix for p in files)),
                "sample": sample,
            }
        )
    write("04-prediction-and-teacher-bench.json", json.dumps(pred, indent=2))

    media_roots = [
        (AWZ / "assets", "awz-assets"),
        (AWZ / "godot" / "assets", "awz-godot-assets"),
        (AWZ / "godot" / "render", "awz-godot-render"),
        (AWZ / "godot" / "acis", "awz-godot-acis"),
        (FORGE / "data" / "library" / "attachments", "forge-attachments"),
        (FORGE / "data" / "library" / "incoming", "forge-incoming"),
        (FORGE / "data" / "library" / "thumbs", "forge-thumbs"),
        (FORGE / "data" / "staging_downloads", "forge-staging"),
        (AZ / "artifacts" / "v9" / "s1", "az-s1"),
        (AZ / "artifacts" / "v9" / "e1", "az-e1"),
        (AZ / "artifacts" / "gridlab2d", "az-gridlab"),
    ]
    media = [walk_media(p, label) for p, label in media_roots]
    # AWZ reports: count only, group by reports/<child>
    report_groups = []
    reports = AWZ / "reports"
    if reports.exists():
        for child in sorted(reports.iterdir()):
            if not child.is_dir() or child.name in SKIP_DIR:
                continue
            info = walk_media(child, f"awz-reports/{child.name}")
            if info.get("files", 0):
                report_groups.append(
                    {
                        "label": info["label"],
                        "files": info["files"],
                        "bytes": info["bytes"],
                        "by_ext": info["by_ext"],
                        "samples": info["samples"][:3],
                    }
                )
    write(
        "05-visual-media.json",
        json.dumps({"roots": media, "awz_report_groups_with_media": report_groups}, indent=2),
    )

    # forge library.db licenses (read-only). Do not print .token.
    db_path = FORGE / "data" / "library" / "library.db"
    db_out: dict = {"path": str(db_path), "exists": db_path.exists()}
    if db_path.exists():
        uri = f"file:{db_path}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        cur = con.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]
        db_out["tables"] = tables
        schemas = {}
        for t in tables:
            cols = list(cur.execute(f"PRAGMA table_info({t})"))
            schemas[t] = [{"cid": c[0], "name": c[1], "type": c[2]} for c in cols]
        db_out["schemas"] = schemas
        # generic license-like column counts
        summaries = []
        for t, cols in schemas.items():
            names = [c["name"] for c in cols]
            lic_cols = [n for n in names if "licen" in n.lower() or n.lower() in {"status", "source"}]
            if not lic_cols:
                continue
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            entry = {"table": t, "rows": n, "license_like_columns": lic_cols, "counts": {}}
            for col in lic_cols:
                if n > 5000 and col.lower() == "source":
                    continue
                rows = cur.execute(
                    f"SELECT COALESCE(CAST({col} AS TEXT), '<null>'), COUNT(*) FROM {t} GROUP BY 1 ORDER BY 2 DESC LIMIT 30"
                ).fetchall()
                entry["counts"][col] = rows
            summaries.append(entry)
        db_out["summaries"] = summaries
        con.close()
    write("06-forge-library-db.json", json.dumps(db_out, indent=2, default=str))

    # checkpoints
    ckpt = []
    for root in [AZ / "artifacts" / "v9" / "s1", AZ / "artifacts" / "v9" / "e1"]:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if "checkpoint" not in str(p).lower() and p.suffix not in {".safetensors", ".npz", ".mlx"}:
                continue
            if p.suffix not in {".safetensors", ".npz", ".npy", ".json", ".mlx", ".pt"} and "checkpoint" not in p.name.lower():
                continue
            if p.stat().st_size > 80_000_000:
                ckpt.append({"path": str(p.relative_to(AZ)), "bytes": p.stat().st_size, "sha256": "skipped_over_80MB"})
            elif p.suffix in {".safetensors", ".npz", ".npy"} or p.stat().st_size < 2_000_000:
                # hash weight-like and small sidecars; skip huge json manifests of datasets
                if p.suffix == ".json" and p.stat().st_size > 200_000:
                    ckpt.append({"path": str(p.relative_to(AZ)), "bytes": p.stat().st_size, "sha256": "json_not_hashed"})
                else:
                    ckpt.append({"path": str(p.relative_to(AZ)), "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    # The filter above is too broad (every json under s1). Restrict.
    ckpt = [c for c in ckpt if "/checkpoints/" in c["path"] or c["path"].endswith(".safetensors")]
    write("07-checkpoints.json", json.dumps(ckpt, indent=2))

    # one S1 packet keys and one E1 student file keys
    samples = {}
    pkt = AZ / "artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26/packets/train.jsonl"
    if pkt.exists():
        line = pkt.open(encoding="utf-8").readline()
        obj = json.loads(line)
        samples["s1_train_packet_top_keys"] = sorted(obj.keys())
        samples["s1_train_packet_bytes"] = len(line)
        # nested key names only
        nested = {}
        for k, v in obj.items():
            if isinstance(v, dict):
                nested[k] = sorted(v.keys())[:40]
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                nested[k] = {"list0_keys": sorted(v[0].keys())[:40], "len": len(v)}
            else:
                nested[k] = type(v).__name__
        samples["s1_train_packet_shape"] = nested
    truth = AZ / "artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26/truth/train.jsonl"
    if truth.exists():
        obj = json.loads(truth.open(encoding="utf-8").readline())
        samples["s1_truth_top_keys"] = sorted(obj.keys()) if isinstance(obj, dict) else type(obj).__name__
    e1_student = AZ / "artifacts/v9/e1/phase2/datasets/student"
    found = None
    if e1_student.exists():
        for p in e1_student.rglob("*.json"):
            if p.stat().st_size < 5_000_000:
                found = p
                break
        if found is None:
            for p in e1_student.rglob("*"):
                if p.is_file() and p.stat().st_size < 5_000_000:
                    found = p
                    break
    if found is not None:
        samples["e1_student_file"] = str(found.relative_to(AZ))
        samples["e1_student_bytes"] = found.stat().st_size
        if found.suffix == ".json":
            obj = json.loads(found.read_text(encoding="utf-8")[:2_000_000])
            if isinstance(obj, dict):
                samples["e1_student_top_keys"] = sorted(obj.keys())
            elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
                samples["e1_student_list0_keys"] = sorted(obj[0].keys())
                samples["e1_student_list_len"] = len(obj)
    # counts of e1 dataset files
    e1_counts = {}
    e1_root = AZ / "artifacts/v9/e1/phase2/datasets"
    if e1_root.exists():
        for sub in sorted(e1_root.iterdir()):
            if sub.is_dir():
                n = sum(1 for p in sub.rglob("*") if p.is_file())
                b = sum(p.stat().st_size for p in sub.rglob("*") if p.is_file())
                e1_counts[sub.name] = {"files": n, "bytes": b}
    samples["e1_phase2_dataset_counts"] = e1_counts
    write("08-interface-samples.json", json.dumps(samples, indent=2))

    # relay cards
    cards = {}
    for tid in [
        "ainerzero.V9.P5",
        "ainerzero.V9.P6",
        "ainerzero.V9.T4",
        "ainerzero.V9.T8",
        "ainerzero.V9.T6",
        "ainerzero.V9.T35",
    ]:
        raw = subprocess.run(
            RELAY + ["show", tid, "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={**os.environ, "RELAY_SESSION_ID": "sess-12e205e2bafa"},
        )
        try:
            t = json.loads(raw.stdout)
        except json.JSONDecodeError:
            cards[tid] = {"error": raw.stdout[:500]}
            continue
        result = t.get("result")
        cards[tid] = {
            "id": t.get("id"),
            "title": t.get("title"),
            "status": t.get("status"),
            "display_label": t.get("display_label"),
            "kind": t.get("kind"),
            "assignee": t.get("assignee"),
            "acceptance": t.get("acceptance"),
            "depends_on": t.get("depends_on"),
            "file_scope": t.get("file_scope"),
            "needs": t.get("needs"),
            "attempts": t.get("attempts"),
            "result_head": (result[:1200] if isinstance(result, str) else result),
        }
        (OUT / f"relay-prompt-{tid.split('.')[-1]}.txt").write_text(
            subprocess.run(
                RELAY + ["prompt", tid],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env={**os.environ, "RELAY_SESSION_ID": "sess-12e205e2bafa"},
            ).stdout,
            encoding="utf-8",
        )
    write("09-relay-cards.json", json.dumps(cards, indent=2, ensure_ascii=False))

    # rlt tests
    test = AZ / "tests/v9/tokenization/test_rlt.py"
    text = test.read_text(encoding="utf-8")
    write(
        "10-rlt-tests.txt",
        f"path={test}\nbytes={test.stat().st_size}\ndef_test_count={text.count(chr(10)+'def test_')}\nmlx_in_file={'mlx' in text}\n",
    )

    # ffprobe availability
    which = run(["/usr/bin/which", "ffprobe"])
    write("11-ffprobe.txt", which)

    write("00-elapsed.txt", f"elapsed_s={time.time()-t0:.3f}\n")
    print(f"done elapsed_s={time.time()-t0:.3f}")


if __name__ == "__main__":
    main()
