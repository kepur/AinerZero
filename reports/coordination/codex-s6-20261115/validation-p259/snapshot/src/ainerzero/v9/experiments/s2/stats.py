"""S2 statistical framework: clustered paired bootstrap and power estimation.

Pure CPU, NumPy / standard library only. Zero MLX imports.
Specifications per reports/V9-S2-DESIGN/DESIGN-r2.md §5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

__all__ = [
    "BootstrapResult",
    "cluster_paired_bootstrap",
    "unclustered_paired_bootstrap",
    "power_estimate",
]


@dataclass(frozen=True)
class BootstrapResult:
    """Outcome of clustered / paired bootstrap resampling."""

    mean: float
    ci_lower: float
    ci_upper: float
    boot_means: np.ndarray
    n_worlds: int
    n_episodes: int
    n_boot: int

    @property
    def ci_width(self) -> float:
        return float(self.ci_upper - self.ci_lower)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean": self.mean,
            "ci_lower": self.ci_lower,
            "ci_upper": self.ci_upper,
            "ci_width": self.ci_width,
            "n_worlds": self.n_worlds,
            "n_episodes": self.n_episodes,
            "n_boot": self.n_boot,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


def _normalize_diff_input(
    diff_by_world_episode: Any,
) -> list[np.ndarray]:
    """Normalize input into a list of 1D ndarrays, one per world."""
    if isinstance(diff_by_world_episode, Mapping):
        # Dict of world_id -> list of episode diffs
        world_arrays = [
            np.asarray(episodes, dtype=np.float64).reshape(-1)
            for episodes in diff_by_world_episode.values()
        ]
    elif isinstance(diff_by_world_episode, np.ndarray):
        if diff_by_world_episode.ndim == 2:
            world_arrays = [
                diff_by_world_episode[w, :].copy()
                for w in range(diff_by_world_episode.shape[0])
            ]
        elif diff_by_world_episode.ndim == 1:
            raise ValueError(
                "1D array passed as diff_by_world_episode; world dimension is required"
            )
        else:
            raise ValueError(
                f"diff_by_world_episode array ndim={diff_by_world_episode.ndim} unsupported"
            )
    elif isinstance(diff_by_world_episode, Sequence):
        world_arrays = [
            np.asarray(world_diffs, dtype=np.float64).reshape(-1)
            for world_diffs in diff_by_world_episode
        ]
    else:
        raise TypeError(
            f"Unsupported diff_by_world_episode type: {type(diff_by_world_episode)}"
        )

    return world_arrays


def cluster_paired_bootstrap(
    diff_by_world_episode: Any,
    n_boot: int = 10000,
    rng: np.random.Generator | int | None = None,
    alpha: float = 0.05,
) -> BootstrapResult:
    """Clustered paired bootstrap on per-world, per-episode differences.

    Methodology (DESIGN-r2.md §5):
    Two-stage cluster resampling:
    1. Sample worlds with replacement (cluster level);
    2. Within each sampled world, sample episodes with replacement.
    Outputs mean difference and (1 - alpha) percentile interval (default 95%).

    Fails closed:
    - If number of worlds < 2, raises ValueError (no silent fallback to unclustered).
    """
    if n_boot <= 0:
        raise ValueError("n_boot must be > 0")
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha must be in (0, 1)")

    if rng is None:
        np_rng = np.random.default_rng()
    elif isinstance(rng, (int, np.integer)):
        np_rng = np.random.default_rng(int(rng))
    elif isinstance(rng, np.random.Generator):
        np_rng = rng
    else:
        raise TypeError("rng must be an int, np.random.Generator, or None")

    world_arrays = _normalize_diff_input(diff_by_world_episode)
    n_worlds = len(world_arrays)

    if n_worlds < 2:
        raise ValueError(
            f"cluster_paired_bootstrap requires at least 2 worlds for cluster resampling, got {n_worlds}"
        )

    for w_idx, arr in enumerate(world_arrays):
        if arr.size == 0:
            raise ValueError(f"World {w_idx} has 0 episodes")

    total_episodes = sum(arr.size for arr in world_arrays)
    grand_mean = float(np.sum([np.sum(arr) for arr in world_arrays]) / total_episodes)

    # Check if balanced (all worlds have identical number of episodes) for fast vectorized path
    lengths = [arr.size for arr in world_arrays]
    is_balanced = all(l == lengths[0] for l in lengths)

    if is_balanced:
        m = lengths[0]
        # Shape: (n_worlds, m)
        data_matrix = np.stack(world_arrays, axis=0)

        # 1. Sample worlds with replacement: shape (n_boot, n_worlds)
        world_idx = np_rng.integers(0, n_worlds, size=(n_boot, n_worlds))
        # 2. Sample episodes within each world with replacement: shape (n_boot, n_worlds, m)
        ep_idx = np_rng.integers(0, m, size=(n_boot, n_worlds, m))

        # Advanced indexing:
        # data_matrix[world_idx[:, :, None], ep_idx] has shape (n_boot, n_worlds, m)
        boot_samples = data_matrix[world_idx[:, :, None], ep_idx]
        boot_means = boot_samples.mean(axis=(1, 2))
    else:
        # Unbalanced: general path
        boot_means = np.empty(n_boot, dtype=np.float64)
        for b in range(n_boot):
            sampled_world_indices = np_rng.integers(0, n_worlds, size=n_worlds)
            b_sum = 0.0
            b_count = 0
            for w in sampled_world_indices:
                w_arr = world_arrays[w]
                w_len = w_arr.size
                sampled_ep = w_arr[np_rng.integers(0, w_len, size=w_len)]
                b_sum += float(np.sum(sampled_ep))
                b_count += w_len
            boot_means[b] = b_sum / b_count

    ci_lower = float(np.percentile(boot_means, 100.0 * (alpha / 2.0)))
    ci_upper = float(np.percentile(boot_means, 100.0 * (1.0 - alpha / 2.0)))

    return BootstrapResult(
        mean=grand_mean,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        boot_means=boot_means,
        n_worlds=n_worlds,
        n_episodes=total_episodes,
        n_boot=n_boot,
    )


def unclustered_paired_bootstrap(
    diff_by_world_episode: Any,
    n_boot: int = 10000,
    rng: np.random.Generator | int | None = None,
    alpha: float = 0.05,
) -> BootstrapResult:
    """Standard unclustered paired bootstrap across all pooled episodes.

    Provided for diagnostic comparison (ratio test in DESIGN-r2.md §5 / mutation P122-M1).
    """
    if rng is None:
        np_rng = np.random.default_rng()
    elif isinstance(rng, (int, np.integer)):
        np_rng = np.random.default_rng(int(rng))
    elif isinstance(rng, np.random.Generator):
        np_rng = rng
    else:
        raise TypeError("rng must be an int, np.random.Generator, or None")

    world_arrays = _normalize_diff_input(diff_by_world_episode)
    flat_diffs = np.concatenate(world_arrays, axis=0)
    n = flat_diffs.size
    if n < 2:
        raise ValueError("unclustered_paired_bootstrap requires at least 2 episodes")

    sample_indices = np_rng.integers(0, n, size=(n_boot, n))
    boot_samples = flat_diffs[sample_indices]
    boot_means = boot_samples.mean(axis=1)

    ci_lower = float(np.percentile(boot_means, 100.0 * (alpha / 2.0)))
    ci_upper = float(np.percentile(boot_means, 100.0 * (1.0 - alpha / 2.0)))

    return BootstrapResult(
        mean=float(np.mean(flat_diffs)),
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        boot_means=boot_means,
        n_worlds=len(world_arrays),
        n_episodes=n,
        n_boot=n_boot,
    )


def power_estimate(
    effect: float,
    p_base: float,
    icc: float,
    n_worlds: int,
    m_per_world: int,
    n_sim: int = 1000,
    n_boot: int = 1000,
    rng: np.random.Generator | int | None = None,
    alpha: float = 0.05,
) -> float:
    """Simulate power for clustered paired testing at (effect, p_base, icc).

    Generates synthetic clustered binary outcomes for Treatment (Arm X) and
    Baseline (Arm Y), runs cluster_paired_bootstrap, and estimates the probability
    that the (1 - alpha) CI lower bound is strictly > 0.
    """
    if n_worlds < 2:
        raise ValueError("n_worlds must be >= 2")
    if m_per_world < 1:
        raise ValueError("m_per_world must be >= 1")
    if not (0.0 <= icc <= 1.0):
        raise ValueError("icc must be in [0, 1]")

    if rng is None:
        np_rng = np.random.default_rng()
    elif isinstance(rng, (int, np.integer)):
        np_rng = np.random.default_rng(int(rng))
    elif isinstance(rng, np.random.Generator):
        np_rng = rng
    else:
        raise TypeError("rng must be an int, np.random.Generator, or None")

    sigma_u = np.sqrt(icc * p_base * (1.0 - p_base))
    rejections = 0

    for _ in range(n_sim):
        # World random intercept
        u = np_rng.normal(0.0, sigma_u, size=n_worlds)

        # Base probabilities clipped to valid range
        p_y = np.clip(p_base + u, 0.01, 0.99)
        p_x = np.clip(p_base + effect + u, 0.01, 0.99)

        # Binary draws for Y and X
        # shape: (n_worlds, m_per_world)
        y = np_rng.binomial(1, p_y[:, None], size=(n_worlds, m_per_world))
        x = np_rng.binomial(1, p_x[:, None], size=(n_worlds, m_per_world))
        diff = (x - y).astype(np.float64)

        res = cluster_paired_bootstrap(diff, n_boot=n_boot, rng=np_rng, alpha=alpha)
        if res.ci_lower > 0.0:
            rejections += 1

    return float(rejections / n_sim)
