"""CPU test double for :class:`~ainerzero.v9.interfaces.WorldBrainAdapter`.

Composes the other doubles (geometry + encoder + scheduler) behind the single
observation entry point (r5 §3):

- ``step`` consumes **only** the ObservationPacket/v1.1 ``payload`` through the
  shared gate, and refuses a ``t_ticks`` that moves backwards inside an
  episode (time is the packet's own whitelist, never a frame counter);
- ``reset`` starts an episode from metadata that is itself free of world truth
  (the same forbidden-key scan);
- ``propose`` returns ``SkillProposal`` records with a TTL and a digest-pinned
  ``evidence_version``, whose ``params`` carry no world-side identity keys, and
  never writes the world.

Pure CPU: it only propagates an SE(2) belief with zero motion.  No model, no
I/O, no side effect.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..interfaces.errors import (
    ContractViolation,
    EnvelopeRejected,
    MalformedPayload,
    SnapshotRejected,
    TimeWhitelistRejected,
)
from ..interfaces.types import (
    BeliefSummary,
    PoseBelief,
    SkillProposal,
    evidence_digest,
    frozen_mapping,
)
from ..interfaces.validation import assert_no_forbidden_keys
from ..interfaces.world_brain import WorldBrainAdapter
from .geometry import FakeGeometryCore
from .perception import FakePerceptionEncoder

__all__ = ["FakeWorldBrain"]

_INITIAL_COVARIANCE = (
    (1e-4, 0.0, 0.0),
    (0.0, 1e-4, 0.0),
    (0.0, 0.0, 1e-5),
)
GRAVITY = (0.0, 0.0, -1.0)


class FakeWorldBrain(WorldBrainAdapter):
    """Payload-gated world-brain double: belief propagation + skill proposals."""

    def __init__(
        self,
        *,
        geometry: Any | None = None,
        encoder: Any | None = None,
        ttl_ticks: int = 120,
    ) -> None:
        if not isinstance(ttl_ticks, int) or isinstance(ttl_ticks, bool) or ttl_ticks < 1:
            raise ContractViolation(f"ttl_ticks must be an integer >= 1, got {ttl_ticks!r}")
        self._geometry = geometry if geometry is not None else FakeGeometryCore()
        self._encoder = encoder if encoder is not None else FakePerceptionEncoder()
        self._ttl_ticks = ttl_ticks
        self._belief = self._initial_belief()
        self._t_ticks = -1  # no observation consumed yet in this episode
        self._proposals = 0
        self._episodes = 0

    @staticmethod
    def _initial_belief() -> PoseBelief:
        return PoseBelief(
            group="SE2",
            mean=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            covariance=_INITIAL_COVARIANCE,
            gravity=GRAVITY,
            unobservable_dof=("global_translation", "global_yaw"),
        )

    # ---- episode boundary ------------------------------------------------- #

    def reset(self, meta: Mapping) -> None:
        """Start a new episode; metadata carrying world truth is refused."""
        if not isinstance(meta, Mapping):
            raise MalformedPayload(f"reset(meta) must be a mapping, got {type(meta).__name__}")
        version = meta.get("schema_version")
        if version is not None:
            text = version if isinstance(version, str) else ""
            if text.startswith("awz.world_snapshot"):
                raise SnapshotRejected(f"reset(meta) schema_version={version!r} is a world snapshot")
            raise EnvelopeRejected(f"reset(meta) schema_version={version!r} is a packet document, not metadata")
        if "envelope" in meta or "payload" in meta:
            raise EnvelopeRejected("reset(meta) takes episode metadata, not a packet document")
        assert_no_forbidden_keys(meta, origin="reset.meta")
        self._belief = self._initial_belief()
        self._t_ticks = -1
        self._episodes += 1

    # ---- the observation entry point ------------------------------------- #

    def step(self, payload: Mapping) -> BeliefSummary:
        """Consume one allowed payload; refuses envelopes, snapshots, backwards time."""
        validated = self.validate_payload(payload)
        
        # r1 打回修复：要求 t_ticks == t_prev + dt_ticks (D-021 §3.2)
        # 第一次调用时 (self._t_ticks == -1)，只要 t_ticks >= 0 即可
        if self._t_ticks != -1:
            expected_ticks = self._t_ticks + validated.dt_ticks
            if validated.t_ticks != expected_ticks:
                # r1 打回修复：要求 t_ticks == t_prev + dt_ticks (D-021 §3.2)
                # 同时包含 "backwards" 以兼容既有测试
                direction = "backwards" if validated.t_ticks < self._t_ticks else "forward jump"
                raise TimeWhitelistRejected(
                    f"t_ticks {direction} detected: expected {expected_ticks} (last {self._t_ticks} + "
                    f"dt {validated.dt_ticks}), got {validated.t_ticks}. "
                    "Packet loss must be explicitly marked in the contract if allowed."
                )
        elif validated.t_ticks < 0:
             raise TimeWhitelistRejected(f"initial t_ticks must be non-negative, got {validated.t_ticks}")

        # zero-motion propagation on the real clock: dt comes from the packet,
        # never from a frame index (r5 §4 式 3).
        self._belief = self._geometry.predict(
            self._belief, (0.0, 0.0, 0.0), validated.dt_ticks / validated.sim_hz
        )
        self._t_ticks = validated.t_ticks
        return BeliefSummary(
            t_ticks=validated.t_ticks,
            dt_ticks=validated.dt_ticks,
            dt_s=validated.dt_s,
            sim_hz=validated.sim_hz,
            belief=self._belief,
            encoder_version=self._encoder.describe().encoder_version,
            used_pose_sensor=validated.used_pose_sensor,
            updated_nodes=(),
            fallback_reason=None,
        )

    # ---- proposals -------------------------------------------------------- #

    def propose(self, goal: Mapping) -> tuple:
        """Return ``SkillProposal`` records for ``goal`` (never writes the world)."""
        if not isinstance(goal, Mapping):
            raise ContractViolation(f"propose(goal) must be a mapping, got {type(goal).__name__}")
        assert_no_forbidden_keys(goal, origin="goal")
        params = frozen_mapping(goal)
        assert_no_forbidden_keys(params, origin="proposal.params")
        basis = {"t_ticks": max(self._t_ticks, 0), "episodes": self._episodes}
        self._proposals += 1
        proposal = SkillProposal(
            proposal_id=f"prop-fake-{self._episodes}-{self._proposals}",
            actor="student",
            basis=basis,
            evidence_version=evidence_digest(basis),
            ability_id="abil-fake-goal",
            params=params,
            targets=(),
            action_budget={"max_actions": 1},
            ttl_ticks=self._ttl_ticks,
            expected_outcomes=("executed-within-ttl",),
        )
        return self.require_skill_proposal(proposal),

    # ---- read-only probes ------------------------------------------------- #

    @property
    def belief(self) -> PoseBelief:
        """Current belief (read-only probe; the interface exposes it via step)."""
        return self._belief

    @property
    def last_t_ticks(self) -> int:
        return self._t_ticks
