"""CPU test double for :class:`~ainerzero.v9.interfaces.PerceptionEncoder`.

Symbolic stand-in front-end (r5 §3, §8.6):

- ``encode`` consumes **only** an ObservationPacket/v1.1 payload through the
  shared gate (envelope / snapshot / forbidden keys / time whitelist refused),
  and resolves every model-visible URI strictly as of the packet's own
  ``t_ticks`` inside the registered namespaces ``obs``/``sensor``/``derived``;
- ``describe`` reports version + provenance; an externally pretrained encoder
  must declare ``source`` **and** ``license`` (the capability note is derived,
  so a capability report cannot omit it);
- ``token_policy`` carries the RLT switch, its frozen ``tau`` and the retention
  it actually achieved: token accounting accumulates across ``encode`` calls,
  and with RLT enabled a repeated stop-frame signature is *seen* but not
  *kept* (式 10), so the retention rate drops below 1.0.

No real tokeniser, no weights, no download: this double counts one token per
channel / resolved reference.  The real RLT implementation is ainerzero.V9.T8.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

from ..interfaces.errors import ContractViolation, ReferenceRejected
from ..interfaces.perception import PerceptionEncoder
from ..interfaces.types import (
    EncodedObservation,
    EncoderDescriptor,
    RetentionReport,
    TokenPolicy,
)
from ..interfaces.validation import resolve_reference, validate_observation_payload

__all__ = ["FakePerceptionEncoder", "REFERENCE_CHANNEL_KEYS"]

REFERENCE_CHANNEL_KEYS: tuple = ("uri", "asset_uri", "content_uri")
"""Channel keys that carry a model-visible reference this double resolves."""


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _collect_references(payload: Mapping) -> list[str]:
    references: list[str] = []
    channels = payload["observation"]["channels"]
    for channel in channels:
        if not isinstance(channel, Mapping):
            continue
        for key in REFERENCE_CHANNEL_KEYS:
            value = channel.get(key)
            if value is not None:
                references.append(value)
        image = channel.get("image")
        if isinstance(image, Mapping):
            for key in REFERENCE_CHANNEL_KEYS:
                value = image.get(key)
                if value is not None:
                    references.append(value)
    return references


class FakePerceptionEncoder(PerceptionEncoder):
    """Declared-provenance, RLT-accounting CPU double for the perception cut."""

    def __init__(
        self,
        *,
        encoder_version: str = "fake-encoder-v1",
        kind: str = "symbolic",
        external_pretrained: bool = False,
        source: str | None = None,
        license: str | None = None,
        rlt_enabled: bool = False,
        threshold_tau: float | None = None,
    ) -> None:
        if rlt_enabled:
            if threshold_tau is None or isinstance(threshold_tau, bool):
                raise ContractViolation("an enabled RLT policy must register a threshold_tau")
            if not math.isfinite(float(threshold_tau)) or float(threshold_tau) < 0:
                raise ContractViolation(f"threshold_tau must be finite and non-negative, got {threshold_tau!r}")
        elif threshold_tau is not None:
            raise ContractViolation("threshold_tau must be None while RLT is disabled")
        self._descriptor = EncoderDescriptor(
            encoder_version=encoder_version,
            kind=kind,
            external_pretrained=external_pretrained,
            source=source,
            license=license,
        )
        self._rlt_enabled = bool(rlt_enabled)
        self._threshold_tau = None if threshold_tau is None else float(threshold_tau)
        self._tokens_seen = 0
        self._tokens_kept = 0
        self._seen_signatures: set[str] = set()

    # ---- declarations ----------------------------------------------------- #

    def describe(self) -> EncoderDescriptor:
        return self.require_descriptor(self._descriptor)

    def token_policy(self) -> TokenPolicy:
        return self.require_policy(
            TokenPolicy(
                rlt_enabled=self._rlt_enabled,
                threshold_tau=self._threshold_tau,
                retention=RetentionReport(tokens_seen=self._tokens_seen, tokens_kept=self._tokens_kept),
            )
        )

    # ---- encoding --------------------------------------------------------- #

    def encode(self, payload: Mapping) -> EncodedObservation:
        """Gate + reference resolution + RLT token accounting for one payload."""
        validated = validate_observation_payload(payload)
        resolved = tuple(
            resolve_reference(reference, as_of_t_ticks=validated.t_ticks)
            for reference in _collect_references(validated.raw)
        )
        signatures: list[str] = []
        for channel in validated.raw["observation"]["channels"]:
            signatures.append(_digest({"channel": channel}))
        signatures.extend(_digest({"reference": reference}) for reference in resolved)
        kept = 0
        for signature in signatures:
            if not self._rlt_enabled or signature not in self._seen_signatures:
                kept += 1
            self._seen_signatures.add(signature)
        self._tokens_seen += len(signatures)
        self._tokens_kept += kept
        return EncodedObservation(
            encoder_version=self._descriptor.encoder_version,
            t_ticks=validated.t_ticks,
            tokens=len(signatures),
            token_signatures=tuple(signatures),
            resolved_references=resolved,
        )

    # ---- probes ----------------------------------------------------------- #

    @property
    def retention(self) -> RetentionReport:
        """Cumulative RLT accounting across ``encode`` calls (式 10 input)."""
        return RetentionReport(tokens_seen=self._tokens_seen, tokens_kept=self._tokens_kept)

    @staticmethod
    def require_resolved(value: EncodedObservation) -> EncodedObservation:
        """Every returned reference must already have passed the namespace cut."""
        if not isinstance(value, EncodedObservation):
            raise ContractViolation(f"encode() must return EncodedObservation, got {type(value).__name__}")
        for reference in value.resolved_references:
            if not isinstance(reference, str) or not reference:
                raise ReferenceRejected(f"resolved reference {reference!r} is not a non-empty string")
        return value
