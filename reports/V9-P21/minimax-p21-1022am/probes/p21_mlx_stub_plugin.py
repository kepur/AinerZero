"""A pytest plugin that keeps the real MLX runtime out of the test process.

``src/ainerzero/v9/experiments/s1/arms.py`` imports ``mlx.core``/``mlx.nn`` at
module level, so *any* test module that imports ``arms`` pulls the real MLX
runtime in.  The P21 review is CPU-only (no MLX import, no model forward), so
the stub is installed before the test modules are imported.

Tests that genuinely need the real MLX runtime therefore fail with the stub;
those failures are reported as "not verifiable under the CPU-only constraint",
not as product defects.
"""

from __future__ import annotations

import sys
import types

if "mlx" not in sys.modules:
    mlx = types.ModuleType("mlx")
    mlx.__path__ = []  # type: ignore[attr-defined]
    core = types.ModuleType("mlx.core")
    core.__spec__ = types.SimpleNamespace(origin="p21-stub")  # type: ignore[attr-defined]
    nn = types.ModuleType("mlx.nn")
    nn.__spec__ = types.SimpleNamespace(origin="p21-stub")  # type: ignore[attr-defined]
    optim = types.ModuleType("mlx.optimizers")
    optim.__spec__ = types.SimpleNamespace(origin="p21-stub")  # type: ignore[attr-defined]

    class _Module:
        pass

    nn.Module = _Module  # type: ignore[attr-defined]
    mlx.core = core  # type: ignore[attr-defined]
    mlx.nn = nn  # type: ignore[attr-defined]
    mlx.optimizers = optim  # type: ignore[attr-defined]
    sys.modules["mlx"] = mlx
    sys.modules["mlx.core"] = core
    sys.modules["mlx.nn"] = nn
    sys.modules["mlx.optimizers"] = optim
