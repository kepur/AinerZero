"""Closed-form parameter count formulas and NumPy layer-by-layer reference (ainerzero.V9.P124).

Implements exact parameter counting for S2 model arms (A, B, C) per DESIGN-r2.md Appendix A.
All three arms are designed and tuned to land within 300k +/- 10% ([270,000, 330,000]).

Architecture components:
- Linear layer: weight (out_features, in_features) + bias (out_features,)
- GRU cell: matching MLX / repository pilot_model convention (Wx, Wh, b, bhn)
- LayerNorm: optional / design choice (2 * normalized_shape if affine, 0 in S2 MLPs)
- Reference counting: constructs pure NumPy empty arrays of exact parameter shapes and sums sizes.
"""

from __future__ import annotations

from typing import Any, Mapping
import numpy as np

from . import spec


# --- Primitive Parameter Formulas ---


def linear_params(in_features: int, out_features: int, bias: bool = True) -> int:
    """Closed-form parameter count for a standard Linear layer.

    Weight shape: (out_features, in_features)
    Bias shape: (out_features,) if bias else none
    """
    if in_features < 1 or out_features < 1:
        raise ValueError(f"Invalid linear dimensions: in={in_features}, out={out_features}")
    weight_count = in_features * out_features
    bias_count = out_features if bias else 0
    return weight_count + bias_count


def gru_params(input_size: int, hidden_size: int, bias: bool = True) -> int:
    """Closed-form parameter count for MLX / repository GRUCell.

    Parameter layout:
    - Wx: (3 * hidden_size, input_size)
    - Wh: (3 * hidden_size, hidden_size)
    - b:  (3 * hidden_size,) if bias
    - bhn: (hidden_size,) if bias
    Total parameters = 3 * hidden_size * (input_size + hidden_size) + (4 * hidden_size if bias else 0)
    """
    if input_size < 1 or hidden_size < 1:
        raise ValueError(f"Invalid GRU dimensions: input={input_size}, hidden={hidden_size}")
    weight_count = 3 * hidden_size * (input_size + hidden_size)
    bias_count = 4 * hidden_size if bias else 0
    return weight_count + bias_count


def layer_norm_params(normalized_shape: int, elementwise_affine: bool = True) -> int:
    """Closed-form parameter count for LayerNorm.

    Design choice in S2 (DESIGN-r2.md Appendix A):
    LayerNorm is omitted from the S2 MLP/GRU architectures to avoid unnecessary
    parameter overhead and maintain direct parity with LeWM and pilot models.
    This formula returns 2 * normalized_shape if affine is enabled, else 0.
    """
    if normalized_shape < 1:
        raise ValueError(f"Invalid LayerNorm dimension: {normalized_shape}")
    return 2 * normalized_shape if elementwise_affine else 0


# --- Closed-Form Arm Parameter Counters ---


def count_arm_a_closed_form(dims: Mapping[str, Any] | None = None) -> int:
    """Count parameters of Arm A (flat RSSM) using closed-form formula.

    Components:
    1. Shared E1 encoder:
       - Linear(e1_input -> e1_hidden)
       - Linear(e1_hidden -> e1_output)
    2. GRU deterministic recurrence:
       - Input: [z_{t-1}(latent_dim), a(4), dt(1)]
       - Hidden: gru_hidden
    3. Prior head p(z|h):
       - Linear(gru_hidden -> prior_hidden)
       - Linear(prior_hidden -> 2 * latent_dim)
    4. Posterior head q(z|h, E1(o)):
       - Linear((gru_hidden + e1_output) -> posterior_hidden)
       - Linear(posterior_hidden -> 2 * latent_dim)
    5. Decoder [h, z] -> o:
       - Linear((gru_hidden + latent_dim) -> decoder_hidden)
       - Linear(decoder_hidden -> e1_input)
    """
    cfg = dict(dims if dims is not None else spec.ARM_DIMS["arm_a"])
    e1_in = int(cfg["e1_input"])
    e1_h = int(cfg["e1_hidden"])
    e1_out = int(cfg["e1_output"])
    z_dim = int(cfg["latent_dim"])
    gru_in = int(cfg["gru_input"])
    gru_h = int(cfg["gru_hidden"])
    prior_h = int(cfg["prior_hidden"])
    post_h = int(cfg["posterior_hidden"])
    dec_h = int(cfg["decoder_hidden"])

    # E1
    e1_count = linear_params(e1_in, e1_h) + linear_params(e1_h, e1_out)
    # GRU
    gru_count = gru_params(gru_in, gru_h)
    # Prior head (outputs mean and std: 2 * z_dim)
    prior_count = linear_params(gru_h, prior_h) + linear_params(prior_h, 2 * z_dim)
    # Posterior head
    post_count = linear_params(gru_h + e1_out, post_h) + linear_params(post_h, 2 * z_dim)
    # Decoder
    dec_count = linear_params(gru_h + z_dim, dec_h) + linear_params(dec_h, e1_in)

    return e1_count + gru_count + prior_count + post_count + dec_count


