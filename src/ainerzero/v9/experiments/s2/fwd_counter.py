"""Forward-call counter and hard budget for S2 shared planners.

Counting unit
-------------
One single-element evaluation of any wrapped network function counts as 1.
A batched call of leading size ``B`` counts as ``B``. Encoder calls (including
goal encoding) are charged the same way; otherwise compute can be hidden inside
``encode``. Exceeding the hard budget raises ``ForwardBudgetExceeded``
immediately — never silent truncation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

__all__ = [
    "ForwardBudgetExceeded",
    "ForwardCounter",
    "batch_size_of",
    "canonical_bytes",
]


def canonical_bytes(obs: Any) -> bytes:
    """Extract deterministic byte representation for caching / hashing."""
    if isinstance(obs, np.ndarray):
        return np.ascontiguousarray(obs).tobytes()
    if isinstance(obs, (bytes, bytearray)):
        return bytes(obs)
    if isinstance(obs, str):
        return obs.encode("utf-8")
    if isinstance(obs, (list, tuple)):
        try:
            return np.ascontiguousarray(np.array(obs)).tobytes()
        except Exception:
            return repr(obs).encode("utf-8")
    return repr(obs).encode("utf-8")


class ForwardBudgetExceeded(RuntimeError):
    """Raised when a wrapped forward would push the counter past ``N_fwd``."""

    def __init__(self, name: str, requested: int, total: int, budget: int) -> None:
        self.name = name
        self.requested = requested
        self.total = total
        self.budget = budget
        super().__init__(
            f"forward budget exceeded on {name!r}: "
            f"need {requested}, already {total}, budget {budget}"
        )


def batch_size_of(*args: Any, **kwargs: Any) -> int:
    """Infer element count for one network call.

    Rule: the first ``ndarray`` argument with ``ndim >= 2`` contributes its
    leading axis as the batch size; otherwise the call is a single element (1).
    Keyword ``batch_size`` overrides when provided explicitly.
    """
    if "batch_size" in kwargs and kwargs["batch_size"] is not None:
        return int(kwargs["batch_size"])
    for value in args:
        if isinstance(value, np.ndarray) and value.ndim >= 2:
            return int(value.shape[0])
    for value in kwargs.values():
        if isinstance(value, np.ndarray) and value.ndim >= 2:
            return int(value.shape[0])
    return 1


class ForwardCounter:
    """Wrap callables and charge ``batch_elements × calls`` against a budget."""

    def __init__(self, budget: int | None = None) -> None:
        if budget is not None and budget < 0:
            raise ValueError("budget must be >= 0")
        self.budget = budget
        self._counts: dict[str, int] = {}
        self.total = 0
        self._goal_cache: Any = None
        self._goal_sha: str | None = None

    def begin_episode(self) -> None:
        """Begin a new episode: clear episode-scoped caches."""
        self._goal_cache = None
        self._goal_sha = None

    def reset(self) -> None:
        """Reset decision-level counters; preserves episode-level goal cache."""
        self._counts.clear()
        self.total = 0

    def goal_embedding(self, goal_obs: Any, encode: Callable[..., Any]) -> Any:
        """Retrieve cached goal embedding or compute and charge 1 to encode.

        Charges 1 on the first call within an episode; returns cached value thereafter.
        Raises ValueError if goal_obs changes within the same episode.
        """
        sha = hashlib.sha256(canonical_bytes(goal_obs)).hexdigest()
        if self._goal_sha is not None:
            if sha != self._goal_sha:
                raise ValueError(
                    f"goal observation changed within the same episode: "
                    f"cached {self._goal_sha[:16]}... vs new {sha[:16]}..."
                )
            return self._goal_cache

        # First call in this episode: compute and charge
        self._goal_sha = sha
        if hasattr(encode, "__wrapped__"):
            res = encode(goal_obs)
        else:
            self.charge("encode", 1)
            res = encode(goal_obs)
        self._goal_cache = res
        return res

    @property
    def by_name(self) -> dict[str, int]:
        return dict(self._counts)

    def snapshot(self) -> dict[str, Any]:
        return {
            "total": int(self.total),
            "by_name": dict(self._counts),
            "budget": self.budget,
        }

    def charge(self, name: str, n: int = 1) -> None:
        """Charge ``n`` units to ``name``; raise if budget would be exceeded."""
        if n < 0:
            raise ValueError("charge count must be >= 0")
        if n == 0:
            return
        if self.budget is not None and self.total + n > self.budget:
            raise ForwardBudgetExceeded(name, n, self.total, self.budget)
        self._counts[name] = self._counts.get(name, 0) + n
        self.total += n

    def wrap(self, name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Return a wrapper that charges before invoking ``fn``."""

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            # Prefer explicit batch_size kw; do not forward it to ``fn``.
            call_kwargs = dict(kwargs)
            batch_size = call_kwargs.pop("batch_size", None)
            n = batch_size_of(*args, batch_size=batch_size) if batch_size is not None else batch_size_of(*args, **kwargs)
            self.charge(name, n)
            return fn(*args, **call_kwargs)

        wrapped.__name__ = getattr(fn, "__name__", name)
        wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
        return wrapped

    def details(self) -> Mapping[str, int]:
        """Per-function breakdown for one decision (same as ``by_name``)."""
        return self.by_name
