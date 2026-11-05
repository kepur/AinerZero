#!/usr/bin/env python3
"""
Official Weights Downloader for ainerzero.V9.T49 (gemini-u7w4)
Strict compliance with:
- Single stream (one file at a time)
- Rate limit <= 2.0 MiB/s (2,097,152 B/s)
- Direct verification against official LFS SHA256 hashes
- Automatic periodic relay heartbeat (every 180s)
- Resume / restart capability (-C - equivalent)
- Error out and delete incomplete/mismatched files
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
REPORT_DIR = ROOT / "reports/V9-T49/gemini-u7w4"
LOG_FILE = REPORT_DIR / "download.log"

MAX_RATE_BYTES_PER_SEC = 2 * 1024 * 1024  # 2.0 MiB/s = 2,097,152 B/s
CHUNK_SIZE = 64 * 1024  # 64 KiB
HEARTBEAT_INTERVAL_S = 180  # 3 minutes

TARGETS = [
    {
        "name": "SAM 2.1 Tiny",
        "category": "t10",
        "url": "https://huggingface.co/facebook/sam2.1-hiera-tiny/resolve/de431c4043854a71d8101e17995dfe596bf101a5/model.safetensors",
        "dest": ROOT / "envs/teachers/t10/weights/sam2.1-hiera-tiny/model.safetensors",
        "size": 155908064,
        "sha256": "48c14467e5cf9e51870511feb72c89688e82dd74523142c0538b663e193ac2a7",
        "repo": "facebook/sam2.1-hiera-tiny",
        "commit": "de431c4043854a71d8101e17995dfe596bf101a5",
        "license": "Apache-2.0"
    },
    {
        "name": "BootsTAPIR v2",
        "category": "t10",
        "url": "https://huggingface.co/google/tapnet/resolve/5d3fb48e76c5422841e38501514121e251beabb7/bootstapir_checkpoint_v2.pt",
        "dest": ROOT / "envs/teachers/t10/weights/tapnet/bootstapir_checkpoint_v2.pt",
        "size": 218886140,
        "sha256": "8493c7a69e02c85b9382fbb3c7b8b539b36bc08ede744b9e99feb739a0129f4b",
        "repo": "google/tapnet",
        "commit": "5d3fb48e76c5422841e38501514121e251beabb7",
        "license": "Apache-2.0"
    },
    {
        "name": "MapAnything Apache",
        "category": "t12",
        "url": "https://huggingface.co/facebook/map-anything-apache/resolve/00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a/model.safetensors",
        "dest": ROOT / "envs/teachers/t12/weights/map-anything-apache/model.safetensors",
        "size": 4914062480,
        "sha256": "fa06c0fdccefc5048e072c85935d5789b1e36b307f3859033c17f9dcb9fd5201",
        "repo": "facebook/map-anything-apache",
        "commit": "00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a",
        "license": "Apache-2.0"
    }
]

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

last_heartbeat = [0.0]

def maybe_heartbeat(msg):
    now = time.time()
    if now - last_heartbeat[0] > HEARTBEAT_INTERVAL_S:
        try:
            cmd = [
                "python3", "/Users/mac/AinerWorkFlow/AinerRelay/bin/relay",
                "heartbeat", "ainerzero.V9.T49", "--agent", "gemini-u7w4",
                "--msg", msg
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            log(f"Relay heartbeat sent: {res.stdout.strip()}")
            last_heartbeat[0] = now
        except Exception as e:
            log(f"Heartbeat warning: {e}")

def download_file(target):
    dest = Path(target["dest"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    url = target["url"]
    expected_size = target["size"]
    expected_sha = target["sha256"]
    name = target["name"]

    log(f"Starting single-stream download for {name} -> {dest}")
    log(f"Target size: {expected_size} bytes ({expected_size / (1024**2):.2f} MB), Rate limit: 2.00 MiB/s")

    # Check existing file
    if dest.exists() and dest.stat().st_size == expected_size:
        log(f"File {dest} already exists with exact size. Verifying SHA256...")
        h = hashlib.sha256(dest.read_bytes()).hexdigest()
        if h == expected_sha:
            log(f"SHA256 verified! Matches: {h}")
            return {
                "name": name,
                "dest": str(dest),
                "size_bytes": expected_size,
                "sha256": h,
                "verified": True,
                "elapsed_s": 0.0,
                "avg_rate_mib_s": 0.0
            }
        else:
            log(f"SHA mismatch on existing file: got {h}, expected {expected_sha}. Removing.")
            dest.unlink()

    part_file = dest.with_suffix(dest.suffix + ".part")
    existing_bytes = part_file.stat().st_size if part_file.exists() else 0

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    if existing_bytes > 0:
        req.add_header("Range", f"bytes={existing_bytes}-")
        log(f"Resuming download from byte {existing_bytes}...")

    t_start = time.time()
    bytes_downloaded = existing_bytes
    bytes_session = 0
    t_session_start = time.time()

    with urllib.request.urlopen(req) as response:
        # Check if server honored Range
        if existing_bytes > 0 and response.status not in (206, 200):
            raise RuntimeError(f"Unexpected status for range request: {response.status}")
        
        mode = "ab" if existing_bytes > 0 and response.status == 206 else "wb"
        if mode == "wb":
            existing_bytes = 0
            bytes_downloaded = 0

        with open(part_file, mode) as f:
            while True:
                chunk_start = time.time()
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                
                f.write(chunk)
                sz = len(chunk)
                bytes_downloaded += sz
                bytes_session += sz

                # Rate limiting <= 2 MiB/s
                elapsed = time.time() - t_session_start
                if elapsed > 0:
                    expected_elapsed = bytes_session / MAX_RATE_BYTES_PER_SEC
                    if expected_elapsed > elapsed:
                        time.sleep(expected_elapsed - elapsed)

                # Periodic heartbeat & logging
                pct = (bytes_downloaded / expected_size) * 100
                rate_mib = (bytes_session / (1024**2)) / max(1e-3, (time.time() - t_session_start))
                msg = f"正在下载 {name}: {bytes_downloaded}/{expected_size} B ({pct:.1f}%), 速率: {rate_mib:.2f} MiB/s"
                maybe_heartbeat(msg)

    total_time = time.time() - t_start
    avg_rate = (bytes_session / (1024**2)) / max(1e-3, total_time)
    log(f"Download finished for {name} in {total_time:.1f}s (avg rate: {avg_rate:.2f} MiB/s)")

    # Verify size
    final_size = part_file.stat().st_size
    if final_size != expected_size:
        part_file.unlink(missing_ok=True)
        raise ValueError(f"Size mismatch: expected {expected_size}, got {final_size}")

    # Verify SHA256
    log(f"Computing SHA256 for {name}...")
    sha = hashlib.sha256()
    with open(part_file, "rb") as f:
        while b := f.read(1024 * 1024):
            sha.update(b)
    actual_sha = sha.hexdigest()

    if actual_sha != expected_sha:
        part_file.unlink(missing_ok=True)
        raise ValueError(f"SHA256 mismatch for {name}: got {actual_sha}, expected {expected_sha}")

    log(f"SHA256 verified for {name}: {actual_sha}")
    part_file.rename(dest)

    return {
        "name": name,
        "dest": str(dest),
        "size_bytes": final_size,
        "sha256": actual_sha,
        "verified": True,
        "elapsed_s": round(total_time, 2),
        "avg_rate_mib_s": round(avg_rate, 3)
    }

def main():
    log("=== Starting ainerzero.V9.T49 Download Session ===")
    results = []
    t0 = time.time()
    
    maybe_heartbeat("开始按清单下载三份权重文件（单流 <= 2 MiB/s）")

    for target in TARGETS:
        res = download_file(target)
        results.append(res)
        maybe_heartbeat(f"已完成 {target['name']} 下载与 SHA256 校验")

    summary_file = REPORT_DIR / "downloads.json"
    with open(summary_file, "w") as f:
        json.dump(results, f, indent=2)

    total_elapsed = time.time() - t0
    log(f"All downloads completed and verified in {total_elapsed:.1f}s. Summary saved to {summary_file}")

if __name__ == "__main__":
    main()