def count_arm_b_closed_form(dims: Mapping[str, Any] | None = None) -> int:
    """Count parameters of Arm B (flat JEPA, LeWM style) using closed-form formula.

    Components:
    1. Shared E1 encoder:
       - Linear(e1_input -> e1_hidden)
       - Linear(e1_hidden -> e1_output)
    2. Residual predictor P1:
       - Linear(p1_input -> p1_hidden_1)
       - Linear(p1_hidden_1 -> p1_hidden_2)
       - Linear(p1_hidden_2 -> p1_output)
    3. Inverse Dynamics Model IDM:
       - Linear(idm_input -> idm_hidden)
       - Linear(idm_hidden -> idm_output)
    """
    cfg = dict(dims if dims is not None else spec.ARM_DIMS["arm_b"])
    e1_in = int(cfg["e1_input"])
    e1_h = int(cfg["e1_hidden"])
    e1_out = int(cfg["e1_output"])
    p1_in = int(cfg["p1_input"])
    p1_h1 = int(cfg["p1_hidden_1"])
    p1_h2 = int(cfg["p1_hidden_2"])
    p1_out = int(cfg["p1_output"])
    idm_in = int(cfg["idm_input"])
    idm_h = int(cfg["idm_hidden"])
    idm_out = int(cfg["idm_output"])

    e1_count = linear_params(e1_in, e1_h) + linear_params(e1_h, e1_out)
    p1_count = (
        linear_params(p1_in, p1_h1)
        + linear_params(p1_h1, p1_h2)
        + linear_params(p1_h2, p1_out)
    )
    idm_count = linear_params(idm_in, idm_h) + linear_params(idm_h, idm_out)

    return e1_count + p1_count + idm_count


def count_arm_c_closed_form(dims: Mapping[str, Any] | None = None) -> int:
    """Count parameters of Arm C (two-layer hierarchical H-JEPA) using closed-form formula.

    Components:
    1. Layer 1 (identical to Arm B structure, configured with 256 hidden width):
       - E1: Linear(e1_input -> e1_hidden) + Linear(e1_hidden -> e1_output)
       - P1: Linear(p1_input -> p1_hidden_1) + Linear(p1_hidden_1 -> p1_hidden_2) + Linear(p1_hidden_2 -> p1_output)
       - IDM1: Linear(idm_input -> idm_hidden) + Linear(idm_hidden -> idm_output)
    2. Layer 2 (macro dynamics across s2 steps):
       - E2: Linear(e2_input -> e2_hidden) + Linear(e2_hidden -> z2_dim)
       - P2: Linear(p2_input -> p2_hidden) + Linear(p2_hidden -> p2_output)
       - IDM2: Linear(idm2_input -> idm2_hidden) + Linear(idm2_hidden -> idm2_output)
    """
    cfg = dict(dims if dims is not None else spec.ARM_DIMS["arm_c"])
    # Layer 1
    e1_in = int(cfg["e1_input"])
    e1_h = int(cfg["e1_hidden"])
    e1_out = int(cfg["e1_output"])
    p1_in = int(cfg["p1_input"])
    p1_h1 = int(cfg["p1_hidden_1"])
    p1_h2 = int(cfg["p1_hidden_2"])
    p1_out = int(cfg["p1_output"])
    idm_in = int(cfg["idm_input"])
    idm_h = int(cfg["idm_hidden"])
    idm_out = int(cfg["idm_output"])

    layer1_count = (
        linear_params(e1_in, e1_h)
        + linear_params(e1_h, e1_out)
        + linear_params(p1_in, p1_h1)
        + linear_params(p1_h1, p1_h2)
        + linear_params(p1_h2, p1_out)
        + linear_params(idm_in, idm_h)
        + linear_params(idm_h, idm_out)
    )

    # Layer 2
    e2_in = int(cfg["e2_input"])
    e2_h = int(cfg["e2_hidden"])
    z2_dim = int(cfg["z2_dim"])
    p2_in = int(cfg["p2_input"])
    p2_h = int(cfg["p2_hidden"])
    p2_out = int(cfg["p2_output"])
    idm2_in = int(cfg["idm2_input"])
    idm2_h = int(cfg["idm2_hidden"])
    idm2_out = int(cfg["idm2_output"])

    layer2_count = (
        linear_params(e2_in, e2_h)
        + linear_params(e2_h, z2_dim)
        + linear_params(p2_in, p2_h)
        + linear_params(p2_h, p2_out)
        + linear_params(idm2_in, idm2_h)
        + linear_params(idm2_h, idm2_out)
    )

    return layer1_count + layer2_count


