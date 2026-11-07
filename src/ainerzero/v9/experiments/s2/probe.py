"""S2 linear probe protocol: closed-form ridge regression for latent readout.

Pure CPU, NumPy / standard library only. Zero MLX imports.
Specifications per reports/V9-S2-DESIGN/DESIGN-r2.md §5 (λ=1.0 closed-form, train-only fit).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

__all__ = [
    "RidgeProbe",
    "fit_ridge",
    "eval_error",
    "summarize_step_errors",
]


@dataclass(frozen=True)
class RidgeProbe:
    """Trained closed-form ridge regression probe."""

    weights: np.ndarray  # shape (D, target_dim)
    bias: np.ndarray  # shape (target_dim,)
    lam: float
    fit_intercept: bool

    def predict(self, Z: np.ndarray | Sequence[Any]) -> np.ndarray:
        """Decode coordinates from latent representations.

        Args:
            Z: ndarray of shape (..., D)

        Returns:
            Decoded coordinates with shape (..., target_dim)
        """
        Z_arr = np.asarray(Z, dtype=np.float64)
        if Z_arr.shape[-1] != self.weights.shape[0]:
            raise ValueError(
                f"Feature dimension mismatch: expected {self.weights.shape[0]}, got {Z_arr.shape[-1]}"
            )
        return Z_arr @ self.weights + self.bias

    def to_dict(self) -> dict[str, Any]:
        return {
            "lam": self.lam,
            "fit_intercept": self.fit_intercept,
            "in_dim": int(self.weights.shape[0]),
            "out_dim": int(self.weights.shape[1]),
        }


def fit_ridge(
    Z_train: np.ndarray | Sequence[Any],
    XY_train: np.ndarray | Sequence[Any],
    lam: float = 1.0,
    *,
    fit_intercept: bool = True,
) -> RidgeProbe:
    """Fit closed-form ridge regression from latent features Z to target coordinates XY.

    Args:
        Z_train: Array of shape (N, D) containing latent representations.
        XY_train: Array of shape (N, 2) containing ground-truth coordinates (x, y).
        lam: Regularization strength λ (frozen default 1.0 per DESIGN-r2.md §5).
        fit_intercept: Whether to estimate an unpenalized bias term.

    Returns:
        RidgeProbe instance containing learned weights and bias.
    """
    if lam < 0.0:
        raise ValueError(f"Ridge penalty lam must be non-negative, got {lam}")

    Z = np.asarray(Z_train, dtype=np.float64)
    XY = np.asarray(XY_train, dtype=np.float64)

    if Z.ndim != 2:
        raise ValueError(f"Z_train must be 2D of shape (N, D), got shape {Z.shape}")
    if XY.ndim != 2:
        raise ValueError(f"XY_train must be 2D of shape (N, target_dim), got shape {XY.shape}")
    if Z.shape[0] != XY.shape[0]:
        raise ValueError(
            f"Sample count mismatch: Z has {Z.shape[0]} rows, XY has {XY.shape[0]} rows"
        )
    if Z.shape[0] == 0:
        raise ValueError("Cannot fit ridge probe on 0 samples")

    N, D = Z.shape
    target_dim = XY.shape[1]

    if fit_intercept:
        mean_Z = np.mean(Z, axis=0)
        mean_XY = np.mean(XY, axis=0)
        Z_centered = Z - mean_Z
        XY_centered = XY - mean_XY

        # Regularized normal equations: (Z_c^T Z_c + λ I) W = Z_c^T XY_c
        A = Z_centered.T @ Z_centered + lam * np.eye(D, dtype=np.float64)
        B = Z_centered.T @ XY_centered
        weights = np.linalg.solve(A, B)
        bias = mean_XY - mean_Z @ weights
    else:
        A = Z.T @ Z + lam * np.eye(D, dtype=np.float64)
        B = Z.T @ XY
        weights = np.linalg.solve(A, B)
        bias = np.zeros(target_dim, dtype=np.float64)

    return RidgeProbe(
        weights=weights,
        bias=bias,
        lam=float(lam),
        fit_intercept=fit_intercept,
    )


def eval_error(
    probe: RidgeProbe,
    Z_test: np.ndarray | Sequence[Any],
    XY_test: np.ndarray | Sequence[Any],
) -> dict[str, Any]:
    """Evaluate Euclidean distance error between decoded positions and ground truth.

    Distance unit: grid cells (DESIGN-r2.md §5).

    Returns:
        Dictionary with:
        - "mean": float mean Euclidean error across samples
        - "median": float median Euclidean error
        - "max": float max Euclidean error
        - "std": float standard deviation of errors
        - "errors": ndarray of per-sample Euclidean distances
        - "count": int number of samples
    """
    pred_XY = probe.predict(Z_test)
    true_XY = np.asarray(XY_test, dtype=np.float64)

    if pred_XY.shape != true_XY.shape:
        raise ValueError(
            f"Shape mismatch: predictions {pred_XY.shape} vs true {true_XY.shape}"
        )

    # Euclidean distance along the coordinate axis (last dimension)
    diff = pred_XY - true_XY
    distances = np.sqrt(np.sum(diff * diff, axis=-1))

    if distances.size == 0:
        raise ValueError("Cannot evaluate error on empty test set")

    return {
        "mean": float(np.mean(distances)),
        "median": float(np.median(distances)),
        "max": float(np.max(distances)),
        "std": float(np.std(distances)),
        "errors": distances,
        "count": int(distances.size),
    }


def summarize_step_errors(
    probe: RidgeProbe,
    trajectory_latents: Any,
    trajectory_coords: Any,
    steps: Sequence[int] = (1, 5, 10, 30, 60),
) -> dict[int, float]:
    """Summarize Euclidean position readout error at given observation steps.

    Args:
        probe: Trained RidgeProbe.
        trajectory_latents: Either:
            - 2D array of shape (T, D) for a single episode; or
            - 3D array of shape (N_episodes, T, D); or
            - List of 2D arrays, each of shape (T_i, D).
        trajectory_coords: Either:
            - 2D array of shape (T, 2); or
            - 3D array of shape (N_episodes, T, 2); or
            - List of 2D arrays, each of shape (T_i, 2).
        steps: Sequence of step horizons (1-indexed observation steps, default (1, 5, 10, 30, 60)).

    Returns:
        dict mapping step index h to mean Euclidean position error at step h.
    """
    # Normalize inputs into a list of (Z_ep, XY_ep) pairs
    episodes: list[tuple[np.ndarray, np.ndarray]] = []
    if isinstance(trajectory_latents, np.ndarray) and trajectory_latents.ndim == 2:
        episodes.append(
            (trajectory_latents, np.asarray(trajectory_coords, dtype=np.float64))
        )
    elif isinstance(trajectory_latents, np.ndarray) and trajectory_latents.ndim == 3:
        coords_arr = np.asarray(trajectory_coords, dtype=np.float64)
        for i in range(trajectory_latents.shape[0]):
            episodes.append((trajectory_latents[i], coords_arr[i]))
    elif isinstance(trajectory_latents, Sequence):
        for z_ep, xy_ep in zip(trajectory_latents, trajectory_coords):
            episodes.append(
                (np.asarray(z_ep, dtype=np.float64), np.asarray(xy_ep, dtype=np.float64))
            )
    else:
        raise TypeError("Unsupported trajectory format")

    results: dict[int, float] = {}

    for h in steps:
        step_idx = h - 1  # 1-indexed to 0-indexed
        z_list: list[np.ndarray] = []
        xy_list: list[np.ndarray] = []

        for z_ep, xy_ep in episodes:
            if step_idx < z_ep.shape[0] and step_idx < xy_ep.shape[0]:
                z_list.append(z_ep[step_idx])
                xy_list.append(xy_ep[step_idx])

        if not z_list:
            # Step horizon exceeds available steps in all episodes
            results[h] = float("nan")
        else:
            Z_h = np.stack(z_list, axis=0)
            XY_h = np.stack(xy_list, axis=0)
            metrics = eval_error(probe, Z_h, XY_h)
            results[h] = float(metrics["mean"])

    return results
