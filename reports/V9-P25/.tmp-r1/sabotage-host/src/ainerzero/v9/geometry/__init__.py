"""S0 analytical geometry; NumPy only, no learned parameters or model imports."""
from .belief import KnownRotationGaussian, TangentGaussian, bounded_translation_update, covariance
from .gravity import GravityFrame
from .lie import SE2, SE3, boxminus, boxplus, skew, tangent_jacobian
from .pose_graph import (
    ObservabilityError,
    PoseGraphResult,
    RelativeFactor,
    linear_translation_error_bound,
    solve_pose_graph,
)

__all__ = [
    "SE2", "SE3", "boxplus", "boxminus", "skew", "tangent_jacobian",
    "TangentGaussian", "KnownRotationGaussian", "bounded_translation_update", "covariance", "GravityFrame",
    "ObservabilityError", "PoseGraphResult", "RelativeFactor",
    "solve_pose_graph", "linear_translation_error_bound",
]
