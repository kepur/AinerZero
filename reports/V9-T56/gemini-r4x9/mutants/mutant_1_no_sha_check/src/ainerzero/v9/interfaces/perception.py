"""``PerceptionEncoder`` interface (ARCHITECTURE_V9 r5 §3, §8.6).

Contracts owned here:

- ``describe`` reports the encoder version, and an externally pretrained
  encoder must declare its source **and** its license; the capability note is
  derived automatically so a capability report cannot omit it;
- ``token_policy`` declares whether RLT stop-frame dedup runs, its frozen
  threshold ``tau``, and the token retention rate it actually achieved (式 10);
- ``encode`` accepts the ObservationPacket/v1.1 payload only, and resolves
  model-visible URIs / content digests strictly as of the packet's own
  ``t_ticks`` inside the registered namespaces.

The real RLT implementation is ainerzero.V9.T8 and the real asset resolver is
awz.V9.A3/B1 (which must be tested on the actual loading path).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from .types import EncodedObservation, EncoderDescriptor, TokenPolicy

__all__ = ["PerceptionEncoder"]


class PerceptionEncoder(ABC):
    """Replaceable perception front-end (symbolic / visual / distilled student)."""

    @abstractmethod
    def encode(self, payload: Mapping) -> EncodedObservation:
        """Encode one allowed payload; refuses envelopes, snapshots and forbidden keys."""

    @abstractmethod
    def describe(self) -> EncoderDescriptor:
        """Declare version, provenance and licence; external weights must be declared."""

    @abstractmethod
    def token_policy(self) -> TokenPolicy:
        """Declare the RLT switch, its frozen threshold and the achieved retention."""

    # ---- shared helpers for implementations ------------------------------- #

    @staticmethod
    def require_descriptor(value: Any) -> EncoderDescriptor:
        from .errors import ContractViolation

        if not isinstance(value, EncoderDescriptor):
            raise ContractViolation(f"describe() must return EncoderDescriptor, got {type(value).__name__}")
        if value.external_pretrained and not (value.source and value.license):
            raise ContractViolation("an externally pretrained encoder must declare source and license")
        return value

    @staticmethod
    def require_policy(value: Any) -> TokenPolicy:
        from .errors import ContractViolation

        if not isinstance(value, TokenPolicy):
            raise ContractViolation(f"token_policy() must return TokenPolicy, got {type(value).__name__}")
        return value