def count_all_arms_closed_form(
    arm_dims: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, int]:
    """Calculate parameter counts for all three arms using closed-form formulas."""
    table = arm_dims if arm_dims is not None else spec.ARM_DIMS
    return {
        "arm_a": count_arm_a_closed_form(table["arm_a"]),
        "arm_b": count_arm_b_closed_form(table["arm_b"]),
        "arm_c": count_arm_c_closed_form(table["arm_c"]),
    }


# --- NumPy Layer-by-Layer Reference Implementation ---


def count_arm_a_numpy_reference(dims: Mapping[str, Any] | None = None) -> int:
    """NumPy reference parameter counting for Arm A by creating exact array shapes."""
    cfg = dict(dims if dims is not None else spec.ARM_DIMS["arm_a"])
    e1_in, e1_h, e1_out = int(cfg["e1_input"]), int(cfg["e1_hidden"]), int(cfg["e1_output"])
    z_dim = int(cfg["latent_dim"])
    gru_in, gru_h = int(cfg["gru_input"]), int(cfg["gru_hidden"])
    prior_h = int(cfg["prior_hidden"])
    post_h = int(cfg["posterior_hidden"])
    dec_h = int(cfg["decoder_hidden"])

    tensors: list[np.ndarray] = [
        # E1
        np.empty((e1_h, e1_in)),
        np.empty((e1_h,)),
        np.empty((e1_out, e1_h)),
        np.empty((e1_out,)),
        # GRU (Wx, Wh, b, bhn)
        np.empty((3 * gru_h, gru_in)),
        np.empty((3 * gru_h, gru_h)),
        np.empty((3 * gru_h,)),
        np.empty((gru_h,)),
        # Prior
        np.empty((prior_h, gru_h)),
        np.empty((prior_h,)),
        np.empty((2 * z_dim, prior_h)),
        np.empty((2 * z_dim,)),
        # Posterior
        np.empty((post_h, gru_h + e1_out)),
        np.empty((post_h,)),
        np.empty((2 * z_dim, post_h)),
        np.empty((2 * z_dim,)),
        # Decoder
        np.empty((dec_h, gru_h + z_dim)),
        np.empty((dec_h,)),
        np.empty((e1_in, dec_h)),
        np.empty((e1_in,)),
    ]
    return sum(int(t.size) for t in tensors)


