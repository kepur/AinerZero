"""Unit test verifying that S3-C2 store and cues are strictly pure-CPU.

Ensures no MLX or GPU libraries are imported when importing or using store and cues.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def test_pure_cpu_zero_mlx_imports() -> None:
    code = """
import sys
from ainerzero.v9.experiments.s3 import store, cues

mlx_modules = [m for m in sys.modules if m == "mlx" or m.startswith("mlx.")]
if mlx_modules:
    print(f"MLX modules detected: {mlx_modules}")
    sys.exit(1)
print("PURE_CPU_OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Subprocess failed with code {result.returncode}:\n{result.stderr}"
    assert "PURE_CPU_OK" in result.stdout
