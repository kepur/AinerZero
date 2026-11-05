"""CMFL 登记文件类型（ADR-0014 r3 §3 C5 / §2 D1 M5）：``cmfl_registration.json``。

单一权威原则：

- 本文件承载 §2 D1 的**完整冻结清单 1–3**（MSG 路由参数、发现与晋升参数、
  与 r5 已有冻结源的单一权威关系），带 SHA256；
- 第 3 条只允许**通过 SHA 引用** r5 已有冻结值（式 6 的 ``(ε, θ_baseline)``、
  式 10 的 ``τ``、式 11 的 ``η``、式 12b 的 ``(f_max, u_max)``），
  **不复制、不覆盖**——所以本文件里出现这些名字的数值即视为违约；
- 运行内不得修改：改任一字段 = 新登记 ID + 新实验 ID，旧结果不覆盖。故
  :meth:`CMFLRegistration.digest` 是写进 ``MSGRouteRecord.registration_sha`` 的
  那个值，加载时对文件自带 ``sha256`` 做自校验（手改即报错）。

Pure CPU: json + hashlib only; no model, no network.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import UnsupportedInput

__all__ = [
    "CMFL_SCHEMA",
    "MSG_SECTION_KEYS",
    "DISCOVERY_SECTION_KEYS",
    "R5_REFERENCE_KEYS",
    "R5_FROZEN_NAMES",
    "CMFLRegistration",
]

CMFL_SCHEMA = "cmfl.registration.v1"

#: §2 D1 冻结清单第 1 条：MSG 路由参数（含 ``D_permit`` 版本与 provenance SHA，M8）。
MSG_SECTION_KEYS: tuple = (
    "alpha_s",
    "kappa",
    "tau_id",
    "tau_H",
    "K",
    "W",
    "tau_decorr",
    "integrators",
    "d_permit",
)

#: §2 D1 冻结清单第 2 条：发现与晋升参数（D2/D3/D4），共 17 项。
DISCOVERY_SECTION_KEYS: tuple = (
    "delta_gain",
    "alpha_seq",
    "gamma_weights",
    "n_max",
    "alpha_dom",
    "r_fpca",
    "alpha_audit",
    "n_min",
    "lambda_grid",
    "k_bet",
    "env_families",
    "b_boot",
    "rng_seed",
    "m_in",
    "m_out",
    "tau_cal",
    "delta_cal",
    "n_cal",
)

#: §2 D1 冻结清单第 3 条：r5 引用条目只允许这两个字段。
R5_REFERENCE_KEYS: tuple = ("source", "sha256")

#: r5 已冻结、本文件**只许引用不许复制**的量名（式 6/10/11/12b）。
R5_FROZEN_NAMES: tuple = ("epsilon", "theta_baseline", "tau", "eta", "f_max", "u_max")

_HEX64 = re.compile(r"[0-9a-f]{64}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnsupportedInput(f"cmfl_registration.{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise UnsupportedInput(f"cmfl_registration.{name} must be finite")
    return number


def _positive_int(value: Any, name: str, *, minimum: int = 1) -> int:
    if not _is_int(value) or value < minimum:
        raise UnsupportedInput(f"cmfl_registration.{name} must be an integer >= {minimum}")
    return value


def _probability(value: Any, name: str) -> float:
    number = _number(value, name)
    if not 0.0 < number < 1.0:
        raise UnsupportedInput(f"cmfl_registration.{name} must be in (0, 1), got {value!r}")
    return number


def _hex64(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise UnsupportedInput(f"cmfl_registration.{name} must be a 64-char lowercase sha256")
    return value


@dataclass(frozen=True)
class CMFLRegistration:
    """一份冻结的 CMFL 登记；``digest()`` 即运行里引用的 ``registration_sha``。"""

    registration_id: str
    frozen_at: str
    msg: Mapping
    discovery: Mapping
    r5_references: Mapping
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.registration_id, str) or not self.registration_id:
            raise UnsupportedInput("cmfl_registration.registration_id must be a non-empty string")
        if not isinstance(self.frozen_at, str) or not self.frozen_at:
            raise UnsupportedInput("cmfl_registration.frozen_at must be a non-empty ISO timestamp")
        _hex64(self.sha256, "sha256")

        for section_name, section, required in (
            ("msg", self.msg, MSG_SECTION_KEYS),
            ("discovery", self.discovery, DISCOVERY_SECTION_KEYS),
        ):
            if not isinstance(section, Mapping):
                raise UnsupportedInput(f"cmfl_registration.{section_name} must be a mapping")
            missing = [key for key in required if key not in section]
            if missing:
                raise UnsupportedInput(
                    f"cmfl_registration.{section_name} is missing frozen key(s) {missing}"
                )
            extra = [key for key in section if key not in required]
            if extra:
                copied = [key for key in extra if key in R5_FROZEN_NAMES]
                if copied:
                    raise UnsupportedInput(
                        f"cmfl_registration.{section_name} carries the r5 frozen value(s) {copied}; "
                        "r5 values may only be referenced by SHA, never copied (§2 D1 item 3)"
                    )
                raise UnsupportedInput(
                    f"cmfl_registration.{section_name} carries unexpected key(s) {extra}; every "
                    "tunable must be on the frozen list"
                )
            for key in required:
                if key in R5_FROZEN_NAMES:
                    raise UnsupportedInput(
                        f"cmfl_registration.{section_name}.{key} duplicates an r5 frozen value; "
                        "r5 values may only be referenced by SHA, never copied (§2 D1 item 3)"
                    )

        self._validate_msg(self.msg)
        self._validate_discovery(self.discovery)
        self._validate_r5_references(self.r5_references)

        if self.digest() != self.sha256:
            raise UnsupportedInput(
                "cmfl_registration.sha256 does not match the canonical digest of its own content; "
                "a frozen registration may not be edited in place (new fields = new registration id)"
            )

    # ---- section checks --------------------------------------------------- #

    @staticmethod
    def _validate_msg(msg: Mapping) -> None:
        _probability(msg["alpha_s"], "msg.alpha_s")
        _number(msg["kappa"], "msg.kappa")
        _number(msg["tau_id"], "msg.tau_id")
        _number(msg["tau_H"], "msg.tau_H")
        _positive_int(msg["K"], "msg.K")
        _positive_int(msg["W"], "msg.W")
        _positive_int(msg["tau_decorr"], "msg.tau_decorr")
        integrators = msg["integrators"]
        if not isinstance(integrators, (list, tuple)) or not integrators:
            raise UnsupportedInput(
                "cmfl_registration.msg.integrators must be a non-empty sequence (row 3 needs a "
                "dt / (dt/2∘dt/2) pair)"
            )
        for index, name in enumerate(integrators):
            if not isinstance(name, str) or not name:
                raise UnsupportedInput(f"cmfl_registration.msg.integrators[{index}] must be a string")
        permit = msg["d_permit"]
        if not isinstance(permit, Mapping):
            raise UnsupportedInput("cmfl_registration.msg.d_permit must be a mapping (M8)")
        for key in ("version", "provenance_sha256"):
            if key not in permit:
                raise UnsupportedInput(f"cmfl_registration.msg.d_permit is missing {key!r} (M8)")
        if not isinstance(permit["version"], str) or not permit["version"]:
            raise UnsupportedInput("cmfl_registration.msg.d_permit.version must be a string")
        _hex64(permit["provenance_sha256"], "msg.d_permit.provenance_sha256")

    @staticmethod
    def _validate_discovery(discovery: Mapping) -> None:
        _number(discovery["delta_gain"], "discovery.delta_gain")
        _probability(discovery["alpha_seq"], "discovery.alpha_seq")
        weights = discovery["gamma_weights"]
        if not isinstance(weights, (list, tuple)) or not weights:
            raise UnsupportedInput(
                "cmfl_registration.discovery.gamma_weights must be an explicit non-empty sequence "
                "(an e-LOND weight formula or array, not a placeholder)"
            )
        total = 0.0
        for index, weight in enumerate(weights):
            value = _number(weight, f"discovery.gamma_weights[{index}]")
            if value < 0.0:
                raise UnsupportedInput(
                    f"cmfl_registration.discovery.gamma_weights[{index}] must be >= 0"
                )
            total += value
        if total > 1.0 + 1e-9:
            raise UnsupportedInput(
                f"cmfl_registration.discovery.gamma_weights must satisfy sum(gamma_t) <= 1, got {total!r}"
            )
        _positive_int(discovery["n_max"], "discovery.n_max")
        _probability(discovery["alpha_dom"], "discovery.alpha_dom")
        _positive_int(discovery["r_fpca"], "discovery.r_fpca")
        _probability(discovery["alpha_audit"], "discovery.alpha_audit")
        _positive_int(discovery["n_min"], "discovery.n_min")
        grid = discovery["lambda_grid"]
        if not isinstance(grid, (list, tuple)) or not grid:
            raise UnsupportedInput(
                "cmfl_registration.discovery.lambda_grid must be a non-empty betting grid {lambda_k}"
            )
        for index, value in enumerate(grid):
            _number(value, f"discovery.lambda_grid[{index}]")
        _positive_int(discovery["k_bet"], "discovery.k_bet")
        families = discovery["env_families"]
        if not isinstance(families, (list, tuple)) or not families:
            raise UnsupportedInput(
                "cmfl_registration.discovery.env_families must declare at least one world family "
                "(EGR 定理 2 needs one e-process per declared family)"
            )
        for index, name in enumerate(families):
            if not isinstance(name, str) or not name:
                raise UnsupportedInput(
                    f"cmfl_registration.discovery.env_families[{index}] must be a string"
                )
        _positive_int(discovery["b_boot"], "discovery.b_boot")
        _positive_int(discovery["rng_seed"], "discovery.rng_seed", minimum=0)
        _positive_int(discovery["m_in"], "discovery.m_in")
        _positive_int(discovery["m_out"], "discovery.m_out")
        _number(discovery["tau_cal"], "discovery.tau_cal")
        _probability(discovery["delta_cal"], "discovery.delta_cal")
        _positive_int(discovery["n_cal"], "discovery.n_cal")

    @staticmethod
    def _validate_r5_references(references: Mapping) -> None:
        if not isinstance(references, Mapping) or not references:
            raise UnsupportedInput(
                "cmfl_registration.r5_references must name the r5 frozen sources it references"
            )
        for name, entry in references.items():
            if not isinstance(name, str) or not name:
                raise UnsupportedInput("cmfl_registration.r5_references keys must be strings")
            if name in R5_FROZEN_NAMES:
                raise UnsupportedInput(
                    f"cmfl_registration.r5_references may not hold the r5 frozen value {name!r} "
                    "itself; reference its source document by SHA instead (§2 D1 item 3)"
                )
            if not isinstance(entry, Mapping):
                raise UnsupportedInput(
                    f"cmfl_registration.r5_references[{name!r}] must be a mapping with {R5_REFERENCE_KEYS}"
                )
            extra = [key for key in entry if key not in R5_REFERENCE_KEYS]
            if extra:
                raise UnsupportedInput(
                    f"cmfl_registration.r5_references[{name!r}] carries {extra}; only "
                    f"{R5_REFERENCE_KEYS} are allowed (reference, do not copy)"
                )
            missing = [key for key in R5_REFERENCE_KEYS if key not in entry]
            if missing:
                raise UnsupportedInput(
                    f"cmfl_registration.r5_references[{name!r}] is missing {missing}"
                )
            if not isinstance(entry["source"], str) or not entry["source"]:
                raise UnsupportedInput(
                    f"cmfl_registration.r5_references[{name!r}].source must be a non-empty string"
                )
            _hex64(entry["sha256"], f"r5_references[{name!r}].sha256")

    # ---- digests and loading ---------------------------------------------- #

    def body(self) -> dict:
        return {
            "schema": CMFL_SCHEMA,
            "registration_id": self.registration_id,
            "frozen_at": self.frozen_at,
            "msg": dict(self.msg),
            "discovery": dict(self.discovery),
            "r5_references": dict(self.r5_references),
        }

    def digest(self) -> str:
        payload = json.dumps(
            self.body(), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, path: str | Path) -> "CMFLRegistration":
        target = Path(path)
        try:
            document = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise UnsupportedInput(f"cmfl_registration file not found: {target}") from error
        except json.JSONDecodeError as error:
            raise UnsupportedInput(f"cmfl_registration is not valid JSON: {target}: {error}") from error
        if not isinstance(document, Mapping):
            raise UnsupportedInput(f"cmfl_registration root must be an object: {target}")
        expected = {"schema", "registration_id", "frozen_at", "msg", "discovery", "r5_references", "sha256"}
        missing = [key for key in expected if key not in document]
        if missing:
            raise UnsupportedInput(f"cmfl_registration is missing top-level key(s) {missing}")
        extra = [key for key in document if key not in expected]
        if extra:
            raise UnsupportedInput(
                f"cmfl_registration carries unexpected top-level key(s) {extra}; "
                "every tunable must live in msg/discovery and be frozen"
            )
        if document["schema"] != CMFL_SCHEMA:
            raise UnsupportedInput(
                f"cmfl_registration.schema must be {CMFL_SCHEMA!r}, got {document['schema']!r}"
            )
        return cls(
            registration_id=document["registration_id"],
            frozen_at=document["frozen_at"],
            msg=document["msg"],
            discovery=document["discovery"],
            r5_references=document["r5_references"],
            sha256=document["sha256"],
        )
