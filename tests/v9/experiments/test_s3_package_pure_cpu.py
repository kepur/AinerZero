"""Test pure CPU package isolation for S3 experiments.

Runs Python in isolated mode (`-I`) in a separate subprocess, imports
`ainerzero.v9.experiments.s3` and all submodules, and asserts that MLX
is never imported into `sys.modules`.
"""

from __future__ import annotations

import os
import subprocess
import sys


def test_s3_package_pure_cpu_no_mlx_imported() -> None:
    """Assert importing s3 package never loads mlx into sys.modules."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    src_dir = os.path.join(repo_root, "src")
    site_packages = [p for p in sys.path if "site-packages" in p]

    code = (
        "import sys\n"
        f"for p in {site_packages!r}:\n"
        "    if p not in sys.path:\n"
        "        sys.path.append(p)\n"
        f"sys.path.insert(0, '{src_dir}')\n"
        f"sys.path.insert(0, '{repo_root}')\n"
        "import ainerzero.v9.experiments.s3 as s3\n"
        "import ainerzero.v9.experiments.s3.spec as spec\n"
        "import ainerzero.v9.experiments.s3.world as world\n"
        "import ainerzero.v9.experiments.s3.content as content\n"
        "import ainerzero.v9.experiments.s3.tour as tour\n"
        "import ainerzero.v9.experiments.s3.data as data\n"
        "loaded_mlx = [m for m in sys.modules if m == 'mlx' or m.startswith('mlx.')]\n"
        "assert not loaded_mlx, f'MLX modules loaded unexpectedly: {loaded_mlx}'\n"
        "assert hasattr(s3, 'generate_episode'), 'generate_episode missing from s3 package'\n"
        "assert spec.OBS_DIM == 198, f'OBS_DIM mismatch: {spec.OBS_DIM}'\n"
        "print('PURE_CPU_OK')\n"
    )

    proc = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Subprocess failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "PURE_CPU_OK" in proc.stdout
