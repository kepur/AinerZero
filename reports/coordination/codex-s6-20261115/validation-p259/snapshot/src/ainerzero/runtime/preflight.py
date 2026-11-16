"""Preflight resource availability, external GPU observations, and frozen identity integrity guards."""

from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

import psutil

# Policy revisions
POLICY_REVISION = "M20261013-09"
LTX_GATEWAY_PATTERN = "[a]i-studio/scripts/ltx25_infer.py"


class PreflightError(RuntimeError):
    """Raised when preflight system conditions or frozen identity checks fail."""


def check_available_memory(
    minimum_gib: float = 16.0,
    *,
    memory_info: Any | None = None,
) -> float:
    """Verify system virtual memory meets the minimum available GiB requirement.

    Returns available memory in GiB on success; raises PreflightError otherwise.
    """
    if memory_info is None:
        memory_info = psutil.virtual_memory()
    available_gib = memory_info.available / (1024**3)
    if available_gib < minimum_gib:
        raise PreflightError(
            f"Available memory {available_gib:.2f} GiB is below required {minimum_gib:.2f} GiB"
        )
    return available_gib


def probe_external_gpu(
    *,
    relay_url: str = "http://127.0.0.1:8790/api/gpu",
    http_getter: Any | None = None,
    ltx_probe: Any | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Observe external GPU occupation without measuring GPU utilisation or taking locks.

    - Queries AinerRelay /api/gpu (ignoring AinerZero's own worker lock).
    - Checks for external heavy GPU workloads (e.g. ai-studio LTX process).
    - Fails softly to state="unknown" if endpoints/commands fail or return invalid data.
    - Never throws; returns structured observation.
    """
    observation: dict[str, Any] = {
        "relay_gpu_free": None,
        "relay_details": None,
        "ltx_busy": None,
        "state": "unknown",  # "free" | "busy" | "unknown"
        "busy_reasons": [],
        "notes": [],
        "policy_revision": POLICY_REVISION,
    }

    # 1. Query AinerRelay /api/gpu
    try:
        if http_getter is not None:
            raw_data = http_getter(relay_url)
        else:
            req = urllib.request.Request(relay_url, headers={"User-Agent": "ainerzero-preflight"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_data = resp.read().decode("utf-8")
        parsed = json.loads(raw_data) if isinstance(raw_data, (str, bytes)) else raw_data
        if isinstance(parsed, dict) and "free" in parsed:
            # Note: Relay server's "free" field only tracks external heavy locks;
            # AinerZero's own lock is reported in "ainerzero" key and excluded from "free".
            observation["relay_gpu_free"] = bool(parsed["free"])
            observation["relay_details"] = parsed
            if not parsed["free"]:
                reason = parsed.get("reason") or "relay reported external gpu busy"
                observation["busy_reasons"].append(f"relay: {reason}")
        else:
            observation["notes"].append("relay /api/gpu returned non-standard payload")
    except Exception as exc:
        observation["notes"].append(f"relay /api/gpu query failed: {type(exc).__name__}: {exc}")

    # 2. Local LTX process probe (pgrep pattern trick [a]i-studio/scripts/ltx25_infer.py)
    try:
        if ltx_probe is not None:
            ltx_busy = ltx_probe()
        else:
            proc = subprocess.run(
                ["pgrep", "-f", LTX_GATEWAY_PATTERN],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            # pgrep rc 0 means found (busy), rc 1 means not found (idle), rc >= 2 means error
            if proc.returncode == 0 and proc.stdout.strip():
                ltx_busy = True
            elif proc.returncode == 1:
                ltx_busy = False
            else:
                ltx_busy = None
        observation["ltx_busy"] = ltx_busy
        if ltx_busy is True:
            observation["busy_reasons"].append("ltx: ai-studio LTX process running")
        elif ltx_busy is None:
            observation["notes"].append("ltx probe returned unknown")
    except Exception as exc:
        observation["notes"].append(f"ltx probe failed: {type(exc).__name__}: {exc}")

    # Determine aggregated state
    # If any external workload is confirmed busy -> "busy"
    if observation["busy_reasons"]:
        observation["state"] = "busy"
    elif observation["relay_gpu_free"] is True and observation["ltx_busy"] is False:
        observation["state"] = "free"
    elif observation["relay_gpu_free"] is True and observation["ltx_busy"] is None:
        # Relay indicates free, LTX probe unknown -> soft unknown
        observation["state"] = "unknown"
    elif observation["relay_gpu_free"] is None and observation["ltx_busy"] is False:
        # Relay unknown, LTX idle -> soft unknown
        observation["state"] = "unknown"
    else:
        observation["state"] = "unknown"

    return observation


def evaluate_gpu_policy(
    gpu_obs: dict[str, Any],
    *,
    is_heavy: bool = False,
) -> tuple[bool, list[str]]:
    """Evaluate external GPU observation against workload tier (Lightweight vs Heavy).

    Per Policy M20261013-09 & ADR-0009:
    - Lightweight workloads (e.g. AinerZero 390k-param training, Godot render):
      External GPU observation is purely informational. Does not block or add wait thresholds.
      Always returns (True, []).
    - Heavy workloads (e.g. LTX, large diffusion):
      Strict mutual exclusion. Blocks if external GPU is "busy" or "unknown".
    """
    reasons: list[str] = []
    if not is_heavy:
        # Lightweight tier: informational only, never rejects
        return True, reasons

    # Heavy tier: mutually exclusive
    state = gpu_obs.get("state", "unknown")
    if state == "busy":
        reasons.extend(gpu_obs.get("busy_reasons") or ["external GPU busy"])
        return False, reasons
    elif state == "unknown":
        reasons.append("external GPU state unknown (cannot safely grant heavy lock)")
        return False, reasons

    return True, reasons


def compute_file_sha256(path: str | Path) -> str:
    """Compute hex sha256 digest of a regular file."""
    p = Path(path)
    if not p.is_file():
        raise PreflightError(f"Target file does not exist or is not a regular file: {p}")
    return hashlib.sha256(p.read_bytes()).hexdigest()


def get_git_status_sha256(cwd: str | Path | None = None) -> str:
    """Compute sha256 digest of `git status --porcelain=v1`."""
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=cwd or Path.cwd(),
        capture_output=True,
        text=True,
        check=True,
    )
    return hashlib.sha256(proc.stdout.encode("utf-8")).hexdigest()


def verify_frozen_identities(
    registered_digests: Mapping[str | Path, str],
    *,
    expected_git_status_sha256: str | None = None,
    cwd: str | Path | None = None,
) -> dict[str, str]:
    """Verify that registered file digests and git working tree match registered freeze.

    Raises PreflightError if any file digest differs or if git status sha256 does not match.
    Returns dictionary of verified digests.
    """
    verified: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}

    for path_key, expected_digest in registered_digests.items():
        p = Path(path_key)
        try:
            actual = compute_file_sha256(p)
        except Exception as exc:
            raise PreflightError(f"Failed to verify {p}: {exc}") from exc
        if actual != expected_digest:
            mismatches[str(p)] = {"expected": expected_digest, "actual": actual}
        else:
            verified[str(p)] = actual

    if mismatches:
        details = json.dumps(mismatches, indent=2)
        raise PreflightError(f"Frozen identity digest mismatch detected:\n{details}")

    if expected_git_status_sha256 is not None:
        actual_git = get_git_status_sha256(cwd=cwd)
        if actual_git != expected_git_status_sha256:
            raise PreflightError(
                f"Working tree git status changed: expected {expected_git_status_sha256}, got {actual_git}"
            )
        verified["git_status_sha256"] = actual_git

    return verified