def count_arm_b_numpy_reference(dims: Mapping[str, Any] | None = None) -> int:
    """NumPy reference parameter counting for Arm B by creating exact array shapes."""
    cfg = dict(dims if dims is not None else spec.ARM_DIMS["arm_b"])
    e1_in, e1_h, e1_out = int(cfg["e1_input"]), int(cfg["e1_hidden"]), int(cfg["e1_output"])
    p1_in = int(cfg["p1_input"])
    p1_h1, p1_h2 = int(cfg["p1_hidden_1"]), int(cfg["p1_hidden_2"])
    p1_out = int(cfg["p1_output"])
    idm_in, idm_h, idm_out = int(cfg["idm_input"]), int(cfg["idm_hidden"]), int(cfg["idm_output"])

    tensors: list[np.ndarray] = [
        # E1
        np.empty((e1_h, e1_in)),
        np.empty((e1_h,)),
        np.empty((e1_out, e1_h)),
        np.empty((e1_out,)),
        # P1
        np.empty((p1_h1, p1_in)),
        np.empty((p1_h1,)),
        np.empty((p1_h2, p1_h1)),
        np.empty((p1_h2,)),
        np.empty((p1_out, p1_h2)),
        np.empty((p1_out,)),
        # IDM
        np.empty((idm_h, idm_in)),
        np.empty((idm_h,)),
        np.empty((idm_out, idm_h)),
        np.empty((idm_out,)),
    ]
    return sum(int(t.size) for t in tensors)


def count_arm_c_numpy_reference(dims: Mapping[str, Any] | None = None) -> int:
    """NumPy reference parameter counting for Arm C by creating exact array shapes."""
    cfg = dict(dims if dims is not None else spec.ARM_DIMS["arm_c"])
    # Layer 1
    e1_in, e1_h, e1_out = int(cfg["e1_input"]), int(cfg["e1_hidden"]), int(cfg["e1_output"])
    p1_in = int(cfg["p1_input"])
    p1_h1, p1_h2 = int(cfg["p1_hidden_1"]), int(cfg["p1_hidden_2"])
    p1_out = int(cfg["p1_output"])
    idm_in, idm_h, idm_out = int(cfg["idm_input"]), int(cfg["idm_hidden"]), int(cfg["idm_output"])

    # Layer 2
    e2_in, e2_h, z2_dim = int(cfg["e2_input"]), int(cfg["e2_hidden"]), int(cfg["z2_dim"])
    p2_in, p2_h, p2_out = int(cfg["p2_input"]), int(cfg["p2_hidden"]), int(cfg["p2_output"])
    idm2_in, idm2_h, idm2_out = int(cfg["idm2_input"]), int(cfg["idm2_hidden"]), int(cfg["idm2_output"])

    tensors: list[np.ndarray] = [
        # Layer 1 E1
        np.empty((e1_h, e1_in)),
        np.empty((e1_h,)),
        np.empty((e1_out, e1_h)),
        np.empty((e1_out,)),
        # Layer 1 P1
        np.empty((p1_h1, p1_in)),
        np.empty((p1_h1,)),
        np.empty((p1_h2, p1_h1)),
        np.empty((p1_h2,)),
        np.empty((p1_out, p1_h2)),
        np.empty((p1_out,)),
        # Layer 1 IDM
        np.empty((idm_h, idm_in)),
        np.empty((idm_h,)),
        np.empty((idm_out, idm_h)),
        np.empty((idm_out,)),
        # Layer 2 E2
        np.empty((e2_h, e2_in)),
        np.empty((e2_h,)),
        np.empty((z2_dim, e2_h)),
        np.empty((z2_dim,)),
        # Layer 2 P2
        np.empty((p2_h, p2_in)),
        np.empty((p2_h,)),
        np.empty((p2_out, p2_h)),
        np.empty((p2_out,)),
        # Layer 2 IDM2
        np.empty((idm2_h, idm2_in)),
        np.empty((idm2_h,)),
        np.empty((idm2_out, idm2_h)),
        np.empty((idm2_out,)),
    ]
    return sum(int(t.size) for t in tensors)


def count_all_arms_numpy_reference(
    arm_dims: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, int]:
    """Calculate parameter counts for all three arms using NumPy reference accumulation."""
    table = arm_dims if arm_dims is not None else spec.ARM_DIMS
    return {
        "arm_a": count_arm_a_numpy_reference(table["arm_a"]),
        "arm_b": count_arm_b_numpy_reference(table["arm_b"]),
        "arm_c": count_arm_c_numpy_reference(table["arm_c"]),
    }
