#!/usr/bin/env python3
"""
DA3-Small / DA3-Base Weights Downloader for ainerzero.V9.T6
Strict compliance with:
- Single stream
- Rate limit <= 2.0 MiB/s (2,097,152 B/s)
- Direct verification against official LFS SHA256 hashes
- Progress and audit logging to reports/V9-T6/
"""

import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEST_DIR = REPO_ROOT / "artifacts/teachers/da3"
REPORT_DIR = REPO_ROOT / "reports/V9-T6"
LOG_FILE = REPORT_DIR / "download_progress.log"

MAX_RATE_BYTES_PER_SEC = 2 * 1024 * 1024  # 2 MiB/s
CHUNK_SIZE = 64 * 1024  # 64 KiB

TARGETS = [
    {
        "model_id": "depth-anything/DA3-SMALL",
        "folder": "DA3-SMALL",
        "revision": "e08cab65ca0ec38e7826075418411ab90cab4da3",
        "files": [
            {
                "rfilename": "config.json",
                "size": 1202,
                "sha256": None,  # Will compute and record
            },
            {
                "rfilename": "model.safetensors",
                "size": 137248940,
                "sha256": "364492e38a3a06d221ac75da7f6621ada3f2361cd24fde11ba79091e9f40efcf",
            },
        ],
    },
    {
        "model_id": "depth-anything/DA3-BASE",
        "folder": "DA3-BASE",
        "revision": "f4a6c9b3c95e41c82048423d3493a81ec3fa810e",
        "files": [
            {
                "rfilename": "config.json",
                "size": 1205,
                "sha256": None,
            },
            {
                "rfilename": "model.safetensors",
                "size": 541518028,
                "sha256": "e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5",
            },
        ],
    },
]


def log_msg(msg: str):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def download_with_rate_limit(url: str, dest_path: Path, expected_size: int, expected_sha: str | None) -> dict:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(".downloading")

    log_msg(f"Starting download: {url} -> {dest_path.name}")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AinerZero-T6-DA3-Downloader/1.0 (RateLimited<=2MiB/s)"},
    )

    t_start = time.time()
    hasher = hashlib.sha256()
    bytes_downloaded = 0
    last_log_time = t_start

    with urllib.request.urlopen(req) as response, open(temp_path, "wb") as out_f:
        while True:
            chunk_start = time.time()
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break

            out_f.write(chunk)
            hasher.update(chunk)
            bytes_downloaded += len(chunk)

            # Rate limit enforcement: sleep if chunk was retrieved too fast
            chunk_elapsed = time.time() - chunk_start
            min_time = len(chunk) / MAX_RATE_BYTES_PER_SEC
            if chunk_elapsed < min_time:
                time.sleep(min_time - chunk_elapsed)

            now = time.time()
            if now - last_log_time >= 5.0:
                overall_elapsed = now - t_start
                cur_rate_kib = (bytes_downloaded / overall_elapsed) / 1024 if overall_elapsed > 0 else 0
                pct = (bytes_downloaded / expected_size * 100) if expected_size > 0 else 0
                log_msg(
                    f"Progress {dest_path.name}: {bytes_downloaded}/{expected_size} B ({pct:.1f}%) "
                    f"at {cur_rate_kib:.1f} KiB/s [Limit: {MAX_RATE_BYTES_PER_SEC/1024:.0f} KiB/s]"
                )
                last_log_time = now

    t_end = time.time()
    total_elapsed = t_end - t_start
    final_sha = hasher.hexdigest()
    avg_rate_kib = (bytes_downloaded / total_elapsed) / 1024 if total_elapsed > 0 else 0

    log_msg(
        f"Completed {dest_path.name}: {bytes_downloaded} bytes in {total_elapsed:.1f}s "
        f"(avg rate {avg_rate_kib:.1f} KiB/s, SHA256: {final_sha})"
    )

    if expected_size and bytes_downloaded != expected_size:
        temp_path.unlink(missing_ok=True)
        raise ValueError(f"Size mismatch for {dest_path.name}: got {bytes_downloaded}, expected {expected_size}")

    if expected_sha and final_sha.lower() != expected_sha.lower():
        temp_path.unlink(missing_ok=True)
        raise ValueError(f"SHA256 mismatch for {dest_path.name}: got {final_sha}, expected {expected_sha}")

    if dest_path.exists():
        dest_path.unlink()
    temp_path.rename(dest_path)

    return {
        "file": str(dest_path.relative_to(REPO_ROOT)),
        "size_bytes": bytes_downloaded,
        "sha256": final_sha,
        "elapsed_s": round(total_elapsed, 2),
        "avg_rate_kib_s": round(avg_rate_kib, 2),
        "verified": True,
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    log_msg("=== DA3 Weights Download Run Started ===")

    manifest_records = []
    total_bytes = 0
    t0_all = time.time()

    for target in TARGETS:
        model_id = target["model_id"]
        folder = target["folder"]
        rev = target["revision"]
        base_url = f"https://huggingface.co/{model_id}/resolve/{rev}"

        for f_info in target["files"]:
            rfilename = f_info["rfilename"]
            expected_size = f_info["size"]
            expected_sha = f_info["sha256"]
            url = f"{base_url}/{rfilename}"
            dest = DEST_DIR / folder / rfilename

            # Check if file already exists with matching SHA
            if dest.exists() and dest.stat().st_size == expected_size:
                h = hashlib.sha256()
                with open(dest, "rb") as f:
                    while chunk := f.read(1024 * 1024):
                        h.update(chunk)
                cur_sha = h.hexdigest()
                if not expected_sha or cur_sha.lower() == expected_sha.lower():
                    log_msg(f"File {dest.name} already exists and verified (SHA256: {cur_sha}). Skipping download.")
                    manifest_records.append({
                        "model": model_id,
                        "file": str(dest.relative_to(REPO_ROOT)),
                        "size_bytes": dest.stat().st_size,
                        "sha256": cur_sha,
                        "elapsed_s": 0.0,
                        "avg_rate_kib_s": 0.0,
                        "verified": True,
                        "cached": True,
                    })
                    total_bytes += dest.stat().st_size
                    continue

            record = download_with_rate_limit(url, dest, expected_size, expected_sha)
            record["model"] = model_id
            manifest_records.append(record)
            total_bytes += record["size_bytes"]

    total_wall_s = time.time() - t0_all
    summary = {
        "status": "COMPLETED",
        "total_files": len(manifest_records),
        "total_bytes": total_bytes,
        "total_wall_s": round(total_wall_s, 2),
        "rate_limit_applied": "2.0 MiB/s",
        "records": manifest_records,
    }

    out_json = REPORT_DIR / "downloads.json"
    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2)

    log_msg(f"=== All downloads completed successfully. Total {total_bytes} bytes. Written to {out_json} ===")


if __name__ == "__main__":
    main()
