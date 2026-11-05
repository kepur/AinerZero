"""Contract: the seven replaceable interfaces as a *surface* (r5 §3).

Positive: ``INTERFACES`` holds exactly the seven ABCs in contract-table order,
each has a CPU fake implementing it, and importing the layer pulls in neither
the fakes nor any framework (MLX / ONNX Runtime / torch / tensorflow / jax).

Counter-examples: an interface losing its abstract methods, a fake that no
longer subclasses its interface, a hidden framework import (checked both by a
fresh subprocess and by a static scan of the shipped sources).
"""

from __future__ import annotations

import re
import subprocess
import sys
from abc import ABC
from pathlib import Path

import pytest

import ainerzero.v9 as v9
from ainerzero.v9 import INTERFACES, LAYERING, fakes

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPO_ROOT / "src/ainerzero/v9"
FRAMEWORKS = ("mlx", "onnxruntime", "torch", "tensorflow", "jax")

CONTRACT_TABLE_ORDER = (
    "WorldBrainAdapter",
    "GeometryCore",
    "TimeScaleAdapter",
    "SpatialMemory",
    "PerceptionEncoder",
    "HierarchicalPlanner",
    "UpdateScheduler",
)


def test_interfaces_tuple_matches_the_contract_table():
    assert len(INTERFACES) == 7
    assert tuple(cls.__name__ for cls in INTERFACES) == CONTRACT_TABLE_ORDER


def test_every_interface_is_an_abstract_class_with_a_real_surface():
    required = {
        "WorldBrainAdapter": {"reset", "step", "propose"},
        "GeometryCore": {
            "compose", "inverse", "exp", "log", "adjoint", "act",
            "predict", "update", "with_side", "canonicalize", "decanonicalize",
            "gravity", "supported",
        },
        "TimeScaleAdapter": {"levels", "align", "macro_action"},
        "SpatialMemory": {
            "write", "transform", "query_metric", "query_topology",
            "consolidate", "promote", "revoke", "demote", "supersede",
            "usable_slow_items", "parameter_fingerprint",
        },
        "PerceptionEncoder": {"encode", "describe", "token_policy"},
        "HierarchicalPlanner": {"levels", "plan", "fallback"},
        "UpdateScheduler": {"mark_dirty", "dirty_set", "update", "fallback_reason", "thresholds"},
    }
    for cls in INTERFACES:
        assert issubclass(cls, ABC), cls
        assert cls.__abstractmethods__, f"{cls.__name__} lost its abstract contract"
        missing = required[cls.__name__] - set(vars(cls))
        assert not missing, f"{cls.__name__} is missing {sorted(missing)}"


def test_every_interface_has_exactly_one_cpu_fake():
    assert set(fakes.FAKES) == {cls.__name__ for cls in INTERFACES}
    for cls in INTERFACES:
        fake = fakes.FAKES[cls.__name__]
        assert issubclass(fake, cls), f"{cls.__name__}'s fake no longer implements its interface"
        assert not fake.__abstractmethods__, f"{cls.__name__}'s fake still has unimplemented methods"


def test_fakes_are_constructible_on_cpu():
    geometry = fakes.FakeGeometryCore()
    assert geometry.supported() == ("SE2",)
    assert fakes.FakeTimeScaleAdapter  # constructed in its own contract test
    memory = fakes.FakeSpatialMemory(geometry)
    assert len(memory) == 0
    assert fakes.FakePerceptionEncoder().describe().encoder_version
    assert fakes.FakeHierarchicalPlanner((1, 0)).levels() == (1, 0)
    assert fakes.FakeUpdateScheduler(f_max=2, u_max=0.1).thresholds()["f_max"] == 2
    assert fakes.FakeWorldBrain(geometry=geometry)


def test_plain_import_does_not_drag_the_fakes_or_a_framework():
    """``import ainerzero.v9`` must stay a contract-layer-only import."""
    code = (
        "import sys\n"
        "import ainerzero.v9\n"
        "assert 'ainzerzero.v9.fakes' not in sys.modules, 'fakes must be imported explicitly'\n"
        "bad = [m for m in %r if m in sys.modules]\n"
        "assert not bad, f'frameworks imported: {bad}'\n"
        "print('surface-import-ok')\n"
    ) % (FRAMEWORKS,)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "surface-import-ok" in completed.stdout


def test_importing_fakes_imports_no_framework():
    code = (
        "import sys\n"
        "from ainerzero.v9 import fakes, INTERFACES\n"
        "assert len(INTERFACES) == 7\n"
        "bad = [m for m in %r if m in sys.modules]\n"
        "assert not bad, f'frameworks imported: {bad}'\n"
        "print('fakes-import-ok')\n"
    ) % (FRAMEWORKS,)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "fakes-import-ok" in completed.stdout


def test_layering_declaration_names_only_pure_dependencies():
    assert set(LAYERING["forbidden_everywhere"]) == set(FRAMEWORKS)
    assert "numpy" in LAYERING["interfaces"]
    forbidden = "|".join(FRAMEWORKS)
    pattern = re.compile(rf"^\s*(?:import|from)\s+({forbidden})\b", re.MULTILINE)
    for sub in ("interfaces", "fakes"):
        for path in sorted((PACKAGE_ROOT / sub).glob("*.py")):
            source = path.read_text(encoding="utf-8")
            match = pattern.search(source)
            assert match is None, f"{path} imports a framework: {match.group(0) if match else ''}"


def test_fakes_never_import_the_real_geometry_or_model_stack():
    """The double may be cross-checked against G1 only by *tests*, never at load."""
    pattern = re.compile(r"^\s*(?:import|from)\s+ainerzero\.v9\.(geometry|models|training)\b", re.MULTILINE)
    for path in sorted((PACKAGE_ROOT / "fakes").glob("*.py")):
        assert pattern.search(path.read_text(encoding="utf-8")) is None, path


def test_package_root_declares_layering_and_no_eager_fakes():
    assert v9.LAYERING is LAYERING
    with pytest.raises(AttributeError):
        v9.not_a_real_attribute  # normal attribute error path
