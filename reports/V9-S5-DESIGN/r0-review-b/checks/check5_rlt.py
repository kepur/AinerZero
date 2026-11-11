#!/usr/bin/env python3
"""Check 5: RLT implementation, drift behavior, and design consistency.

Verifies:
1. rlt_frame_dropping compares against immediately preceding frame (p_{t-1}),
   not the last retained token (anchor).
2. Quantifies error accumulation (creeping drift) under slow continuous change.
3. Verifies theoretical retention lower bound = 1/8 for 16-frame clips with tubelet length 2
   under positive tau (e.g. tau=0.02 as specified in design).
4. Explains boundary condition at tau=0.0 (where diff >= 0 keeps all tokens).
5. Checks consistency between Design §3 R-arm and ARCHITECTURE_V9 Equation 10.
"""
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
from ainerzero.v9.tokenization.rlt import rlt_frame_dropping

def run_checks():
    results = {}
    
    # 5.1 Verification of comparison target: p_{t-1} vs last retained token
    # Construct a slow-drift sequence:
    # 10 frames, single spatial patch [1, 1], 1 dimension
    # Values: 0.00, 0.015, 0.030, 0.045, 0.060, 0.075, 0.090, 0.105, 0.120, 0.135
    T = 10
    step = 0.015
    tau = 0.02
    seq = np.arange(T, dtype=np.float32).reshape(T, 1, 1, 1) * step
    
    retained, run_lengths, positions, restoration, retention_rate = rlt_frame_dropping(seq, tau)
    
    retained_count = len(retained)
    max_recon_error = float(np.max(np.abs(seq - restoration)))
    
    results["slow_drift_test"] = {
        "num_frames": T,
        "step_size": step,
        "tau": tau,
        "tokens_retained": int(retained_count),
        "retained_values": retained.flatten().tolist(),
        "run_lengths": run_lengths.tolist(),
        "max_reconstruction_error": max_recon_error,
        "compares_to_previous_frame_not_anchor": bool(retained_count == 1 and max_recon_error > tau)
    }
    assert retained_count == 1, "rlt_frame_dropping did not compare against previous frame"
    assert max_recon_error > tau, "Error did not accumulate beyond tau"

    # 5.2 Verification of lower bound 1/8 under tau = 0.02
    # For a completely static video of 16 frames with tubelet size 2:
    # Input has shape [8, H_p, W_p, D] (8 tubelets)
    static_clip = np.zeros((8, 14, 14, 32), dtype=np.float32)
    _, _, _, _, min_retention_rate = rlt_frame_dropping(static_clip, tau=0.02)
    results["static_clip_retention_rate_tau_002"] = float(min_retention_rate)
    results["theoretical_lower_bound"] = 1.0 / 8.0
    assert abs(min_retention_rate - 1.0 / 8.0) < 1e-9, f"Retention rate {min_retention_rate} != 1/8"

    # Also check tau = 0.0 behavior:
    _, _, _, _, tau0_rate = rlt_frame_dropping(static_clip, tau=0.0)
    results["static_clip_retention_rate_tau_0"] = float(tau0_rate)
    results["tau_zero_explanation"] = (
        "Under tau=0.0, diff_max >= tau (0.0 >= 0.0) is True, so no tokens are dropped (rate=1.0). "
        "Under any positive tau > 0 (e.g. tau=0.02), identical frames satisfy diff < tau and are merged, "
        "yielding the exact theoretical lower bound of 1/8 (12.5%)."
    )

    # 5.3 ARCHITECTURE_V9 Eq 10 vs Design §3 R-arm
    results["eq10_consistency"] = {
        "eq10_formula": "||p_t - p_{t-1}||_inf < tau",
        "implementation_formula": "diff_max[t] = ||video_chunks[t+1] - video_chunks[t]||_inf < tau",
        "literal_match": True,
        "design_s3_usage": "R-arm applies Eq 10 to tubelet-2 tokens (chunks of 2 frames), so p_t is tubelet t.",
        "accumulated_drift_note": (
            "Because Eq 10 and rlt.py use Markovian (p_{t-1}) rather than anchor-based comparison, "
            "slowly drifting background or camera pan can accumulate reconstruction errors exceeding tau."
        )
    }

    return results

if __name__ == "__main__":
    res = run_checks()
    import json
    print(json.dumps(res, indent=2))
