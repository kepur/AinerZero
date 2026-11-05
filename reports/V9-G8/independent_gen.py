"""V9.G8 独立玩具生成器（对抗复核用）。

设计约束（复核者立场）：
- **不 import** `ainerzero.v9.mechanism.toy_worlds` 里的生成器/积分器/基函数；
  只 import `ObservationContext` 这个纯数据容器（字段形状由 ADR-0014 §3 C7 定义）。
- 物理函数形式必须与 `prior_acceleration` 同族（否则参数辨识与 F_prior 无法对话），
  但积分器、参数抽样、噪声、窗口长度 W、步长 dt、世界/对象命名全部由本文件自己决定。
- 真值（true_route / true_phi / true_mechanism）单独放在 `meta` 里，**不进 ObservationContext**，
  只在评测侧用于对账（§8.6）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ainerzero.v9.mechanism import ObservationContext

# 先验均值/无量纲尺度（与冻结登记一致；这是 F_prior 的输入，不是数据）
G_PRIOR = np.array([9.81, 0.25, 1.20], dtype=float)
SCALE = np.array([2.0, 0.20, 0.50], dtype=float)

# 本复核自己选的观测设置（刻意与 G7 不同：W=16, dt=0.015, sigma=2.5e-3）
W_G8 = 16
DT_G8 = 0.015
SIGMA_G8 = 2.5e-3


@dataclass(frozen=True)
class TruthMeta:
    """评测侧真值（封存，绝不进入 ObservationContext）。"""

    context_id: str
    world_instance_id: str
    family: str
    true_route: str
    true_phi: np.ndarray
    true_mechanism: str
    true_coeff: float


def accel(s: np.ndarray, u: np.ndarray, phi: np.ndarray, mech: str = "none", coeff: float = 0.0) -> np.ndarray:
    """a(s,u;phi) = u - c*v - k*p - g*ey + structural。自己实现（不调用 toy_worlds）。"""
    p = s[..., 0:2]
    v = s[..., 2:4]
    g, c_lin, k_spring = float(phi[0]), float(phi[1]), float(phi[2])
    a = u - c_lin * v - k_spring * p
    a = a + np.stack([np.zeros_like(p[..., 0]), -g * np.ones_like(p[..., 1])], axis=-1)
    if mech == "none" or coeff == 0.0:
        return a
    if mech == "quadratic_drag":
        sp = np.linalg.norm(v, axis=-1, keepdims=True)
        return a - coeff * sp * v
    if mech == "altered_inv_r_gravity":
        r = np.linalg.norm(p, axis=-1, keepdims=True)
        return a - coeff * p / np.maximum(r * (r + 0.25), 1e-6)
    if mech == "coulomb_friction":
        sp = np.linalg.norm(v, axis=-1, keepdims=True)
        return a - coeff * np.tanh(sp / 0.05) * v / np.maximum(sp, 1e-8)
    raise ValueError(mech)


def _rhs(s: np.ndarray, u: np.ndarray, phi: np.ndarray, mech: str, coeff: float) -> np.ndarray:
    return np.concatenate([s[2:4], accel(s, u, phi, mech, coeff)])


def step_rk4(s: np.ndarray, u: np.ndarray, dt: float, phi: np.ndarray, mech: str = "none", coeff: float = 0.0) -> np.ndarray:
    k1 = _rhs(s, u, phi, mech, coeff)
    k2 = _rhs(s + 0.5 * dt * k1, u, phi, mech, coeff)
    k3 = _rhs(s + 0.5 * dt * k2, u, phi, mech, coeff)
    k4 = _rhs(s + dt * k3, u, phi, mech, coeff)
    return s + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def step_euler(s: np.ndarray, u: np.ndarray, dt: float, phi: np.ndarray, mech: str = "none", coeff: float = 0.0) -> np.ndarray:
    return s + dt * _rhs(s, u, phi, mech, coeff)


def rollout(
    init_state: np.ndarray,
    actions: np.ndarray,
    dt: float,
    phi: np.ndarray,
    mech: str,
    coeff: float,
    stepper=step_rk4,
    sigma: float = 0.0,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """生成 (states, next_states)；next_states 带观测噪声，states 不带。"""
    w = actions.shape[0]
    states = np.zeros((w, 4), dtype=float)
    next_states = np.zeros((w, 4), dtype=float)
    cur = np.array(init_state, dtype=float, copy=True)
    for k in range(w):
        states[k] = cur
        nxt = stepper(cur, actions[k], dt, phi, mech, coeff)
        next_states[k] = nxt if (sigma == 0.0 or rng is None) else nxt + rng.normal(0.0, sigma, size=4)
        cur = nxt
    return states, next_states


def make_context(
    *,
    cid: str,
    wid: str,
    states: np.ndarray,
    next_states: np.ndarray,
    actions: np.ndarray,
    dt: float,
    integrator: str,
    sigma: float,
    cov_scale: float = 1.0,
    in_slow_domain: bool = True,
    competing: Sequence[float] = (1.0,),
    requested: Sequence[str] = ("x", "y", "vx", "vy", "ux", "uy"),
    t_start: int = 0,
    objects: Sequence[str] = ("body_a",),
) -> ObservationContext:
    return ObservationContext(
        context_id=cid,
        world_instance_id=wid,
        t_start=t_start,
        object_keys=tuple(objects),
        dt=dt,
        integrator=integrator,
        states=states,
        next_states=next_states,
        actions=actions,
        innovation_cov=np.eye(4, dtype=float) * (sigma ** 2) * cov_scale,
        requested_variables=tuple(requested),
        competing_model_probs=tuple(competing),
        in_slow_domain=in_slow_domain,
    )


# ---------------------------------------------------------------------------
# 八族生成器：每族自己抽参数/动作/初态，标签只进 TruthMeta
# ---------------------------------------------------------------------------

def gen_sufficient(seed: int, n: int) -> list[tuple[ObservationContext, TruthMeta]]:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        s0 = np.array([rng.uniform(-2, 2), rng.uniform(-2, 2), rng.uniform(-3, 3), rng.uniform(-3, 3)])
        u = rng.uniform(-2.5, 2.5, size=(W_G8, 2))
        st, ns = rollout(s0, u, DT_G8, G_PRIOR, "none", 0.0, sigma=SIGMA_G8, rng=rng)
        out.append((make_context(cid=f"g8_suf_{i:02d}", wid=f"g8w_suf_{i:02d}", states=st, next_states=ns,
                                 actions=u, dt=DT_G8, integrator="rk4", sigma=SIGMA_G8),
                    TruthMeta(f"g8_suf_{i:02d}", f"g8w_suf_{i:02d}", "sufficient", "SUFFICIENT", G_PRIOR.copy(), "none", 0.0)))
    return out


def gen_parametric(seed: int, n: int) -> list[tuple[ObservationContext, TruthMeta]]:
    """参数偏差：true_phi != 先验，激励充分（λ_min 应过 τ_id=1.5）。"""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        d = np.array([rng.uniform(0.9, 1.7) * (1 if i % 2 == 0 else -1),
                      rng.uniform(0.18, 0.32),
                      rng.uniform(0.40, 0.70) * (-1 if i % 2 == 0 else 1)])
        tp = G_PRIOR + d
        s0 = np.array([2.2, -1.9, 3.2, -2.7])
        u = rng.uniform(-3.0, 3.0, size=(W_G8, 2))
        st, ns = rollout(s0, u, DT_G8, tp, "none", 0.0, sigma=SIGMA_G8, rng=rng)
        out.append((make_context(cid=f"g8_par_{i:02d}", wid=f"g8w_par_{i:02d}", states=st, next_states=ns,
                                 actions=u, dt=DT_G8, integrator="rk4", sigma=SIGMA_G8),
                    TruthMeta(f"g8_par_{i:02d}", f"g8w_par_{i:02d}", "parametric", "PARAMETRIC", tp, "none", 0.0)))
    return out


def gen_structural(seed: int, n: int, mech: str = "quadratic_drag", coeff: float = 0.55) -> list[tuple[ObservationContext, TruthMeta]]:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        s0 = np.array([1.9, -1.7, 3.6, -3.1])
        u = rng.uniform(-3.0, 3.0, size=(W_G8, 2))
        st, ns = rollout(s0, u, DT_G8, G_PRIOR, mech, coeff, sigma=SIGMA_G8, rng=rng)
        out.append((make_context(cid=f"g8_str_{i:02d}", wid=f"g8w_str_{i:02d}", states=st, next_states=ns,
                                 actions=u, dt=DT_G8, integrator="rk4", sigma=SIGMA_G8),
                    TruthMeta(f"g8_str_{i:02d}", f"g8w_str_{i:02d}", "structural", "STRUCTURAL", G_PRIOR.copy(), mech, coeff)))
    return out


def gen_cov_inconsistent(seed: int, n: int, scale: float = 12.0) -> list[tuple[ObservationContext, TruthMeta]]:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        s0 = np.array([rng.uniform(-2, 2), rng.uniform(-2, 2), rng.uniform(-3, 3), rng.uniform(-3, 3)])
        u = rng.uniform(-2.5, 2.5, size=(W_G8, 2))
        st, ns = rollout(s0, u, DT_G8, G_PRIOR, "none", 0.0, sigma=SIGMA_G8, rng=rng)
        out.append((make_context(cid=f"g8_cov_{i:02d}", wid=f"g8w_cov_{i:02d}", states=st, next_states=ns,
                                 actions=u, dt=DT_G8, integrator="rk4", sigma=SIGMA_G8, cov_scale=scale),
                    TruthMeta(f"g8_cov_{i:02d}", f"g8w_cov_{i:02d}", "cov_inconsistent", "COVARIANCE_INCONSISTENT",
                              G_PRIOR.copy(), "none", 0.0)))
    return out


def gen_numerical(seed: int, n: int) -> list[tuple[ObservationContext, TruthMeta]]:
    """真世界 RK4，学习者用粗步 Euler：ε_num 应触发 NUMERICAL。"""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        s0 = np.array([2.4, -2.1, 3.9, 3.3])
        u = 3.0 * np.sin(np.linspace(0.2, 2.8, W_G8))[:, None] * np.array([[1.0, -0.85]])
        st, ns = rollout(s0, u, 0.08, G_PRIOR, "none", 0.0, sigma=6e-4, rng=rng)
        out.append((make_context(cid=f"g8_num_{i:02d}", wid=f"g8w_num_{i:02d}", states=st, next_states=ns,
                                 actions=u, dt=0.08, integrator="euler", sigma=6e-4),
                    TruthMeta(f"g8_num_{i:02d}", f"g8w_num_{i:02d}", "numerical", "NUMERICAL", G_PRIOR.copy(), "none", 0.0)))
    return out


def gen_abstain(seed: int, n: int) -> list[tuple[ObservationContext, TruthMeta]]:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        s0 = np.array([rng.uniform(-2, 2), rng.uniform(-2, 2), rng.uniform(-3, 3), rng.uniform(-3, 3)])
        u = rng.uniform(-2.0, 2.0, size=(W_G8, 2))
        u[0, 1] = 12.0 * 1.3  # 超 D_permit action_limit=12
        st, ns = rollout(s0, u, DT_G8, G_PRIOR, "none", 0.0, sigma=SIGMA_G8, rng=rng)
        out.append((make_context(cid=f"g8_abs_{i:02d}", wid=f"g8w_abs_{i:02d}", states=st, next_states=ns,
                                 actions=u, dt=DT_G8, integrator="rk4", sigma=SIGMA_G8),
                    TruthMeta(f"g8_abs_{i:02d}", f"g8w_abs_{i:02d}", "d_permit", "ABSTAIN", G_PRIOR.copy(), "none", 0.0)))
    return out


def gen_unidentifiable(seed: int, n: int) -> list[tuple[ObservationContext, TruthMeta]]:
    """悬停：u 抵消重力，轨迹不动 → k/c 不可激励；且竞争机制后验熵 ln2 > τ_H=0.65。"""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        tp = G_PRIOR + np.array([1.5, 0.0, 0.0])
        s0 = np.zeros(4)
        u = np.zeros((W_G8, 2))
        u[:, 1] = tp[0]
        st, ns = rollout(s0, u, DT_G8, tp, "none", 0.0, sigma=SIGMA_G8, rng=rng)
        out.append((make_context(cid=f"g8_uni_{i:02d}", wid=f"g8w_uni_{i:02d}", states=st, next_states=ns,
                                 actions=u, dt=DT_G8, integrator="rk4", sigma=SIGMA_G8,
                                 competing=(0.5, 0.5)),
                    TruthMeta(f"g8_uni_{i:02d}", f"g8w_uni_{i:02d}", "unidentifiable", "UNIDENTIFIABLE",
                              tp, "none", 0.0)))
    return out


def gen_ood(seed: int, n: int, *, in_slow_domain: bool = True) -> list[tuple[ObservationContext, TruthMeta]]:
    """包络外：初态远离 D∪C 的协变量范围，但物理在 D_permit 内。"""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        s0 = np.array([11.5, -10.8, 9.0, -8.4])
        u = rng.uniform(-2.0, 2.0, size=(W_G8, 2))
        st, ns = rollout(s0, u, DT_G8, G_PRIOR, "none", 0.0, sigma=SIGMA_G8, rng=rng)
        out.append((make_context(cid=f"g8_ood_{i:02d}", wid=f"g8w_ood_{i:02d}", states=st, next_states=ns,
                                 actions=u, dt=DT_G8, integrator="rk4", sigma=SIGMA_G8,
                                 in_slow_domain=in_slow_domain),
                    TruthMeta(f"g8_ood_{i:02d}", f"g8w_ood_{i:02d}", "ood", "OUT_OF_DOMAIN", G_PRIOR.copy(), "none", 0.0)))
    return out


def gen_suite(seed: int, n: int = 6, *, ood_flag: bool = True) -> list[tuple[ObservationContext, TruthMeta]]:
    """ood_flag=True 表示 OOD 上下文**带**真值标签（`in_slow_domain=False`，G7 同构口径）；
    False 表示不带标签，只能靠共形包络判越界。"""
    rows: list[tuple[ObservationContext, TruthMeta]] = []
    rows += gen_sufficient(seed + 1, n)
    rows += gen_ood(seed + 2, n, in_slow_domain=not ood_flag)
    rows += gen_numerical(seed + 3, n)
    rows += gen_cov_inconsistent(seed + 4, n)
    rows += gen_parametric(seed + 5, n)
    rows += gen_unidentifiable(seed + 6, n)
    rows += gen_structural(seed + 7, n)
    rows += gen_abstain(seed + 8, n)
    return rows
