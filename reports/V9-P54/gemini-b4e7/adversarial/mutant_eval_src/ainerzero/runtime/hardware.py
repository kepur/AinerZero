"""Read-only, allowlisted diagnostics; never changes machine or service settings."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psutil


def _command(args: list[str], timeout: float = 15) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True)
    return result.stdout


def probe_mlx() -> dict:
    """Isolate native backend errors from the supervisor process."""
    try:
        raw = _command([sys.executable, "-m", "ainerzero.runtime.mlx_probe"], timeout=30)
        report = json.loads(raw)
        if not isinstance(report, dict) or not isinstance(report.get("available"), bool):
            raise ValueError("invalid backend probe response")
        return report
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"available": False, "error": f"{type(exc).__name__}: backend probe failed"}


def collect_hardware(*, include_mlx: bool = True, path: Path | None = None) -> dict:
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage(path or Path.cwd())
    warnings: list[str] = []
    machine: dict = {"cpu_logical": os.cpu_count(), "cpu_physical": psutil.cpu_count(False)}
    power = "unknown"
    if sys.platform == "darwin":
        try:
            data = json.loads(
                _command(["system_profiler", "-json", "SPHardwareDataType", "SPDisplaysDataType"])
            )
            hardware = data.get("SPHardwareDataType", [{}])[0]
            machine.update(
                {
                    "model": hardware.get("machine_model"),
                    "chip": hardware.get("chip_type"),
                    "cpu_description": hardware.get("number_processors"),
                }
            )
            displays = data.get("SPDisplaysDataType", [])
            machine["gpu"] = [
                {"name": gpu.get("sppci_model"), "cores": gpu.get("sppci_cores")}
                for gpu in displays
            ]
        except (OSError, subprocess.SubprocessError, ValueError, IndexError, TypeError):
            warnings.append("macOS hardware details unavailable")
        try:
            battery = _command(["pmset", "-g", "batt"], timeout=5)
            if "AC Power" in battery:
                power = "ac"
            elif "Battery Power" in battery:
                power = "battery"
        except (OSError, subprocess.SubprocessError):
            warnings.append("power source unavailable")
    packages = {}
    for name in ("ainerzero", "mlx", "mlx-metal", "numpy", "pydantic", "safetensors", "psutil"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "scope": "M0 hardware readiness; not a training throughput benchmark",
        "platform": {
            "system": platform.system(),
            "version": platform.mac_ver()[0],
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "machine": machine,
        "memory": {
            "total_bytes": memory.total,
            "available_bytes": memory.available,
            "swap_used_bytes": swap.used,
        },
        "disk": {"free_bytes": disk.free, "total_bytes": disk.total},
        "power_source": power,
        "packages": packages,
        "backend": probe_mlx() if include_mlx else {"available": None, "checked": False},
        "warnings": warnings,
    }
