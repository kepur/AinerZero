"""Offline MID discovery: Weak-form STLSQ, data thinning, and executable prior checker.

Implements ADR-0014 r3 §2 D2 (items 1, 4, 6, 7, 8).
Pure NumPy implementation; zero external dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

from .identification import compute_innovations_and_nis
from .registration import _norm_ppf
from .toy_worlds import (
    COULOMB_V_EPS,
    INV_R_SOFTENING,
    ObservationContext,
    k_step_propagated_sensitivity,
    step_sensitivity_jacobian,
)


@dataclass(frozen=True)
class BasisTermSpec:
    """Candidate basis function in the MID symbolic/sparse regression library."""

    name: str
    units: str  # must be "L/T^2" for acceleration
    is_dissipative: bool
    eval_accel: Callable[[np.ndarray], np.ndarray]  # maps state (..., 4) -> accel (..., 2)


def default_basis_library(*, exclude_terms: Sequence[str] = ()) -> tuple[BasisTermSpec, ...]:
    """Build candidate basis library (supports excluding terms for ALDER negative controls)."""
    excluded = set(exclude_terms)
    all_terms = (
        BasisTermSpec(
            name="quadratic_drag",
            units="L/T^2",
            is_dissipative=True,
            eval_accel=lambda s: np.stack(
                [
                    -np.hypot(s[..., 2], s[..., 3]) * s[..., 2],
                    -np.hypot(s[..., 2], s[..., 3]) * s[..., 3],
                ],
                axis=-1,
            ),
        ),
        BasisTermSpec(
            name="coulomb_friction",
            units="L/T^2",
            is_dissipative=True,
            eval_accel=lambda s: (
                -np.tanh(np.hypot(s[..., 2], s[..., 3]) / COULOMB_V_EPS)[..., None]
                * np.stack([s[..., 2], s[..., 3]], axis=-1)
                / np.maximum(np.hypot(s[..., 2], s[..., 3])[..., None], 1e-8)
            ),
        ),
        BasisTermSpec(
            name="altered_inv_r_gravity",
            units="L/T^2",
            is_dissipative=False,
            eval_accel=lambda s: np.stack(
                [
                    -s[..., 0] / np.maximum(np.hypot(s[..., 0], s[..., 1]) * (np.hypot(s[..., 0], s[..., 1]) + INV_R_SOFTENING), 1e-6),
                    -s[..., 1] / np.maximum(np.hypot(s[..., 0], s[..., 1]) * (np.hypot(s[..., 0], s[..., 1]) + INV_R_SOFTENING), 1e-6),
                ],
                axis=-1,
            ),
        ),
        BasisTermSpec(
            name="cubic_spring",
            units="L/T^2",
            is_dissipative=False,
            eval_accel=lambda s: np.stack(
                [
                    -(s[..., 0] ** 2 + s[..., 1] ** 2) * s[..., 0],
                    -(s[..., 0] ** 2 + s[..., 1] ** 2) * s[..., 1],
                ],
                axis=-1,
            ),
        ),
        BasisTermSpec(
            name="spurious_energy_pump",
            units="L/T^2",
            is_dissipative=True,  # claims to be dissipative velocity force, but pumps energy (+|v|v)
            eval_accel=lambda s: np.stack(
                [
                    +np.hypot(s[..., 2], s[..., 3]) * s[..., 2],
                    +np.hypot(s[..., 2], s[..., 3]) * s[..., 3],
                ],
                axis=-1,
            ),
        ),
        BasisTermSpec(
            name="spurious_anisotropic_x2",
            units="L^2/T^2",  # wrong units and breaks SO(2) horizontal symmetry
            is_dissipative=False,
            eval_accel=lambda s: np.stack([s[..., 0] ** 2, np.zeros_like(s[..., 1])], axis=-1),
        ),
    )
    return tuple(t for t in all_terms if t.name not in excluded)


# ---------------------------------------------------------------------------
# 1. Executable Prior Checker (ADR-0014 §2 D2-1, PG-SR 2602.13021)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PriorCheckVerdict:
    term_name: str
    passed: bool
    dimensional_ok: bool
    se2_symmetry_ok: bool
    passivity_ok: bool
    reason: str


class ExecutablePriorChecker:
    """Prunes candidate basis terms using executable physical prior constraints:
    1. Dimensional consistency (units == 'L/T^2')
    2. Horizontal SO(2) rotation equivariance: a(R*p, R*v) == R * a(p, v)
    3. Passivity / energy non-increase for velocity-dependent dissipative terms: <a(s), v> <= 0
    """

    def check_term(self, term: BasisTermSpec) -> PriorCheckVerdict:
        dim_ok = term.units == "L/T^2"

        # Test horizontal rotation equivariance on probe states
        theta = 0.73
        c, s = np.cos(theta), np.sin(theta)
        rot = np.array([[c, -s], [s, c]], dtype=float)
        probe = np.array(
            [
                [1.5, -0.8, 2.2, -1.4],
                [-1.1, 2.0, -1.7, 0.9],
                [0.6, 1.3, -0.5, -2.1],
            ],
            dtype=float,
        )
        rot_probe = np.zeros_like(probe)
        rot_probe[:, :2] = probe[:, :2] @ rot.T
        rot_probe[:, 2:4] = probe[:, 2:4] @ rot.T

        a_orig = term.eval_accel(probe)
        a_rot_input = term.eval_accel(rot_probe)
        a_rot_output = a_orig @ rot.T
        se2_ok = bool(np.allclose(a_rot_input, a_rot_output, atol=1e-10, rtol=1e-8))

        # Test passivity <a(s), v> <= 0 if dissipative
        if term.is_dissipative:
            power = np.sum(a_orig * probe[:, 2:4], axis=-1)
            pass_ok = bool(np.all(power <= 1e-12))
        else:
            pass_ok = True

        passed = dim_ok and se2_ok and pass_ok
        reasons = []
        if not dim_ok:
            reasons.append(f"invalid units {term.units!r} != 'L/T^2'")
        if not se2_ok:
            reasons.append("violates horizontal SO(2) rotation equivariance")
        if not pass_ok:
            reasons.append("violates passivity (<a, v> > 0 pumps energy)")
        return PriorCheckVerdict(
            term_name=term.name,
            passed=passed,
            dimensional_ok=dim_ok,
            se2_symmetry_ok=se2_ok,
            passivity_ok=pass_ok,
            reason="ok" if passed else "; ".join(reasons),
        )

    def filter_library(
        self, library: Sequence[BasisTermSpec]
    ) -> tuple[tuple[BasisTermSpec, ...], tuple[PriorCheckVerdict, ...]]:
        verdicts = tuple(self.check_term(t) for t in library)
        kept = tuple(t for t, v in zip(library, verdicts) if v.passed)
        return kept, verdicts


# ---------------------------------------------------------------------------
# 2. Data Thinning (ADR-0014 §2 D2-8, PSI-SINDy 2610.11486)
# ---------------------------------------------------------------------------

def data_thin_gaussian_residuals(
    residuals: np.ndarray,
    noise_cov: np.ndarray,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Split Gaussian residuals R ~ N(mu, Sigma) into two independent views:
    R_select = R + Z,  R_infer = R - Z,  where Z ~ N(0, Sigma).
    Under known-variance additive Gaussian noise, Cov(R_select, R_infer) = Sigma - Sigma = 0.
    """
    r = np.asarray(residuals, dtype=float)
    cov = noise_cov if noise_cov.ndim == 2 else noise_cov[0]
    z = rng.multivariate_normal(np.zeros(r.shape[-1], dtype=float), cov, size=r.shape[:-1])
    return r + z, r - z


