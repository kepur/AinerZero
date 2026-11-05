"""Machine-readable error hierarchy for the seven v9 replaceable interfaces.

Every rejection carries a stable ``code`` so contract tests can assert on the
*reason* rather than on message text.  Codes are part of the interface contract
(ARCHITECTURE_V9 r5 §3); implementations must raise these instead of returning a
sentinel, so that a silent acceptance cannot be mistaken for a valid input.

Pure CPU: no model, MLX/ORT import, no network, no side effect.
"""

from __future__ import annotations


class V9InterfaceError(Exception):
    """Base class for every v9 interface rejection."""

    code = "v9_interface_error"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}" if detail else self.code)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}(code={self.code!r}, detail={self.detail!r})"


class ObservationRejected(V9InterfaceError):
    """Base class for everything refused on the observation path."""

    code = "observation_rejected"


class EnvelopeRejected(ObservationRejected):
    """The caller passed the whole ObservationPacket (envelope level) instead of ``payload``."""

    code = "envelope_rejected"


class SnapshotRejected(ObservationRejected):
    """A WorldSnapshot / world-side document was handed to the student interface."""

    code = "snapshot_rejected"


class TruthFieldRejected(ObservationRejected):
    """A forbidden truth / identity / randomness / world-metadata key was found."""

    code = "truth_field_rejected"


class FutureFieldRejected(ObservationRejected):
    """A future-information key (``future_*`` / ``next_*`` / ``predicted_*``) was found."""

    code = "future_field_rejected"


class TimeWhitelistRejected(ObservationRejected):
    """``payload.time`` is missing, has extra keys, or is inconsistent with the clock."""

    code = "time_whitelist_rejected"


class ReferenceRejected(ObservationRejected):
    """A model-visible URI / content digest is outside the allowed namespace or time cut."""

    code = "reference_rejected"


class MalformedPayload(ObservationRejected):
    """The payload is not a mapping or misses required ObservationPacket/v1.1 fields."""

    code = "malformed_payload"


class ContractViolation(V9InterfaceError):
    """Base class for behaviour contracts (budgets, evidence, versions, signals)."""

    code = "contract_violation"


class UnsupportedInput(ContractViolation):
    """An input type the interface explicitly refuses (e.g. raw RGB for canonicalize)."""

    code = "unsupported_input"


class BudgetExhausted(ContractViolation):
    """A per-level planning budget was consumed before the level finished."""

    code = "budget_exhausted"


class EncoderVersionMismatch(ContractViolation):
    """Memory would have to be interpreted in a latent space it was not written in."""

    code = "encoder_version_mismatch"


class PartitionWriteRejected(ContractViolation):
    """Writing into a sealed partition (``final``) or an unknown partition."""

    code = "partition_write_rejected"


class EvidenceRequired(ContractViolation):
    """A promotion (or claim) lacks the independent evidence the contract requires."""

    code = "evidence_required"


class SignalRejected(ContractViolation):
    """An update-scheduling signal came from outside the learning-side information boundary."""

    code = "signal_rejected"


class SingularMeasurementNoise(ContractViolation):
    """A measurement with singular (e.g. exactly zero) noise must not be fused (§4.7 C1)."""

    code = "singular_measurement_noise"
