"""Protocol, manifests, budgets and status codes for T4 teacher benchmarks.

Defines the approved teacher model manifest (T21/T22 exact SHA256 hashes),
the R20261016-T4 approval specifications, resource protection lines (32 GiB RSS),
and conservative budget caps (1800s cumulative, 600s per-run).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

# T4 Research Log Approval Constraints
T4_APPROVAL_SECTION = "R20261016-T4"
T4_APPROVAL_KEYWORD = "批准 T4"
T4_APPROVAL_TARGET = "ainerzero.V9.T4"

# T4 Budget & Resource Guard Constraints (from RESEARCH_LOG & T23 card)
T4_MAX_CUMULATIVE_WALL_SECONDS = 1800.0
T4_MAX_PER_RUN_WALL_SECONDS = 600.0
T4_MAX_RESIDENT_MODELS = 1
T4_MAX_PROCESS_RSS_GIB = 32.0
T4_MAX_PROCESS_RSS_BYTES = int(32.0 * (1024**3))

# T6 DA3 Research Log & Resource Guard Constraints (from T26 & T6 card)
# Canonical task ID for the DA3 teacher benchmark line. Per user decision (2026-10-28, E18),
# DA3 quota uses line-wide accounting across all tasks in the central RunStore (whatever the task field);
# sitecustomize task-ID rewriting has been retired.
T6_TASK_ID = "ainerzero.V9.T6"
T6_APPROVAL_SECTION = "R20261026-T6"
T6_APPROVAL_KEYWORD = "批准 T6"
T6_APPROVAL_TARGET = "ainerzero.V9.T6"
# V9.T51: 累计墙钟上限动态从已登记的 T28 提案派生（默认 1200.0）
from ainerzero.v9.teachers.t28_registration import (
    get_registered_cumulative_wall_cap_s,
)


def get_t6_max_cumulative_wall_seconds() -> float:
    """Return effective T6 max cumulative wall seconds (from registered T28 proposal, or default 1200.0)."""
    return get_registered_cumulative_wall_cap_s()


def __getattr__(name: str) -> Any:
    if name == "T6_MAX_CUMULATIVE_WALL_SECONDS":
        return get_registered_cumulative_wall_cap_s()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


T6_MAX_PER_RUN_WALL_SECONDS = 1200.0
T6_MAX_RESIDENT_MODELS = 1
T6_MAX_PROCESS_RSS_GIB = 8.0
T6_MAX_PROCESS_RSS_BYTES = int(8.0 * (1024**3))
T6_MAX_VIEWS = 64

# Defaults
DEFAULT_LOCK_PATH = Path("artifacts/locks/m0-worker.lock")
DEFAULT_STORE_PATH = Path("artifacts/v9/teachers/benchmark/runs.db")
DEFAULT_RESEARCH_LOG = Path("RESEARCH_LOG.md")
DEFAULT_WEIGHTS_ROOT = Path("artifacts/teachers/t4-approved")
DEFAULT_T6_WEIGHTS_ROOT = Path("artifacts/teachers/da3")

# Exit Codes
EXIT_COMPLETED = 0
EXIT_FAILED = 1
EXIT_REFUSED_RESOURCE = 2
EXIT_REFUSED_APPROVAL = 3
EXIT_LOCK_BUSY = 4
EXIT_REFUSED_BUDGET = 5


class BenchmarkRefusalError(RuntimeError):
    """Base error for all benchmark gate refusals."""

    exit_code: int = EXIT_FAILED

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class BenchmarkApprovalRefused(BenchmarkRefusalError):
    """RESEARCH_LOG approval line is missing, uncanonical, or tampered."""

    exit_code = EXIT_REFUSED_APPROVAL


class BenchmarkResourceRefused(BenchmarkRefusalError):
    """Resource guard line (e.g. RSS > 32 GiB) is violated."""

    exit_code = EXIT_REFUSED_RESOURCE


class BenchmarkBudgetRefused(BenchmarkRefusalError):
    """Cumulative (1800s) or per-run (600s) wall budget is exceeded."""

    exit_code = EXIT_REFUSED_BUDGET


class BenchmarkLockBusy(BenchmarkRefusalError):
    """Shared worker lock could not be acquired (non-blocking)."""

    exit_code = EXIT_LOCK_BUSY


@dataclass(frozen=True)
class ModelFileSpec:
    relative_path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class TeacherModelSpec:
    model_id: str
    repository: str
    revision: str
    license: str
    files: tuple[ModelFileSpec, ...]

    @property
    def total_bytes(self) -> int:
        return sum(f.bytes for f in self.files)


APPROVED_TEACHER_MODELS: dict[str, TeacherModelSpec] = {
    "vjepa": TeacherModelSpec(
        model_id="vjepa",
        repository="dgrauet/vjepa-2.1-vitl-mlx",
        revision="b0674736bad10eb16bd765942a9065e7e2ee9a54",
        license="mit",
        files=(
            ModelFileSpec(
                relative_path="README.md",
                bytes=1074,
                sha256="3424969988eab48453eafd1fbc4fadb1b1dff79ad89f44b819a845a8c1dd2529",
            ),
            ModelFileSpec(
                relative_path="config.json",
                bytes=861,
                sha256="36a174637ddd2976efbe3e166e2c54359afbe2f4cbff67573f71f0691634eb96",
            ),
            ModelFileSpec(
                relative_path="encoder.safetensors",
                bytes=1218752536,
                sha256="7a68c25e3515108f81a88c3157ab5aa41322e0b49faf135c35cca147130c8e19",
            ),
            ModelFileSpec(
                relative_path="predictor.safetensors",
                bytes=91908429,
                sha256="c601a96f4bdb852ade8c5334b0a8e1beaa7461b60566387ad7a134ee437c2bf7",
            ),
            ModelFileSpec(
                relative_path="split_model.json",
                bytes=944,
                sha256="8681855d8bf614758fec95dde10f017a1171ecc232130ae8a3de2f4a4df1a2c5",
            ),
        ),
    ),
    "depth-anything-v2": TeacherModelSpec(
        model_id="depth-anything-v2",
        repository="apple/coreml-depth-anything-v2-small",
        revision="cfef6f6f2a70783dedc0bfae40cecbc2052285d3",
        license="apache-2.0",
        files=(
            ModelFileSpec(
                relative_path="DepthAnythingV2SmallF16.mlpackage/Data/com.apple.CoreML/model.mlmodel",
                bytes=399433,
                sha256="44ac97a3efcfd52113183fb2862ff59cd0368e9ec2e30a90a54980dd11407042",
            ),
            ModelFileSpec(
                relative_path="DepthAnythingV2SmallF16.mlpackage/Data/com.apple.CoreML/weights/weight.bin",
                bytes=49419072,
                sha256="fa60d9b6a155734f59029ebb882fd54e549bfaee3539c1a9cbd2cbbab64a0fed",
            ),
            ModelFileSpec(
                relative_path="DepthAnythingV2SmallF16.mlpackage/Manifest.json",
                bytes=617,
                sha256="2883ae290c48fe916dc5ececac03a7d847fa277165a49ef5652fa1d2b9cb55f7",
            ),
            ModelFileSpec(
                relative_path="DepthAnythingV2SmallF32.mlpackage/Data/com.apple.CoreML/model.mlmodel",
                bytes=366829,
                sha256="dfd7fd461ab2544f4951e757a59d878d6af93b5544541ed534329d84e958f0c9",
            ),
            ModelFileSpec(
                relative_path="DepthAnythingV2SmallF32.mlpackage/Data/com.apple.CoreML/weights/weight.bin",
                bytes=98821504,
                sha256="6b02236f9b6c8c4694904f89c0fc84c3b6175cde43f9f918f77948708c36b58d",
            ),
            ModelFileSpec(
                relative_path="DepthAnythingV2SmallF32.mlpackage/Manifest.json",
                bytes=617,
                sha256="048f5f5fbc11cff5ee8ab21e3a97830b7e0aacab5404eff0b3ea198dd1a39336",
            ),
            ModelFileSpec(
                relative_path="README.md",
                bytes=3900,
                sha256="a3280768d250f8a0c38f1f60971284e9658bc000eeb897eab126e20bd7cdee46",
            ),
        ),
    ),
}

TOTAL_T4_FILES_COUNT = sum(len(m.files) for m in APPROVED_TEACHER_MODELS.values())
TOTAL_T4_BYTES = sum(m.total_bytes for m in APPROVED_TEACHER_MODELS.values())


APPROVED_DA3_MODELS: dict[str, TeacherModelSpec] = {
    "da3-small": TeacherModelSpec(
        model_id="da3-small",
        repository="depth-anything/DA3-SMALL",
        revision="3d835ec1a5802d64a8b8b15f817a1ab54809bfe4",
        license="apache-2.0",
        files=(
            ModelFileSpec(
                relative_path="config.json",
                bytes=1202,
                sha256="a486e29e82b7ab4a7d4cefc1ea4526cfe2ae438a572c8ca98917cfbcde7447d2",
            ),
            ModelFileSpec(
                relative_path="model.safetensors",
                bytes=137248940,
                sha256="364492e38a3a06d221ac75da7f6621ada3f2361cd24fde11ba79091e9f40efcf",
            ),
        ),
    ),
    "da3-base": TeacherModelSpec(
        model_id="da3-base",
        repository="depth-anything/DA3-BASE",
        revision="3d835ec1a5802d64a8b8b15f817a1ab54809bfe4",
        license="apache-2.0",
        files=(
            ModelFileSpec(
                relative_path="config.json",
                bytes=1205,
                sha256="5e34115ebc17bd2d8d43033c5f72e9446ac8833fd61d3fa160b7e67e0bb5b7b5",
            ),
            ModelFileSpec(
                relative_path="model.safetensors",
                bytes=541518028,
                sha256="e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5",
            ),
        ),
    ),
}

TOTAL_DA3_FILES_COUNT = sum(len(m.files) for m in APPROVED_DA3_MODELS.values())
TOTAL_DA3_BYTES = sum(m.total_bytes for m in APPROVED_DA3_MODELS.values())


@dataclass(frozen=True)
class DA3RunSpec:
    model: str
    wall_budget_seconds: float
    views: int
    research_log_path: Path
    store_path: Path
    lock_path: Path
    weights_root: Path
    statistical_protocol_path: Path | None = None
    request_id: str | None = None
    run_id: str | None = None
    coordinator_release: bool = False
    allow_model_execution: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": T6_TASK_ID,
            "model": self.model,
            "wall_budget_seconds": self.wall_budget_seconds,
            "views": self.views,
            "research_log_path": str(self.research_log_path),
            "store_path": str(self.store_path),
            "lock_path": str(self.lock_path),
            "weights_root": str(self.weights_root),
            "statistical_protocol_path": str(self.statistical_protocol_path)
            if self.statistical_protocol_path
            else None,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "coordinator_release": self.coordinator_release,
            "allow_model_execution": self.allow_model_execution,
        }


@dataclass(frozen=True)
class BenchmarkRunSpec:
    model: str
    wall_budget_seconds: float
    research_log_path: Path
    store_path: Path
    lock_path: Path
    weights_root: Path
    request_id: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "wall_budget_seconds": self.wall_budget_seconds,
            "research_log_path": str(self.research_log_path),
            "store_path": str(self.store_path),
            "lock_path": str(self.lock_path),
            "weights_root": str(self.weights_root),
            "request_id": self.request_id,
            "run_id": self.run_id,
        }