# ---------------------------------------------------------------------------
# 3. Weak-Form STLSQ + Post-Selection Inference (ADR-0014 §2 D2-1 & D2-8)
# ---------------------------------------------------------------------------

def _weak_bump_weights(sub_len: int) -> np.ndarray:
    """Compactly supported smooth test function psi(tau) = (1 - tau^2)^4 on [-1, 1]."""
    tau = np.linspace(-1.0, 1.0, sub_len + 2)[1:-1]
    w = (1.0 - tau * tau) ** 4
    return w / np.sum(w)


@dataclass(frozen=True)
class DiscoveredCandidate:
    """Candidate residual mechanism discovered in MID (ready for D3 promotion testing)."""

    candidate_id: str
    proposer: str
    active_terms: tuple[str, ...]
    coefficients: np.ndarray  # aligned with active_terms
    confidence_intervals: tuple[tuple[float, float], ...]
    abstained_terms: tuple[str, ...]
    pareto_error: float
    pareto_complexity: int
    discovery_data_id: str
    total_candidates_attempted: int
    orthogonality_mode: str

    def predict_residual_accel(
        self,
        state: np.ndarray,
        library_map: dict[str, BasisTermSpec],
    ) -> np.ndarray:
        out = np.zeros_like(state[..., :2], dtype=float)
        for name, coeff in zip(self.active_terms, self.coefficients):
            if coeff > 0.0 and name in library_map:
                out = out + float(coeff) * library_map[name].eval_accel(state)
        return out


