"""Shared value types for the seven v9 replaceable interfaces (ARCHITECTURE_V9 r5 §3).

Design notes (all of them are contracts, not conveniences):

- **Frozen dataclasses only.**  Nothing here mutates in place, so a memory write
  or a belief update cannot smuggle a parameter change through a shared object.
- **Tagged coordinate arrays.**  ``canonicalize`` may only accept points, object
  vectors and map coordinates (r4 §4 / §3 GeometryCore row).  A bare ndarray is
  ambiguous (is it a point set, a pose matrix or an image?), so the interface
  requires an explicit tag; ambiguous input is refused instead of guessed.
- **Explicit gravity and explicit gauge.**  ``PoseBelief`` requires a non-zero
  gravity vector and an explicit declaration of unobservable degrees of freedom.
  There is no silent default for either.
- **Right perturbation only** (r5 §4 convention): ``X = mu Exp(xi_r)``.  A belief
  in a left frame must be converted through ``GeometryCore.with_side`` before it
  enters any other interface method.

Pure CPU: numpy only, no model / MLX / ORT import, no I/O.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

import numpy as np

__all__ = [
    "SIM_HZ",
    "TIME_WHITELIST_KEYS",
    "PARTITIONS",
    "WRITABLE_PARTITIONS",
    "UNOBSERVABLE_DOF",
    "UPDATE_SIGNAL_KINDS",
    "Points",
    "Vectors",
    "MapCoordinates",
    "as_points",
    "as_vectors",
    "as_map_coordinates",
    "PoseBelief",
    "ValidatedPayload",
    "BeliefSummary",
    "SkillProposal",
    "EncoderDescriptor",
    "RetentionReport",
    "TokenPolicy",
    "EncodedObservation",
    "Fragment",
    "QueryResult",
    "ConsolidationReport",
    "PromotionEvidence",
    "PROMOTION_EVIDENCE_SCHEMA_VERSIONS",
    "PROMOTION_CALIBRATION_METHODS",
    "KNOWLEDGE_ORIGIN_CATEGORIES",
    "EVIDENCE_DATA_ROLES",
    "EVIDENCE_BLOCK_UNITS",
    "DEFAULT_CONFORMAL_N_MIN",
    "LevelSpec",
    "LevelAlignment",
    "MacroAction",
    "LevelBudget",
    "PlanBudget",
    "Subgoal",
    "PlanLevel",
    "Plan",
    "FallbackRecord",
    "UpdateSignal",
    "UpdateResult",
    "evidence_digest",
    "frozen_mapping",
]

SIM_HZ = 120
"""The registered world clock.  ObservationPacket/v1.1 pins ``time.sim_hz`` to it."""

TIME_WHITELIST_KEYS = ("sim_hz", "t_ticks", "dt_ticks", "dt_s")
"""The only time fields a model may consume (§2 structure diagram, §3 WorldBrainAdapter)."""

PARTITIONS = ("train", "development", "final", "quarantine")
WRITABLE_PARTITIONS = ("train", "development")
"""Fail-closed write allowlist for episodic memory (``final`` is sealed, §3 SpatialMemory)."""

UNOBSERVABLE_DOF = ("global_translation", "global_yaw", "scale")
"""Gauge freedoms that must be declared, never estimated (§4 约定段: 规范与锚点)."""

UPDATE_SIGNAL_KINDS = ("observation_change", "executed_action", "belief_uncertainty")
"""The only three learning-side signal sources (§3 UpdateScheduler, §8.6 F2)."""

_GROUP_DOF = {"SE2": 3, "SE3": 6}
_GROUP_POSE = {"SE2": (3, 3), "SE3": (4, 4)}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


# --------------------------------------------------------------------------- #
# tagged coordinates (the only inputs canonicalize accepts)
# --------------------------------------------------------------------------- #


class Points(np.ndarray):
    """World / map frame point coordinates; the group action adds translation."""


class Vectors(np.ndarray):
    """Object vectors (directions, velocities); the group action rotates only."""


class MapCoordinates(np.ndarray):
    """Metric map-layer coordinates; carried with the map resolution metadata."""

    resolution_m: float = 1.0


def _float_array(value: Any, name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.ndim not in (1, 2):
        raise ValueError(f"{name} must have 1 or 2 dimensions, got ndim={array.ndim}")
    if array.shape[-1] not in (2, 3):
        raise ValueError(f"{name} last axis must be 2 or 3, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite")
    array.setflags(write=False)
    return array


def as_points(value: Any) -> Points:
    """Tag ``(..., 2|3)`` finite coordinates as points (translation applies)."""
    return _float_array(value, "points").view(Points)


def as_vectors(value: Any) -> Vectors:
    """Tag ``(..., 2|3)`` finite coordinates as object vectors (no translation)."""
    return _float_array(value, "vectors").view(Vectors)


def as_map_coordinates(value: Any, resolution_m: float) -> MapCoordinates:
    """Tag metric map coordinates and carry their resolution through the transform."""
    if not isinstance(resolution_m, (int, float)) or not math.isfinite(float(resolution_m)):
        raise ValueError("resolution_m must be a finite number")
    if float(resolution_m) <= 0:
        raise ValueError("resolution_m must be positive")
    tagged = _float_array(value, "map_coordinates").view(MapCoordinates)
    tagged.resolution_m = float(resolution_m)
    return tagged


# --------------------------------------------------------------------------- #
# beliefs
# --------------------------------------------------------------------------- #


def _validate_pose(matrix: Any, group: str, name: str) -> np.ndarray:
    shape = _GROUP_POSE[group]
    pose = np.array(matrix, dtype=float, copy=True)
    if pose.shape != shape:
        raise ValueError(f"{name} must have shape {shape} for {group}, got {pose.shape}")
    if not np.isfinite(pose).all():
        raise ValueError(f"{name} must be finite")
    rotation = pose[:-1, :-1]
    if not np.allclose(pose[-1], np.concatenate([np.zeros(shape[0] - 1), [1.0]]), atol=1e-12):
        raise ValueError(f"{name} last row must be [0 ... 0 1]")
    if not np.allclose(rotation.T @ rotation, np.eye(shape[0] - 1), atol=1e-9):
        raise ValueError(f"{name} rotation block must be orthonormal")
    if not math.isclose(float(np.linalg.det(rotation)), 1.0, abs_tol=1e-9):
        raise ValueError(f"{name} rotation block must be a proper rotation (det=+1)")
    pose.setflags(write=False)
    return pose


def _validate_covariance(value: Any, dof: int, name: str) -> np.ndarray:
    cov = np.array(value, dtype=float, copy=True)
    if cov.shape != (dof, dof):
        raise ValueError(f"{name} must have shape ({dof}, {dof}), got {cov.shape}")
    if not np.isfinite(cov).all():
        raise ValueError(f"{name} must be finite")
    if not np.allclose(cov, cov.T, atol=1e-12):
        raise ValueError(f"{name} must be symmetric")
    smallest = float(np.linalg.eigvalsh((cov + cov.T) / 2.0)[0])
    if smallest <= 0.0:
        raise ValueError(f"{name} must be positive definite (min eig={smallest!r})")
    cov.setflags(write=False)
    return cov


@dataclass(frozen=True)
class PoseBelief:
    """Tangent-space Gaussian pose belief with an explicit gravity axis and gauge.

    ``mean`` is the pose ``T_AB`` (r5 §4 convention: it maps coordinates of frame
    B into frame A, so ``T_AC = T_AB @ T_BC``).  ``covariance`` belongs to the
    **right** perturbation ``X = mean @ Exp(xi_r)``; a pure left world-frame
    change leaves it untouched (r5 §4 约定段).
    """

    group: str
    mean: np.ndarray
    covariance: np.ndarray
    gravity: np.ndarray
    unobservable_dof: tuple
    side: str = "right"
    anchor: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.group not in _GROUP_DOF:
            raise ValueError(f"unsupported group {self.group!r}; expected one of {sorted(_GROUP_DOF)}")
        if self.side not in ("right", "left"):
            raise ValueError(f"side must be 'right' or 'left', got {self.side!r}")
        object.__setattr__(self, "mean", _validate_pose(self.mean, self.group, "mean"))
        object.__setattr__(
            self, "covariance", _validate_covariance(self.covariance, _GROUP_DOF[self.group], "covariance")
        )
        gravity = np.array(self.gravity, dtype=float, copy=True)
        if gravity.shape != (3,):
            raise ValueError("gravity must be a 3-vector")
        if not np.isfinite(gravity).all() or float(np.linalg.norm(gravity)) == 0.0:
            raise ValueError("gravity must be finite and non-zero (gravity direction is explicit)")
        gravity.setflags(write=False)
        object.__setattr__(self, "gravity", gravity)
        if self.unobservable_dof is None or not isinstance(self.unobservable_dof, tuple):
            raise ValueError(
                "unobservable_dof must be an explicit tuple (use () when every degree of freedom is observable)"
            )
        unknown = [str(item) for item in self.unobservable_dof if item not in UNOBSERVABLE_DOF]
        if unknown:
            raise ValueError(f"unobservable_dof contains undeclared entries {unknown}; allowed={UNOBSERVABLE_DOF}")
        object.__setattr__(self, "unobservable_dof", tuple(self.unobservable_dof))
        if self.anchor is not None:
            object.__setattr__(self, "anchor", _validate_pose(self.anchor, self.group, "anchor"))

    @property
    def dof(self) -> int:
        return _GROUP_DOF[self.group]

    @property
    def up(self) -> np.ndarray:
        """Unit vector opposite to gravity (the canonicalisation rotation axis)."""
        return (-self.gravity / float(np.linalg.norm(self.gravity))).astype(float)

    def with_mean(self, mean: Any) -> "PoseBelief":
        """Return a belief with a new mean and the same gauge declaration."""
        return replace(self, mean=mean)


# --------------------------------------------------------------------------- #
# observation path
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ValidatedPayload:
    """Result of the ObservationPacket/v1.1 payload gate (only allowed fields)."""

    t_ticks: int
    dt_ticks: int
    dt_s: float
    sim_hz: int
    channel_kinds: tuple
    used_pose_sensor: bool
    raw: Mapping

    @property
    def time(self) -> Mapping[str, Any]:
        return {
            "sim_hz": self.sim_hz,
            "t_ticks": self.t_ticks,
            "dt_ticks": self.dt_ticks,
            "dt_s": self.dt_s,
        }


@dataclass(frozen=True)
class BeliefSummary:
    """What ``WorldBrainAdapter.step`` is allowed to expose about its belief."""

    t_ticks: int
    dt_ticks: int
    dt_s: float
    sim_hz: int
    belief: PoseBelief
    encoder_version: str
    used_pose_sensor: bool
    updated_nodes: tuple = ()
    fallback_reason: str | None = None


@dataclass(frozen=True)
class SkillProposal:
    """SkillProposal/v1 view (contract source: ``contracts/v9/skill_proposal.v1.schema.json``).

    Only the contract items owned by *this* card are enforced here: a TTL, an
    evidence version, a basis tick, and no world-side identity keys in ``params``.
    Full schema conformance stays with the B1 checker.
    """

    proposal_id: str
    actor: str
    basis: Mapping
    evidence_version: str
    ability_id: str
    params: Mapping
    targets: tuple
    action_budget: Mapping
    ttl_ticks: int
    expected_outcomes: tuple

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, str) or not re.match(r"^prop-[a-z0-9][a-z0-9-]{2,63}$", self.proposal_id):
            raise ValueError(f"proposal_id must match the skill_proposal.v1 pattern, got {self.proposal_id!r}")
        if not isinstance(self.ability_id, str) or not re.match(r"^abil-[a-z0-9][a-z0-9_.-]{2,63}$", self.ability_id):
            raise ValueError(f"ability_id must match the skill_proposal.v1 pattern, got {self.ability_id!r}")
        if not isinstance(self.ttl_ticks, int) or isinstance(self.ttl_ticks, bool) or self.ttl_ticks < 1:
            raise ValueError(f"ttl_ticks must be an integer >= 1, got {self.ttl_ticks!r}")
        if not isinstance(self.evidence_version, str) or not _HEX64.match(self.evidence_version):
            raise ValueError("evidence_version must be a 64-char lowercase hex digest")
        if not isinstance(self.basis, Mapping) or "t_ticks" not in self.basis:
            raise ValueError("basis must be a mapping containing t_ticks")
        if not isinstance(self.params, Mapping):
            raise ValueError("params must be a mapping")
        if not isinstance(self.expected_outcomes, (tuple, list)) or len(self.expected_outcomes) < 1:
            raise ValueError("expected_outcomes must contain at least one entry")
        object.__setattr__(self, "targets", tuple(self.targets))
        object.__setattr__(self, "expected_outcomes", tuple(self.expected_outcomes))
        object.__setattr__(self, "params", frozen_mapping(self.params))
        object.__setattr__(self, "basis", frozen_mapping(self.basis))
        object.__setattr__(self, "action_budget", frozen_mapping(self.action_budget))


# --------------------------------------------------------------------------- #
# perception
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EncoderDescriptor:
    """What ``PerceptionEncoder.describe`` must report; external weights must be declared."""

    encoder_version: str
    kind: str
    external_pretrained: bool
    source: str | None = None
    license: str | None = None

    def __post_init__(self) -> None:
        if not self.encoder_version or not isinstance(self.encoder_version, str):
            raise ValueError("encoder_version must be a non-empty string")
        if self.external_pretrained and not (self.source and self.license):
            raise ValueError(
                "an externally pretrained encoder must declare both its source and its license "
                "(ARCHITECTURE_V9 §3 PerceptionEncoder, §5 S5)"
            )
        object.__setattr__(
            self, "capability_note",
            (
                f"external_pretrained source={self.source} license={self.license} "
                "(not learned from scratch by this project)"
                if self.external_pretrained
                else "self_contained_fake_encoder (no external weights)"
            ),
        )


@dataclass(frozen=True)
class RetentionReport:
    """RLT stop-frame token accounting (§4 式 10); reported whenever RLT runs."""

    tokens_seen: int
    tokens_kept: int

    def __post_init__(self) -> None:
        if self.tokens_seen < 0 or self.tokens_kept < 0:
            raise ValueError("token counters must be non-negative")
        if self.tokens_kept > self.tokens_seen:
            raise ValueError("tokens_kept cannot exceed tokens_seen")

    @property
    def rate(self) -> float:
        if self.tokens_seen == 0:
            return 1.0
        return self.tokens_kept / self.tokens_seen


@dataclass(frozen=True)
class TokenPolicy:
    """``PerceptionEncoder.token_policy``: RLT switch, frozen threshold, retention."""

    rlt_enabled: bool
    threshold_tau: float | None
    retention: RetentionReport

    def __post_init__(self) -> None:
        if self.rlt_enabled:
            if self.threshold_tau is None or not math.isfinite(float(self.threshold_tau)):
                raise ValueError("an enabled RLT policy must register a finite threshold_tau")
            if float(self.threshold_tau) < 0:
                raise ValueError("threshold_tau must be non-negative")
        elif self.threshold_tau is not None:
            raise ValueError("threshold_tau must be None while RLT is disabled")
        object.__setattr__(self, "threshold_tau", None if self.threshold_tau is None else float(self.threshold_tau))


@dataclass(frozen=True)
class EncodedObservation:
    """Encoder output: token count plus the reference cut used for URI resolution."""

    encoder_version: str
    t_ticks: int
    tokens: int
    token_signatures: tuple
    resolved_references: tuple


# --------------------------------------------------------------------------- #
# memory
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Fragment:
    """One episodic fragment: place, time, partition, encoder version and content.

    ADR-0014 r3 §3 C3 adds the ARCH §2 provenance triple:

    - ``provenance_ref`` — where the entry came from (observation / action /
      teacher cache entry / discovery job id), a learning-side visible id only;
    - ``object_keys`` — which object slots the fragment speaks about;
    - ``action_keys`` — which executed action slots it covers.

    Old fragments stay readable and queryable (the three fields default to
    empty), but an entry that misses any of them **cannot be promoted to SLOW**
    (:meth:`promotion_gaps`).  Identifiers must not smuggle world-truth ids in
    (§8.6): tokens from the L2/L5/L8 leak rules are refused at construction.
    """

    fragment_id: str
    t_ticks: int
    place: str
    partition: str
    encoder_version: str
    metric: Any = None
    topology: tuple = ()
    provenance_ref: str = ""
    object_keys: tuple = ()
    action_keys: tuple = ()

    def __post_init__(self) -> None:
        if not self.fragment_id or not isinstance(self.fragment_id, str):
            raise ValueError("fragment_id must be a non-empty string")
        if not isinstance(self.t_ticks, int) or isinstance(self.t_ticks, bool) or self.t_ticks < 0:
            raise ValueError("t_ticks must be a non-negative integer")
        if not self.place or not isinstance(self.place, str):
            raise ValueError("place must be a non-empty string")
        if self.partition not in PARTITIONS:
            raise ValueError(f"partition must be one of {PARTITIONS}, got {self.partition!r}")
        if not self.encoder_version or not isinstance(self.encoder_version, str):
            raise ValueError("every memory entry must carry its encoder version")
        object.__setattr__(self, "topology", tuple(self.topology))
        if not isinstance(self.provenance_ref, str):
            raise ValueError("provenance_ref must be a string (empty when unknown)")
        if self.provenance_ref:
            _reject_world_truth_identifiers(self.provenance_ref, "provenance_ref")
        object.__setattr__(self, "object_keys", _identifier_tuple(self.object_keys, "object_keys"))
        object.__setattr__(self, "action_keys", _identifier_tuple(self.action_keys, "action_keys"))

    def promotion_gaps(self) -> tuple:
        """Fields ARCH §2 requires for SLOW that this fragment does not carry."""
        gaps: list[str] = []
        if not self.provenance_ref:
            gaps.append("provenance_ref")
        if not self.object_keys:
            gaps.append("object_keys")
        if not self.action_keys:
            gaps.append("action_keys")
        return tuple(gaps)

    def content_digest(self) -> str:
        """Digest of the stored content; ``PromotionEvidence.entry_digest`` must match it."""
        metric = None
        if self.metric is not None:
            array = np.asarray(self.metric, dtype=float).ravel()
            metric = [float(value) for value in array]
        return evidence_digest(
            {
                "action_keys": list(self.action_keys),
                "encoder_version": self.encoder_version,
                "fragment_id": self.fragment_id,
                "metric": metric,
                "object_keys": list(self.object_keys),
                "partition": self.partition,
                "place": self.place,
                "provenance_ref": self.provenance_ref,
                "t_ticks": self.t_ticks,
                "topology": list(self.topology),
            }
        )


def _identifier_tuple(value: Any, name: str) -> tuple:
    """Freeze an identifier sequence and refuse world-truth tokens (§8.6)."""
    if isinstance(value, str):
        raise ValueError(f"{name} must be a sequence of identifiers, not a bare string")
    try:
        items = tuple(value)
    except TypeError as error:
        raise ValueError(f"{name} must be a sequence of identifiers") from error
    for item in items:
        if not isinstance(item, str) or not item:
            raise ValueError(f"{name} entries must be non-empty strings")
        _reject_world_truth_identifiers(item, name)
    return items


def _world_truth_tokens() -> tuple:
    """Tokens taken from the L2/L5/L8 leak rules (single source, not a second table)."""
    from .validation import LEAK_RULES

    tokens: list[str] = []
    for rule in LEAK_RULES:
        if rule["id"] in ("L2", "L5", "L8"):
            tokens.extend(rule["forbidden_keys"])
    return tuple(sorted(set(tokens)))


def _reject_world_truth_identifiers(identifier: str, name: str) -> None:
    tokens = _world_truth_tokens()
    for segment in re.split(r"[/:.,|]", identifier.lower()):
        if not segment:
            continue
        if segment in tokens or segment.startswith(("gt_", "eval_")):
            raise ValueError(
                f"{name} carries a world-truth identifier segment {segment!r} in {identifier!r}; "
                "memory entries may only reference learning-side visible ids (§8.6)"
            )


@dataclass(frozen=True)
class QueryResult:
    """Version-checked query output; nothing is interpreted in a foreign latent space."""

    entries: tuple
    encoder_version: str
    excluded: tuple = ()


@dataclass(frozen=True)
class ConsolidationReport:
    budget: int
    scanned: int
    kept: int
    promoted_candidates: tuple = ()


PROMOTION_EVIDENCE_SCHEMA_VERSIONS = ("v1", "v2")
"""``v1`` objects stay constructible/readable; ``promote`` only accepts ``v2`` (fail-closed)."""

PROMOTION_CALIBRATION_METHODS = ("split_conformal", "aci_conformal", "fpca_split_conformal")
"""D3-4 允许的标定构造；ACI 只有长期平均覆盖，须在证据里自带实测覆盖率。"""

KNOWLEDGE_ORIGIN_CATEGORIES = ("sindy", "symbolic", "llm", "teacher", "human", "engineered")
"""§2 D3-7 知识起源类别（llm/teacher 只进 MID，但来源必须登记）。"""

EVIDENCE_DATA_ROLES = ("discovery", "calibration", "test")
"""D / C / T 三个数据角色；三者身份构造时强制两两不相交（§2 D3）。"""

EVIDENCE_BLOCK_UNITS = ("world_instance", "world_cluster")
"""证据单元只能是世界级 block/cluster（EGR 定理 2 (ii)）；轨迹步/回合不是独立单元。"""

DEFAULT_CONFORMAL_N_MIN = 10
"""``n_min`` 的接口层缺省值；实际值以 ``cmfl_registration.json`` 为准。"""

_CALIBRATION_REQUIRED_KEYS = ("method", "alpha_dom", "n_cal", "exchangeability_ref", "fpca_basis_ref")
_ERROR_CONTROL_REQUIRED_KEYS = (
    "elond_state_ref",
    "alpha_t",
    "attempts_N",
    "test_id_frozen_ref",
    "frozen_test_id",
    "block_unit",
)
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"evidence.{name} must be a non-empty string")
    return value


def _require_hex64(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError(f"evidence.{name} must be a 64-char lowercase sha256 digest")
    return value


def _require_open_unit(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"evidence.{name} must be a number in (0, 1)")
    number = float(value)
    if not math.isfinite(number) or not 0.0 < number < 1.0:
        raise ValueError(f"evidence.{name} must be a number in (0, 1), got {value!r}")
    return number


def _require_positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"evidence.{name} must be an integer >= 1, got {value!r}")
    return value


def _require_mapping(value: Any, name: str, required: tuple) -> Mapping:
    if not isinstance(value, Mapping):
        raise ValueError(f"evidence.{name} must be a mapping with {required}")
    missing = [key for key in required if key not in value]
    if missing:
        raise ValueError(f"evidence.{name} is missing {missing}; required={required}")
    return value


@dataclass(frozen=True)
class PromotionEvidence:
    """Independent evidence for a FAST/MID -> SLOW promotion (§1, §3 SpatialMemory).

    ADR-0014 r3 §3 C1 — ``schema_version="v2"`` carries everything the single-sided
    promotion gate needs to be auditable:

    - ``domain_ref`` — the D_valid reference the certificate is valid inside;
    - ``calibration`` — method, ``alpha_dom``, ``n_cal``, the exchangeability
      self-check reference and the FPCA basis data identity (S3: basis and
      calibration set must be disjoint);
    - ``error_control`` — e-LOND state reference, ``alpha_t``, attempt count ``N``,
      the pre-registration (贷前冻结) reference plus the ``test_id`` it froze, and
      the world-level block unit declaration;
    - ``counterexample_ref`` — the counter-example ledger entry (§2 D3-5);
    - ``origin_category`` — knowledge origin (§2 D3-7);
    - ``data_identity`` — D / C / T identities, forced pairwise disjoint;
    - ``regression_ref`` — 式 6 旧能力保持 reference;
    - ``entry_digest`` + ``encoder_version`` — what exactly is being promoted.

    ``v1`` stays constructible and readable (same three required fields as before,
    same ``validate_producer`` call), but :meth:`SpatialMemory.promote` refuses it.
    """

    kind: str
    report_ref: str
    producer: str
    test_id: str = ""
    schema_version: str = "v1"
    trusted_context: Any = None
    domain_ref: str = ""
    calibration: Any = None
    error_control: Any = None
    counterexample_ref: str = ""
    origin_category: str = ""
    data_identity: Any = None
    regression_ref: str = ""
    entry_digest: str = ""
    encoder_version: str = ""
    prior_version: str = ""

    def __post_init__(self) -> None:
        if self.kind != "independent_test":
            raise ValueError("a SLOW promotion needs kind='independent_test' evidence")
        if not self.report_ref or not isinstance(self.report_ref, str):
            raise ValueError("evidence.report_ref must name the independent test report")
        if not self.test_id or not isinstance(self.test_id, str):
            raise ValueError("evidence.test_id must name the independent test run")
        if self.schema_version not in PROMOTION_EVIDENCE_SCHEMA_VERSIONS:
            raise ValueError(
                f"evidence.schema_version must be one of {PROMOTION_EVIDENCE_SCHEMA_VERSIONS}, "
                f"got {self.schema_version!r}"
            )

        if self.schema_version == "v1":
            # v1 原样保留：只做登记表校验（teacher/LLM 仍被拒），但 promote 会拒绝 v1。
            from .validation import validate_producer

            validate_producer(self.producer)
            return

        # v2：唯一登记表权威 + SLOW 专用守卫（拦截 self + 强制可信上下文绑定）
        from .validation import require_independent_slow_producer

        require_independent_slow_producer(self.producer, trusted_context=self.trusted_context)
        self._validate_v2()

    # ---- v2 field checks -------------------------------------------------- #

    def _validate_v2(self) -> None:
        _require_text(self.domain_ref, "domain_ref")

        calibration = _require_mapping(self.calibration, "calibration", _CALIBRATION_REQUIRED_KEYS)
        method = calibration["method"]
        if method not in PROMOTION_CALIBRATION_METHODS:
            raise ValueError(
                f"evidence.calibration.method must be one of {PROMOTION_CALIBRATION_METHODS}, "
                f"got {method!r}"
            )
        alpha_dom = _require_open_unit(calibration["alpha_dom"], "calibration.alpha_dom")
        n_cal = _require_positive_int(calibration["n_cal"], "calibration.n_cal")
        n_min = _require_positive_int(
            calibration.get("n_min", DEFAULT_CONFORMAL_N_MIN), "calibration.n_min"
        )
        _require_text(calibration["exchangeability_ref"], "calibration.exchangeability_ref")
        fpca_basis_ref = _require_text(calibration["fpca_basis_ref"], "calibration.fpca_basis_ref")
        if method == "fpca_split_conformal" and fpca_basis_ref == "none":
            raise ValueError(
                "evidence.calibration.fpca_basis_ref must name the frozen FPCA basis data identity "
                "when method='fpca_split_conformal' (S3: basis and calibration set must be disjoint)"
            )
        if n_cal < n_min:
            raise ValueError(
                f"evidence.calibration.n_cal={n_cal} is below n_min={n_min}; the conformal "
                "certificate is empty, so promotion is refused (§2 D3-4)"
            )
        # 标准 split conformal 有限样本引理：k = ceil((1-alpha_dom)(n_cal+1)) 必须 <= n_cal
        rank = math.ceil((1.0 - alpha_dom) * (n_cal + 1))
        if rank > n_cal:
            raise ValueError(
                f"evidence.calibration: ceil((1-alpha_dom)(n_cal+1))={rank} > n_cal={n_cal}; "
                "the conformal certificate is empty, so promotion is refused (§2 D3-4)"
            )
        if method == "aci_conformal" and "empirical_coverage" not in calibration:
            raise ValueError(
                "evidence.calibration for aci_conformal must report empirical_coverage "
                "(ACI only guarantees long-run average coverage, §2 D3-4)"
            )

        error_control = _require_mapping(self.error_control, "error_control", _ERROR_CONTROL_REQUIRED_KEYS)
        _require_text(error_control["elond_state_ref"], "error_control.elond_state_ref")
        _require_open_unit(error_control["alpha_t"], "error_control.alpha_t")
        _require_positive_int(error_control["attempts_N"], "error_control.attempts_N")
        _require_text(error_control["test_id_frozen_ref"], "error_control.test_id_frozen_ref")
        frozen_test_id = error_control["frozen_test_id"]
        if frozen_test_id != self.test_id:
            raise ValueError(
                "evidence.error_control.frozen_test_id must equal evidence.test_id "
                f"({frozen_test_id!r} != {self.test_id!r}): the challenger, filter and test_id are "
                "frozen before any decision evidence is opened (EGR 定理 2 (i))"
            )
        block_unit = error_control["block_unit"]
        if block_unit not in EVIDENCE_BLOCK_UNITS:
            raise ValueError(
                f"evidence.error_control.block_unit must be one of {EVIDENCE_BLOCK_UNITS}, "
                f"got {block_unit!r}; trajectory steps and same-world episodes are not independent "
                "units (EGR 定理 2 (ii))"
            )

        _require_text(self.counterexample_ref, "counterexample_ref")
        if self.origin_category not in KNOWLEDGE_ORIGIN_CATEGORIES:
            raise ValueError(
                f"evidence.origin_category must be one of {KNOWLEDGE_ORIGIN_CATEGORIES}, "
                f"got {self.origin_category!r}"
            )

        data = _require_mapping(self.data_identity, "data_identity", EVIDENCE_DATA_ROLES)
        for role in EVIDENCE_DATA_ROLES:
            _require_text(data[role], f"data_identity.{role}")
        identities = [data[role] for role in EVIDENCE_DATA_ROLES]
        if len(set(identities)) != len(identities):
            raise ValueError(
                f"evidence.data_identity must be pairwise disjoint across D/C/T, got {identities}; "
                "the discovery, calibration and test sets may never overlap (§2 D3)"
            )

        _require_text(self.regression_ref, "regression_ref")
        _require_hex64(self.entry_digest, "entry_digest")
        _require_text(self.encoder_version, "encoder_version")
        # D3-9 重验条款要求「编码器、F_prior 或 GeometryCore 版本变化触发重验」，
        # 因此证据必须带上 F_prior/GeometryCore 的版本身份，否则该条款不可执行。
        _require_text(self.prior_version, "prior_version")

    # ---- probes ----------------------------------------------------------- #

    def is_v2(self) -> bool:
        return self.schema_version == "v2"


# --------------------------------------------------------------------------- #
# time scales
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LevelSpec:
    """One hierarchical level: stride in world-clock ticks plus its macro rule."""

    level: int
    stride_ticks: int
    macro_rule: str
    macro_dim: int
    action_classes: tuple = ()

    def __post_init__(self) -> None:
        if not isinstance(self.level, int) or isinstance(self.level, bool) or self.level < 0:
            raise ValueError("level must be a non-negative integer")
        if not isinstance(self.stride_ticks, int) or isinstance(self.stride_ticks, bool) or self.stride_ticks < 1:
            raise ValueError("stride_ticks must be an integer >= 1")
        if self.macro_dim < 1:
            raise ValueError("macro_dim must be >= 1")
        object.__setattr__(self, "action_classes", tuple(self.action_classes))


@dataclass(frozen=True)
class LevelAlignment:
    """Explicit-dt alignment of one level against the 120 Hz world clock."""

    level: int
    stride_ticks: int
    t_ticks: int
    dt_ticks: int
    aligned_ticks: int
    step_index: int
    delta_s: float


@dataclass(frozen=True)
class MacroAction:
    """Aggregated macro action ``a^(k) = A_k(a^(k-1)_{t:t+s_k})`` plus its real duration."""

    level: int
    rule: str
    values: np.ndarray
    delta_ticks: int
    delta_s: float


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LevelBudget:
    """Per-level planning budget; every level must receive one explicitly."""

    level: int
    max_expansions: int

    def __post_init__(self) -> None:
        if not isinstance(self.max_expansions, int) or isinstance(self.max_expansions, bool):
            raise ValueError("max_expansions must be an integer")
        if self.max_expansions < 0:
            raise ValueError("max_expansions must be non-negative")


@dataclass(frozen=True)
class PlanBudget:
    """Budget container; a level that is not listed has no budget and cannot be planned."""

    levels: tuple

    def __post_init__(self) -> None:
        entries = tuple(self.levels)
        seen: dict[int, LevelBudget] = {}
        for entry in entries:
            if not isinstance(entry, LevelBudget):
                raise ValueError("PlanBudget only accepts LevelBudget entries")
            if entry.level in seen:
                raise ValueError(f"duplicate budget for level {entry.level}")
            seen[entry.level] = entry
        object.__setattr__(self, "levels", entries)
        object.__setattr__(self, "_by_level", seen)

    def for_level(self, level: int) -> LevelBudget:
        if level not in self._by_level:
            raise ValueError(f"no budget registered for level {level}")
        return self._by_level[level]


@dataclass(frozen=True)
class Subgoal:
    level: int
    target: Mapping
    cost: int


@dataclass(frozen=True)
class PlanLevel:
    level: int
    budget: LevelBudget
    expansions: int
    subgoals: tuple
    exhausted: bool
    fallback_reason: str | None = None


@dataclass(frozen=True)
class Plan:
    goal: Mapping
    levels: tuple
    fallback_used: bool
    fallback_reason: str | None


@dataclass(frozen=True)
class FallbackRecord:
    level: int
    reason: str
    expansions: int


# --------------------------------------------------------------------------- #
# learning-side update scheduling
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UpdateSignal:
    """Learning-side dirty signal; the *only* allowed sources are in ``kind``.

    The payload is scanned for world-side keys (events, world entity ids,
    hidden contacts, world dirty/fallback flags, truth graphs) and refused
    (ARCHITECTURE_V9 r5 §3 UpdateScheduler, §8.6).
    """

    kind: str
    node: str
    source_t_ticks: int
    detail: Mapping = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in UPDATE_SIGNAL_KINDS:
            raise ValueError(
                f"signal kind must be one of {UPDATE_SIGNAL_KINDS} (learning-side sources only), got {self.kind!r}"
            )
        if not self.node or not isinstance(self.node, str):
            raise ValueError("signal.node must name a belief node")
        if not isinstance(self.source_t_ticks, int) or isinstance(self.source_t_ticks, bool):
            raise ValueError("signal.source_t_ticks must be an integer tick")
        if not isinstance(self.detail, Mapping):
            raise ValueError("signal.detail must be a mapping")
        object.__setattr__(self, "detail", frozen_mapping(self.detail))


@dataclass(frozen=True)
class UpdateResult:
    belief: Mapping
    nodes_updated: tuple
    mode: str
    fallback_reason: str | None
    expansions: int


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def frozen_mapping(value: Mapping) -> Mapping:
    """Read-only view: nested mappings and lists are frozen one level deeper."""
    frozen: dict[Any, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            frozen[key] = frozen_mapping(item)
        elif isinstance(item, (list, tuple)):
            frozen[key] = tuple(
                frozen_mapping(sub) if isinstance(sub, Mapping) else sub for sub in item
            )
        else:
            frozen[key] = item
    return _FrozenDict(frozen)


class _FrozenDict(Mapping):
    __slots__ = ("_data",)

    def __init__(self, data: dict) -> None:
        object.__setattr__(self, "_data", data)

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __setattr__(self, name, value):  # pragma: no cover - guarded
        raise AttributeError("frozen mappings are immutable")

    def __hash__(self):
        return hash(frozenset(self._data.keys()))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return repr(self._data)


def evidence_digest(value: Any) -> str:
    """Deterministic digest of a proposal basis (JCS-style, sorted keys, UTF-8).

    This is the interface-level digest used for ``evidence_version``; the full
    RFC 8785 checker stays with the B1 contract card.  Frozen mappings, tuples
    and other JSON-shaped containers are normalised first so that a digest is
    recomputable from a frozen ``SkillProposal.basis``.
    """
    payload = json.dumps(
        _jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def sequence_of_floats(value: Sequence[float], size: int, name: str) -> np.ndarray:
    array = np.array(list(value), dtype=float)
    if array.shape != (size,):
        raise ValueError(f"{name} must have {size} entries, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite")
    return array
