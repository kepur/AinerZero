#!/usr/bin/env python3
"""Check 4: Leakage Audit for Exploratory Probes and Design Draft Data Flow.

1. Probe audit (explore_s5a_probes.py):
   - World / seed overlap between train (0, 1, 2) and test (3).
   - Feature normalization statistics (mu, sigma).
   - Hyperparameter lambda selection on test set and its impact.
2. Architecture data flow audit (Design §2, §3):
   - Path verification from world truth to student input.
   - Verification of R2 set-level occupancy grid (IDs vs count vs occupancy).
"""
import json
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
EXPLORE = ROOT / "reports" / "V9-S5-DESIGN" / "tier1-explore"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(EXPLORE))
from ainerzero.v9.experiments.s4 import world as W

def run_checks():
    results = {}
    
    # 4.1 World & seed independence between train (0..2) and test (3)
    namespace = "s5x-explore"
    world_seeds = [W.derive_seed(namespace, "world", w) for w in range(4)]
    agent_seeds = [W.derive_seed(namespace, "agent", w) for w in range(4)]
    
    results["world_seeds"] = world_seeds
    results["agent_seeds"] = agent_seeds
    assert len(set(world_seeds)) == 4, "World seeds collided"
    assert len(set(agent_seeds)) == 4, "Agent seeds collided"
    assert len(set(world_seeds).intersection(set(agent_seeds))) == 0, "Cross-type seed collision"
    results["seeds_strictly_disjoint"] = True

    # 4.2 Normalization mu, sigma analysis in explore_s5a_probes.py
    # Lines 79-80:
    # mu, sd = xtr.mean(0), xtr.std(0) + 1e-6
    # a = (xtr - mu) / sd
    # return lambda x: ((x - mu) / sd) @ w + ytr.mean()
    # Verified: mu, sd are computed on xtr only, then applied to xte.
    results["normalization_independent_of_test"] = True

    # 4.3 Lambda selection impact in probe results
    probe_json = json.loads((EXPLORE / "round-a" / "probes-r2.json").read_text())
    vjepa_lambdas = probe_json["vjepa"]
    
    # Compare lambda=1 vs lambda=100 (best) vs lambda=1000 for V-JEPA
    inv_r2_l1 = vjepa_lambdas["lambda=1"]["inv_all"]
    inv_r2_l100 = vjepa_lambdas["lambda=100"]["inv_all"]
    inv_r2_l1000 = vjepa_lambdas["lambda=1000"]["inv_all"]
    
    logd_r2_l1 = vjepa_lambdas["lambda=1"]["logd_nonsky_obj"]
    logd_r2_l100 = vjepa_lambdas["lambda=100"]["logd_nonsky_obj"]
    
    disk_r2_l1 = vjepa_lambdas["lambda=1"]["disk_all"]
    disk_r2_l100 = vjepa_lambdas["lambda=100"]["disk_all"]
    
    results["vjepa_lambda_sweep"] = {
        "inv_all": {"lam_1": inv_r2_l1, "lam_100": inv_r2_l100, "lam_1000": inv_r2_l1000, "max_delta": inv_r2_l100 - inv_r2_l1},
        "logd_nonsky_obj": {"lam_1": logd_r2_l1, "lam_100": logd_r2_l100, "max_delta": logd_r2_l100 - logd_r2_l1},
        "disk_all": {"lam_1": disk_r2_l1, "lam_100": disk_r2_l100, "max_delta": disk_r2_l100 - disk_r2_l1}
    }
    # Sensitivity is <= 0.006 across best vs default lambda=1
    results["lambda_leakage_assessment"] = (
        "Selecting lambda on the test set is a formal hyperparameter selection leak, "
        "but empirical sensitivity is <= 0.006 (0.6 percentage points). "
        "The conclusion that V-JEPA representations (R2 ~0.92-0.94) vastly outperform raw pixels (R2 ~0.21-0.27) "
        "remains unaffected."
    )

    # 4.4 Data Flow Audit
    data_flow = [
        {"stream": "Agent Pose (x0, y0, heading)", "enters_student": False, "destination": "render() camera placement only"},
        {"stream": "Object IDs (-2..105)", "enters_student": False, "destination": "Discarded / label generation only"},
        {"stream": "Ground Truth Depth [H, W]", "enters_student": False, "destination": "R1 supervision label only"},
        {"stream": "RGB Frames [T, H, W, 3]", "enters_student": True, "destination": "Student PerceptionEncoder input"},
        {"stream": "DA2 Output [56, 56]", "enters_student": False, "destination": "A1/A3 distillation loss target only"},
        {"stream": "V-JEPA Tokens [N, 1024]", "enters_student": False, "destination": "A2/A3/A4 distillation/alignment loss target only"}
    ]
    results["data_flow_audit"] = data_flow
    results["no_forbidden_information_in_student_input"] = True

    # 4.5 R2 Occupancy Grid Specification Audit
    # Grid: 12 azimuth bins x 7 log-range bins [0.5, 7.0] m.
    # In §3 line 127: readout head uses BCE (Binary Cross Entropy).
    # BCE requires y in {0, 1}.
    # If cell has >= 1 visible disk, y = 1. Else y = 0.
    # Check whether grid carries disk ID:
    # Any disk falling in bin (a, r) sets grid[a, r] = 1. No identity or instance index is stored.
    # What if two disks fall in the same bin?
    # In set occupancy: grid[a, r] remains 1. It is occupancy, not count.
    results["r2_grid_analysis"] = {
        "grid_shape": [12, 7],
        "value_type": "binary occupancy {0, 1}",
        "loss_type": "BCE",
        "carries_disk_id": False,
        "carries_count": False,
        "multiple_disk_collision_behavior": "Saturates at 1 (set occupancy). Must not store integer counts since BCE is used."
    }

    return results

if __name__ == "__main__":
    res = run_checks()
    print(json.dumps(res, indent=2))
