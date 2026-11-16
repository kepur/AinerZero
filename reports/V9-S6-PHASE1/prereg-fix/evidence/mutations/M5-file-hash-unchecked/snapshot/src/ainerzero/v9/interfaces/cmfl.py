"""CMFL 承载结构（ADR-0014 r3 §3 C7）：参数信念与 MSG 路由记录。

为什么要另立承载，而不是复用 ``UpdateScheduler`` 的 ``belief`` Mapping（R1 证据）：

- ``fakes/scheduler.py:132-144`` 的全量回退对 ``belief`` 的**所有键**执行
  ``updated[node] = belief[node] + 1``，放进去的 ``ParamBelief`` 会被当作标量相加；
- ``interfaces/scheduler.py:66-76`` 的 ``require_graph`` 要求值是**邻居序列**；
- ``BeliefSummary.belief`` 是 ``PoseBelief``（``types.py``），没有参数维度。

因此本模块给出三个**独立**结构，``UpdateScheduler`` / ``BeliefSummary`` /
``RunStore`` 的公共契约零改动：

- :class:`ParamBelief` —— φ 后验（均值、协方差、无量纲尺度、更新时刻），冻结；
- :class:`ParamBeliefStore` —— 学习侧容器，**只**由 MSG ``PARAMETRIC`` 分支写、
  由式 8 ``F_prior(…; φ̂)`` 读；它刻意**不是** ``Mapping``，避免被当成节点映射；
- :class:`MSGRouteRecord` / :class:`MSGRouteLog` —— 每次路由必产出一条记录，
  汇总写 ``msg_routes.json``（8 个路由码全在，``COVARIANCE_INCONSISTENT`` 单独计类）。

Pure CPU: numpy + hashlib + json only; no model, no network, no I/O at import.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .errors import ContractViolation, UnsupportedInput

__all__ = [
    "ROUTE_CODES",
    "MSG_ROUTE_ORDER",
    "NIS_ROUTE_CODES",
    "PARAMETRIC_ROUTE_CODE",
    "ParamBelief",
    "ParamBeliefStore",
    "MSGRouteRecord",
    "MSGRouteLog",
]

#: ADR-0014 §2 D1 的 8 个路由码（含 M4 拆出的下尾 ``COVARIANCE_INCONSISTENT``）。
ROUTE_CODES: tuple = (
    "ABSTAIN",
    "OUT_OF_DOMAIN",
    "NUMERICAL",
    "COVARIANCE_INCONSISTENT",
    "SUFFICIENT",
    "PARAMETRIC",
    "UNIDENTIFIABLE",
    "STRUCTURAL",
)

#: 判定次序（首条命中即停）：1 ABSTAIN → 2 OUT_OF_DOMAIN → 3 NUMERICAL →
#: 4a COVARIANCE_INCONSISTENT → 4b SUFFICIENT → 5 PARAMETRIC → 6 UNIDENTIFIABLE → 7 STRUCTURAL。
MSG_ROUTE_ORDER: tuple = ROUTE_CODES

#: 以 NIS 统计量为判据的两个路由（4a/4b），必须带统计量与自由度。
NIS_ROUTE_CODES: tuple = ("COVARIANCE_INCONSISTENT", "SUFFICIENT")

#: 唯一允许写 :class:`ParamBeliefStore` 的路由分支（§2 D1 第 5 条）。
PARAMETRIC_ROUTE_CODE = "PARAMETRIC"

_HEX64 = re.compile(r"[0-9a-f]{64}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _hex64(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise UnsupportedInput(f"{name} must be a 64-char lowercase sha256 digest")
    return value


@dataclass(frozen=True)
class ParamBelief:
    """φ 后验：``mean``/``cov`` 在**无量纲化参数**坐标上，``dimensionless_scale`` 是尺度。

    ``dimensionless_scale`` 必须显式给出，因为 §2 D1 第 6 条的 ``λ_min(I_φ) < τ_id``
    只对按先验尺度无量纲化后的 φ 有意义；缺尺度就无法判断可辨识性。
    """

    mean: tuple
    cov: tuple
    dimensionless_scale: tuple
    updated_at_ticks: int

    def __post_init__(self) -> None:
        mean = np.asarray(self.mean, dtype=float).ravel()
        if mean.size < 1:
            raise UnsupportedInput("ParamBelief.mean must have at least one entry")
        if not np.isfinite(mean).all():
            raise UnsupportedInput("ParamBelief.mean must be finite")
        cov = np.asarray(self.cov, dtype=float)
        if cov.shape != (mean.size, mean.size):
            raise UnsupportedInput(
                f"ParamBelief.cov must be {mean.size}x{mean.size}, got {cov.shape}"
            )
        if not np.isfinite(cov).all():
            raise UnsupportedInput("ParamBelief.cov must be finite")
        scale = float(np.max(np.abs(cov))) if cov.size else 0.0
        tolerance = 1e-9 * max(scale, 1.0)
        if not np.allclose(cov, cov.T, atol=tolerance, rtol=0.0):
            raise UnsupportedInput("ParamBelief.cov must be symmetric")
        smallest = float(np.min(np.linalg.eigvalsh((cov + cov.T) / 2.0)))
        if smallest < -tolerance:
            raise UnsupportedInput(
                f"ParamBelief.cov must be positive semi-definite, min eigenvalue {smallest!r}"
            )
        scale_vector = np.asarray(self.dimensionless_scale, dtype=float).ravel()
        if scale_vector.shape != mean.shape:
            raise UnsupportedInput(
                f"ParamBelief.dimensionless_scale must have {mean.size} entries, got {scale_vector.shape}"
            )
        if not np.isfinite(scale_vector).all() or not (scale_vector > 0).all():
            raise UnsupportedInput("ParamBelief.dimensionless_scale entries must be finite and > 0")
        if not _is_int(self.updated_at_ticks) or self.updated_at_ticks < 0:
            raise UnsupportedInput("ParamBelief.updated_at_ticks must be a non-negative integer")
        object.__setattr__(self, "mean", tuple(float(value) for value in mean))
        object.__setattr__(self, "cov", tuple(tuple(float(value) for value in row) for row in cov))
        object.__setattr__(self, "dimensionless_scale", tuple(float(v) for v in scale_vector))

    @property
    def dimension(self) -> int:
        return len(self.mean)

    def mean_array(self) -> np.ndarray:
        return np.asarray(self.mean, dtype=float)

    def cov_array(self) -> np.ndarray:
        return np.asarray(self.cov, dtype=float)

    def to_json(self) -> dict:
        return {
            "mean": list(self.mean),
            "cov": [list(row) for row in self.cov],
            "dimensionless_scale": list(self.dimensionless_scale),
            "updated_at_ticks": self.updated_at_ticks,
        }


class ParamBeliefStore:
    """学习侧 φ 后验容器：MSG ``PARAMETRIC`` 分支写、式 8 ``F_prior`` 读。

    刻意**不实现** ``Mapping``：它不是节点信念表，不得被传给
    ``UpdateScheduler.update(belief=...)``（那会把参数当节点做 ``belief[node] + 1``）。
    """

    __slots__ = ("_beliefs", "_registration_sha", "_version")

    def __init__(self, *, registration_sha: str = "") -> None:
        if registration_sha:
            _hex64(registration_sha, "registration_sha")
        self._beliefs: dict[str, ParamBelief] = {}
        self._registration_sha = registration_sha
        self._version = 0

    # ---- writes ----------------------------------------------------------- #

    def put(
        self,
        param_id: str,
        belief: ParamBelief,
        *,
        route_code: str,
        registration_sha: str = "",
    ) -> None:
        """写入一条 φ 后验；只有 MSG ``PARAMETRIC`` 分支有写权限。"""
        if not isinstance(param_id, str) or not param_id:
            raise UnsupportedInput("param_id must be a non-empty string")
        if not isinstance(belief, ParamBelief):
            raise UnsupportedInput(
                f"ParamBeliefStore takes ParamBelief values, got {type(belief).__name__}"
            )
        if route_code != PARAMETRIC_ROUTE_CODE:
            raise ContractViolation(
                f"ParamBeliefStore is written only by the MSG {PARAMETRIC_ROUTE_CODE} branch "
                f"(ADR-0014 §2 D1 row 5); got route_code={route_code!r}"
            )
        if self._registration_sha:
            if registration_sha and registration_sha != self._registration_sha:
                raise ContractViolation(
                    "registration_sha does not match the store's frozen CMFL registration"
                )
            if not registration_sha:
                raise ContractViolation(
                    "ParamBeliefStore.put needs the CMFL registration_sha this store was frozen with"
                )
        existing = self._beliefs.get(param_id)
        if existing is not None and belief.updated_at_ticks < existing.updated_at_ticks:
            raise ContractViolation(
                f"ParamBelief for {param_id!r} would move backwards in time "
                f"({belief.updated_at_ticks} < {existing.updated_at_ticks})"
            )
        self._beliefs[param_id] = belief
        self._version += 1

    def drop(self, param_id: str) -> None:
        """移除一条 φ 后验（机制被撤销/降级时由 SLOW 侧驱动）。"""
        if param_id not in self._beliefs:
            raise ContractViolation(f"unknown param belief {param_id!r}")
        del self._beliefs[param_id]
        self._version += 1

    # ---- reads ------------------------------------------------------------ #

    def get(self, param_id: str) -> ParamBelief:
        try:
            return self._beliefs[param_id]
        except KeyError as error:
            raise ContractViolation(f"unknown param belief {param_id!r}") from error

    def maybe_get(self, param_id: str) -> ParamBelief | None:
        return self._beliefs.get(param_id)

    def ids(self) -> tuple:
        return tuple(sorted(self._beliefs))

    def snapshot(self) -> Mapping:
        """Read-only view for 式 8 ``F_prior(…; φ̂)``; copying keeps callers from aliasing."""
        return {param_id: belief for param_id, belief in sorted(self._beliefs.items())}

    @property
    def version(self) -> int:
        return self._version

    @property
    def registration_sha(self) -> str:
        return self._registration_sha

    def digest(self) -> str:
        payload = json.dumps(
            {param_id: belief.to_json() for param_id, belief in sorted(self._beliefs.items())},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def __len__(self) -> int:
        return len(self._beliefs)

    def __contains__(self, param_id: object) -> bool:
        return param_id in self._beliefs

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ParamBeliefStore(ids={self.ids()}, version={self._version})"


@dataclass(frozen=True)
class MSGRouteRecord:
    """一条 MSG 路由记录（§2 D1 可观测性要求：路由码 + 原因 + 统计量）。"""

    context_id: str
    t_ticks: int
    route_code: str
    reason: str
    nis_stat: float | None = None
    dof: int | None = None
    registration_sha: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.context_id, str) or not self.context_id:
            raise UnsupportedInput("MSGRouteRecord.context_id must be a non-empty string")
        if not _is_int(self.t_ticks) or self.t_ticks < 0:
            raise UnsupportedInput("MSGRouteRecord.t_ticks must be a non-negative integer")
        if self.route_code not in ROUTE_CODES:
            raise UnsupportedInput(
                f"MSGRouteRecord.route_code must be one of {ROUTE_CODES}, got {self.route_code!r}"
            )
        if not isinstance(self.reason, str) or not self.reason:
            raise UnsupportedInput("MSGRouteRecord.reason must be a non-empty string")
        if self.route_code in NIS_ROUTE_CODES:
            if self.nis_stat is None or self.dof is None:
                raise UnsupportedInput(
                    f"route {self.route_code!r} is decided on the NIS statistic and must record "
                    "both nis_stat and dof (§2 D1 rows 4a/4b)"
                )
        if self.nis_stat is not None:
            if isinstance(self.nis_stat, bool) or not isinstance(self.nis_stat, (int, float)):
                raise UnsupportedInput("MSGRouteRecord.nis_stat must be a number or None")
            value = float(self.nis_stat)
            if not math.isfinite(value) or value < 0.0:
                raise UnsupportedInput("MSGRouteRecord.nis_stat must be finite and >= 0")
            object.__setattr__(self, "nis_stat", value)
        if self.dof is not None:
            if not _is_int(self.dof) or self.dof < 1:
                raise UnsupportedInput("MSGRouteRecord.dof must be an integer >= 1 or None")
        if self.registration_sha:
            _hex64(self.registration_sha, "registration_sha")

    def to_json(self) -> dict:
        return {
            "context_id": self.context_id,
            "t_ticks": self.t_ticks,
            "route_code": self.route_code,
            "reason": self.reason,
            "nis_stat": self.nis_stat,
            "dof": self.dof,
            "registration_sha": self.registration_sha,
        }


class MSGRouteLog:
    """路由记录汇总；写 ``msg_routes.json`` 且拒绝覆盖已存在的运行报告。"""

    __slots__ = ("_records", "_registration_sha")

    def __init__(self, *, registration_sha: str = "") -> None:
        if registration_sha:
            _hex64(registration_sha, "registration_sha")
        self._records: list[MSGRouteRecord] = []
        self._registration_sha = registration_sha

    def record(self, record: MSGRouteRecord) -> MSGRouteRecord:
        if not isinstance(record, MSGRouteRecord):
            raise UnsupportedInput(
                f"MSGRouteLog takes MSGRouteRecord, got {type(record).__name__}"
            )
        if self._registration_sha and record.registration_sha != self._registration_sha:
            raise ContractViolation(
                "MSGRouteRecord.registration_sha does not match the frozen CMFL registration "
                f"({record.registration_sha!r} != {self._registration_sha!r}); a run may not mix "
                "registrations (ADR-0014 §2 D1 M5)"
            )
        self._records.append(record)
        return record

    def records(self) -> tuple:
        return tuple(self._records)

    def counts(self) -> dict:
        """8 个路由码全在（缺省 0），``COVARIANCE_INCONSISTENT`` 单独计类。"""
        counts = {code: 0 for code in ROUTE_CODES}
        for record in self._records:
            counts[record.route_code] += 1
        return counts

    def to_json(self, path: str | Path) -> Path:
        target = Path(path)
        if target.exists():
            raise ContractViolation(
                f"msg_routes report already exists: {target}; never overwrite a delivered run report "
                "(COORDINATION rule 8)"
            )
        payload = {
            "schema": "cmfl.msg_routes.v1",
            "registration_sha": self._registration_sha,
            "route_order": list(MSG_ROUTE_ORDER),
            "counts": self.counts(),
            "records": [record.to_json() for record in self._records],
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
        try:
            tmp.write_text(
                json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp, target)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
        return target

    def __len__(self) -> int:
        return len(self._records)
