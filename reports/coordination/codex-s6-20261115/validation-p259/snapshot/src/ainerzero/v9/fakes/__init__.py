"""CPU test doubles for the seven v9 interfaces (``fakes`` layer).

Every fake implements exactly one interface, depends only on ``interfaces`` +
numpy, and is written to be *breakable*: each contract in
``tests/v9/contracts/`` has a counter-example, and the sabotage harness in
``reports/V9-B2/r1-mimo-5fb1-20261020/run_mutations.py`` shows that mutating a
fake makes the matching test go red.

These are **test doubles**, not research implementations: no model, no
training, no download, no MLX/ORT/torch import, no I/O at call time.
"""

from __future__ import annotations

from .geometry import FakeGeometryCore
from .perception import FakePerceptionEncoder
from .planner import FakeHierarchicalPlanner
from .scheduler import FakeUpdateScheduler
from .spatial_memory import FakeSpatialMemory
from .timescale import FakeTimeScaleAdapter
from .world_brain import FakeWorldBrain

FAKES: dict = {
    "WorldBrainAdapter": FakeWorldBrain,
    "GeometryCore": FakeGeometryCore,
    "TimeScaleAdapter": FakeTimeScaleAdapter,
    "SpatialMemory": FakeSpatialMemory,
    "PerceptionEncoder": FakePerceptionEncoder,
    "HierarchicalPlanner": FakeHierarchicalPlanner,
    "UpdateScheduler": FakeUpdateScheduler,
}
"""Interface name -> its CPU test double (keys mirror ``INTERFACES``)."""

__all__ = [
    "FAKES",
    "FakeWorldBrain",
    "FakeGeometryCore",
    "FakeTimeScaleAdapter",
    "FakeSpatialMemory",
    "FakePerceptionEncoder",
    "FakeHierarchicalPlanner",
    "FakeUpdateScheduler",
]
