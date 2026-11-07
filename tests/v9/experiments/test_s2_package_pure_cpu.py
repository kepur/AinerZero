"""Test pure CPU package isolation for S2 experiments.

Runs Python in isolated mode (`-I`) in a separate subprocess, imports
`ainerzero.v9.experiments.s2` and `ainerzero.v9.experiments.s2.core_math`,
and asserts that MLX is never imported into `sys.modules`.
"""

from __future__ import annotations

import os
import subprocess
import sys


def test_s2_package_pure_cpu_no_mlx_imported() -> None:
    """Assert importing s2 package never loads mlx into sys.modules."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    src_dir = os.path.join(repo_root, "src")

    code = (
        "import sys\n"
        f"sys.path.insert(0, '{src_dir}')\n"
        f"sys.path.insert(0, '{repo_root}')\n"
        "import ainerzero.v9.experiments.s2 as s2\n"
        "import ainerzero.v9.experiments.s2.core_math as cm\n"
        "loaded_mlx = [m for m in sys.modules if m == 'mlx' or m.startswith('mlx.')]\n"
        "assert not loaded_mlx, f'MLX modules loaded unexpectedly: {loaded_mlx}'\n"
        "assert hasattr(s2, 'sigreg'), 'sigreg missing from s2 package'\n"
        "assert hasattr(cm, 'aggregate_macro'), 'aggregate_macro missing from core_math'\n"
        "print('PURE_CPU_OK')\n"
    )

    proc = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Subprocess failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "PURE_CPU_OK" in proc.stdout
