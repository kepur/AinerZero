"""S4 phase 2 evaluation workers compile MLX CPU kernels in a directory of their own (probe p1,
2026-11-11: workers compiling the same kernel into the shared cache collided). Native: runs MLX in
fresh processes, because MLX fixes its kernel-cache directory at the first compilation of a process."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mlx.core")
pytestmark = pytest.mark.native_mlx

SRC = Path(__file__).resolve().parents[3] / "src"

CHILD = r"""
import json, sys, os
sys.path.insert(0, {src!r})
from ainerzero.v9.experiments.s4 import worker_p2 as WK
before = os.environ.get("TMPDIR")
d = WK.private_compile_dir()
import mlx.core as mx, mlx.nn as nn
mx.set_default_device(mx.cpu)
mx.eval(nn.relu(mx.ones(({k}, 1, 7)) - mx.ones((1, 3, 7))))       # a broadcast pattern no cache holds yet
libs = [str(p) for p in d.rglob("*.so")] + [str(p) for p in d.rglob("*.dylib")]
print(json.dumps({{"dir": str(d), "pid": os.getpid(), "before": before, "libs": libs}}))
"""


def _child(tmp_path, k):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "TMPDIR": str(tmp_path)}
    r = subprocess.run([sys.executable, "-I", "-c", CHILD.format(src=str(SRC), k=k)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_each_worker_compiles_into_its_own_directory(tmp_path) -> None:
    a, b = _child(tmp_path, 11), _child(tmp_path, 13)
    for r in (a, b):
        assert r["dir"].startswith(str(tmp_path)) and r["dir"].endswith(f"ainerzero-mlx-cpu/{r['pid']}")
        assert r["libs"] and all(lib.startswith(r["dir"]) for lib in r["libs"])   # MLX honoured the new directory
    assert a["dir"] != b["dir"]


def test_init_sets_the_directory_before_anything_else(monkeypatch) -> None:
    from ainerzero.v9.experiments.s4 import worker_p2 as WK

    calls = []
    monkeypatch.setattr(WK, "private_compile_dir", lambda: calls.append("dir"))
    monkeypatch.setattr(WK, "build_models", lambda w: (calls.append("models"), ({}, {}, {}))[1])
    WK.init({})
    assert calls == ["dir", "models"]
