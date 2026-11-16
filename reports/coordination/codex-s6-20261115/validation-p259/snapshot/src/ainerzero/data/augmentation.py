"""Optional byte relabeling for a preregistered C0 training comparison.

The same bijection covers all observations, next-observation targets, and cells
within one sampled window. It changes byte identities, without providing any
world rule or changing actions. Callers must opt in; sampling never applies it.
"""

from __future__ import annotations

import numpy as np


def permute_symbols(
    batch: dict[str, np.ndarray], rng: np.random.Generator
) -> dict[str, np.ndarray]:
    """Copy a batch and independently relabel each sample's visible bytes.

    ``symbols`` must have shape ``[B, T+1, 8]`` and integer values in 0..255.
        ``visible_mask`` must have the same shape and a Boolean dtype. The returned
        symbols use int32, including when a narrower input dtype cannot hold a
        permuted value. Hidden cells remain zero. Other arrays retain their values
        and dtypes in independent copies. Only the caller's RNG state advances.
    """
    if not isinstance(rng, np.random.Generator):
        raise TypeError("rng must be a numpy.random.Generator")
    if not isinstance(batch, dict):
        raise TypeError("batch must be a dictionary of numpy arrays")
    if "symbols" not in batch or "visible_mask" not in batch:
        raise ValueError("batch requires symbols and visible_mask")
    if any(not isinstance(value, np.ndarray) for value in batch.values()):
        raise TypeError("batch values must be numpy arrays")
    symbols = batch["symbols"]
    visible_mask = batch["visible_mask"]
    if symbols.ndim != 3 or symbols.shape[2] != 8 or 0 in symbols.shape:
        raise ValueError("symbols must have nonempty shape [B, T+1, 8]")
    if not np.issubdtype(symbols.dtype, np.integer):
        raise TypeError("symbols must have an integer dtype, not Boolean")
    if np.any(symbols < 0) or np.any(symbols > 255):
        raise ValueError("symbols must be in the range 0..255")
    if visible_mask.shape != symbols.shape:
        raise ValueError("visible_mask must have the same shape as symbols")
    if visible_mask.dtype != np.bool_:
        raise TypeError("visible_mask must have a Boolean dtype")

    result = {name: values.copy() for name, values in batch.items()}
    transformed = np.zeros(symbols.shape, dtype=np.int32)
    for index in range(symbols.shape[0]):
        permutation = rng.permutation(256)
        visible = visible_mask[index]
        transformed[index][visible] = permutation[symbols[index][visible]]
    result["symbols"] = transformed
    return result