class WeakFormSTLSQ:
    """Weak-form Sequential Thresholded Least Squares with data thinning & prior checking."""

    def __init__(
        self,
        *,
        threshold: float = 0.20,
        sub_window: int = 6,
        stride: int = 2,
        ridge: float = 1e-8,
        ci_alpha: float = 0.05,
    ) -> None:
        self.threshold = float(threshold)
        self.sub_window = int(sub_window)
        self.stride = int(stride)
        self.ridge = float(ridge)
        self.ci_alpha = float(ci_alpha)
        self.prior_checker = ExecutablePriorChecker()

    def _compute_pooled_orthogonal_basis(
        self,
        contexts: Sequence[ObservationContext],
        phi: np.ndarray,
        mode: str,
    ) -> np.ndarray:
        """Compute orthonormal basis Q_pool of the global parameter sensitivity subspace across contexts."""
        p = len(phi)
        g_blocks: list[np.ndarray] = []
        for ctx in contexts:
            if mode == "single_step":
                sens = step_sensitivity_jacobian(
                    ctx.states, ctx.actions, ctx.dt, phi, integrator=ctx.integrator
                )
            elif mode == "k_step":
                sens = k_step_propagated_sensitivity(
                    ctx.states[0], ctx.actions, ctx.dt, phi, integrator=ctx.integrator
                )
            else:
                raise ValueError(f"unsupported orthogonality_mode: {mode!r}")
            g_blocks.append(sens.reshape(-1, p))
        g_pool = np.vstack(g_blocks)
        u_svd, s_svd, _ = np.linalg.svd(g_pool, full_matrices=False)
        rank = int(np.sum(s_svd > 1e-12 * max(1.0, float(s_svd[0]))))
        return u_svd[:, :rank]

    @staticmethod
    def _project_views_orthogonal(
        views: Sequence[np.ndarray],
        q_pool: np.ndarray,
    ) -> list[np.ndarray]:
        """Project a list of (W, 4) state-residual arrays onto col(Q_pool)^perp."""
        if q_pool.size == 0:
            return [v.copy() for v in views]
        shapes = [v.shape for v in views]
        sizes = [v.size for v in views]
        stacked = np.concatenate([v.reshape(-1) for v in views])
        proj = stacked - q_pool @ (q_pool.T @ stacked)
        splits = np.cumsum(sizes[:-1])
        chunks = np.split(proj, splits)
        return [c.reshape(sh) for c, sh in zip(chunks, shapes)]

    def _build_weak_system(
        self,
        contexts: Sequence[ObservationContext],
        residual_views: Sequence[np.ndarray],
        basis_accel_views: Sequence[Sequence[np.ndarray]],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Integrate velocity residuals dv_res/dt and basis accelerations against weak bump psi."""
        rows_theta: list[np.ndarray] = []
        rows_target: list[float] = []
        bump = _weak_bump_weights(self.sub_window)
        m_terms = len(basis_accel_views)

        for ctx_i, (ctx, res) in enumerate(zip(contexts, residual_views)):
            w = ctx.states.shape[0]
            # Acceleration residual implied by step velocity residual dv_res / dt
            acc_res = res[:, 2:4] / ctx.dt  # (W, 2)
            for start in range(0, w - self.sub_window + 1, self.stride):
                end = start + self.sub_window
                for axis in (0, 1):
                    target_val = float(np.sum(bump * acc_res[start:end, axis]))
                    feat_row = np.array(
                        [
                            float(np.sum(bump * basis_accel_views[j][ctx_i][start:end, axis]))
                            for j in range(m_terms)
                        ],
                        dtype=float,
                    )
                    rows_theta.append(feat_row)
                    rows_target.append(target_val)
        return np.asarray(rows_theta, dtype=float), np.asarray(rows_target, dtype=float)

    def discover(
        self,
        contexts: Sequence[ObservationContext],
        phi: np.ndarray,
        *,
        library: Sequence[BasisTermSpec] | None = None,
        rng: np.random.Generator,
        discovery_data_id: str = "D_discovery_v1",
        orthogonality_mode: str = "single_step",
        project_orthogonal: bool = True,
        candidate_id: str = "cand_stlsq_v1",
    ) -> DiscoveredCandidate:
        """Run complete MID continuous discovery pipeline:
        1. ExecutablePriorChecker prunes physically inconsistent basis functions.
        2. Project residuals and basis columns onto orthogonal complement of global sensitivity subspace (FWL).
        3. Data thinning splits residuals into independent selection view and inference view.
        4. Weak-form STLSQ selects active support on selection view using normalized column thresholds.
        5. Post-selection z-intervals computed on independent inference view; unidentifiable or
           zero-crossing terms are abstained/dropped.
        """
        raw_lib = default_basis_library() if library is None else tuple(library)
        valid_lib, _ = self.prior_checker.filter_library(raw_lib)
        if not valid_lib:
            return DiscoveredCandidate(
                candidate_id=candidate_id,
                proposer="sindy",
                active_terms=(),
                coefficients=np.zeros(0, dtype=float),
                confidence_intervals=(),
                abstained_terms=(),
                pareto_error=float("inf"),
                pareto_complexity=0,
                discovery_data_id=discovery_data_id,
                total_candidates_attempted=1,
                orthogonality_mode=orthogonality_mode,
            )

        raw_residuals = [compute_innovations_and_nis(ctx, phi)[0] for ctx in contexts]
        raw_sel: list[np.ndarray] = []
        raw_inf: list[np.ndarray] = []
        for ctx, r_raw in zip(contexts, raw_residuals):
            r_s, r_i = data_thin_gaussian_residuals(r_raw, ctx.innovation_cov, rng)
            raw_sel.append(r_s)
            raw_inf.append(r_i)

        if project_orthogonal:
            q_pool = self._compute_pooled_orthogonal_basis(contexts, phi, orthogonality_mode)
            select_views = self._project_views_orthogonal(raw_sel, q_pool)
            infer_views = self._project_views_orthogonal(raw_inf, q_pool)
            basis_accel_views: list[list[np.ndarray]] = []
            for term in valid_lib:
                ds_list = []
                for ctx in contexts:
                    aj = term.eval_accel(ctx.states)
                    ds_list.append(np.concatenate([0.5 * (ctx.dt ** 2) * aj, ctx.dt * aj], axis=-1))
                ds_perp = self._project_views_orthogonal(ds_list, q_pool)
                basis_accel_views.append([v[:, 2:4] / ctx.dt for v, ctx in zip(ds_perp, contexts)])
        else:
            select_views = raw_sel
            infer_views = raw_inf
            basis_accel_views = [[term.eval_accel(ctx.states) for ctx in contexts] for term in valid_lib]

        w_sel, y_sel = self._build_weak_system(contexts, select_views, basis_accel_views)
        w_inf, y_inf = self._build_weak_system(contexts, infer_views, basis_accel_views)

        m = len(valid_lib)
        active_mask = np.ones(m, dtype=bool)
        coeffs = np.zeros(m, dtype=float)
        n_attempted = 0
        col_norms = np.maximum(np.linalg.norm(w_sel, axis=0), 1e-12)
        y_sel_norm = max(float(np.linalg.norm(y_sel)), 1e-12)

        # Sequential Thresholded Least Squares on selection view (normalized contribution thresholding)
        for _ in range(m + 1):
            n_attempted += 1
            if not np.any(active_mask):
                break
            sub_w = w_sel[:, active_mask]
            gram = sub_w.T @ sub_w + self.ridge * np.eye(sub_w.shape[1])
            sub_c = np.linalg.solve(gram, sub_w.T @ y_sel)
            # Physical mechanisms have positive magnitude coefficients in our sign-normalized basis
            new_mask = active_mask.copy()
            active_indices = np.where(active_mask)[0]
            for local_j, global_j in enumerate(active_indices):
                norm_contrib = float(sub_c[local_j] * col_norms[global_j] / y_sel_norm)
                if sub_c[local_j] <= 0.0 or norm_contrib < self.threshold:
                    new_mask[global_j] = False
            coeffs[:] = 0.0
            if np.any(new_mask):
                sub_w2 = w_sel[:, new_mask]
                gram2 = sub_w2.T @ sub_w2 + self.ridge * np.eye(sub_w2.shape[1])
                coeffs[new_mask] = np.linalg.solve(gram2, sub_w2.T @ y_sel)
            if np.array_equal(new_mask, active_mask):
                break
            active_mask = new_mask

        # Post-selection inference on independent view (w_inf, y_inf)
        selected_idx = np.where(active_mask)[0]
        if selected_idx.size == 0:
            err = float(np.mean(y_inf ** 2))
            return DiscoveredCandidate(
                candidate_id=candidate_id,
                proposer="sindy",
                active_terms=(),
                coefficients=np.zeros(0, dtype=float),
                confidence_intervals=(),
                abstained_terms=(),
                pareto_error=err,
                pareto_complexity=0,
                discovery_data_id=discovery_data_id,
                total_candidates_attempted=n_attempted,
                orthogonality_mode=orthogonality_mode,
            )

        sub_inf = w_inf[:, selected_idx]
        gram_inf = sub_inf.T @ sub_inf
        eigvals = np.linalg.eigvalsh(gram_inf)
        abstained: list[str] = []
        final_names: list[str] = []
        final_coeffs: list[float] = []
        final_cis: list[tuple[float, float]] = []

        if eigvals[0] <= 1e-10:
            # Unidentifiable design on inference view -> abstain on interval reporting (PSI-SINDy)
            abstained = [valid_lib[i].name for i in selected_idx]
            err = float(np.mean(y_inf ** 2))
            return DiscoveredCandidate(
                candidate_id=candidate_id,
                proposer="sindy",
                active_terms=(),
                coefficients=np.zeros(0, dtype=float),
                confidence_intervals=(),
                abstained_terms=tuple(abstained),
                pareto_error=err,
                pareto_complexity=0,
                discovery_data_id=discovery_data_id,
                total_candidates_attempted=n_attempted,
                orthogonality_mode=orthogonality_mode,
            )

        c_inf = np.linalg.solve(gram_inf, sub_inf.T @ y_inf)
        res_inf = y_inf - sub_inf @ c_inf
        dof_inf = max(1, len(y_inf) - len(selected_idx))
        sigma2_hat = float(np.sum(res_inf ** 2) / dof_inf)
        cov_c = sigma2_hat * np.linalg.inv(gram_inf)
        z_crit = _norm_ppf(1.0 - 0.5 * self.ci_alpha)

        col_norms_inf = np.maximum(np.linalg.norm(w_inf, axis=0), 1e-12)
        y_inf_norm = max(float(np.linalg.norm(y_inf)), 1e-12)

        for local_j, global_j in enumerate(selected_idx):
            c_val = float(c_inf[local_j])
            se_val = float(np.sqrt(max(cov_c[local_j, local_j], 1e-16)))
            lo, hi = c_val - z_crit * se_val, c_val + z_crit * se_val
            norm_contrib_inf = float(c_val * col_norms_inf[global_j] / y_inf_norm)
            if lo > 0.0 and norm_contrib_inf >= self.threshold:
                final_names.append(valid_lib[global_j].name)
                final_coeffs.append(c_val)
                final_cis.append((lo, hi))
            else:
                abstained.append(valid_lib[global_j].name)

        if final_names:
            kept_idx = [i for i, t in enumerate(valid_lib) if t.name in final_names]
            pred_inf = w_inf[:, kept_idx] @ np.asarray(final_coeffs, dtype=float)
            pareto_err = float(np.mean((y_inf - pred_inf) ** 2))
        else:
            pareto_err = float(np.mean(y_inf ** 2))

        return DiscoveredCandidate(
            candidate_id=candidate_id,
            proposer="sindy",
            active_terms=tuple(final_names),
            coefficients=np.asarray(final_coeffs, dtype=float),
            confidence_intervals=tuple(final_cis),
            abstained_terms=tuple(abstained),
            pareto_error=pareto_err,
            pareto_complexity=len(final_names),
            discovery_data_id=discovery_data_id,
            total_candidates_attempted=n_attempted,
            orthogonality_mode=orthogonality_mode,
        )
