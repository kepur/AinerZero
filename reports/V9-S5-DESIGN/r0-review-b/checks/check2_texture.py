#!/usr/bin/env python3
"""Check 2: Texture world-anchoring verification.

Verify that floor checker pattern is anchored to world coordinates:
When agent rotates (heading changes) without translation (x0, y0 constant),
any fixed ground location (Xw, Yw) in the interior of a grid cell maps to
the exact same texture pattern in both frames.
"""
import sys
import math
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
EXPLORE = ROOT / "reports" / "V9-S5-DESIGN" / "tier1-explore"
sys.path.insert(0, str(EXPLORE))
import render as R

def world_to_pixel(Xw, Yw, agent, width=224, height=224, f=112.0, cam_h=0.5):
    """Analytic projection of ground point (Xw, Yw, 0) into camera pixel coordinates."""
    x0, y0, heading = agent
    dx = Xw - x0
    dy = Yw - y0
    phi = math.atan2(dy, dx)
    theta = (phi - heading + math.pi) % (2 * math.pi) - math.pi
    t = math.hypot(dx, dy)
    z = t * math.cos(theta)
    if z <= 0:
        return None, None, None
    col_offset = -f * math.tan(theta)
    c = col_offset + width / 2.0 - 0.5
    row_offset = f * cam_h / z
    r = row_offset + height / 2.0 - 0.5
    return r, c, z

def run_checks():
    results = {}
    x0, y0 = 5.0, 5.0
    heading1 = 0.0
    heading2 = 0.12  # ~6.8 deg turn
    
    agent1 = (x0, y0, heading1)
    agent2 = (x0, y0, heading2)
    
    img1, depth1, ids1 = R.render(agent1, [], [], width=224, height=224, return_ids=True, texture=True)
    img2, depth2, ids2 = R.render(agent2, [], [], width=224, height=224, return_ids=True, texture=True)
    
    # Test a set of interior world ground points (away from integer grid boundaries)
    test_world_points = [
        (6.5, 5.4),
        (6.3, 5.3),
        (7.2, 4.6),
        (5.8, 5.2),
        (6.7, 4.4),
        (7.4, 5.3),
    ]
    
    point_results = []
    for Xw, Yw in test_world_points:
        expected_checker = int((math.floor(Xw) + math.floor(Yw)) % 2)
        
        r1, c1, z1 = world_to_pixel(Xw, Yw, agent1)
        r2, c2, z2 = world_to_pixel(Xw, Yw, agent2)
        
        ir1, ic1 = int(round(r1)), int(round(c1))
        ir2, ic2 = int(round(r2)), int(round(c2))
        
        id1 = ids1[ir1, ic1]
        id2 = ids2[ir2, ic2]
        assert id1 == -1 and id2 == -1, f"Expected floor id -1, got {id1}, {id2}"
        
        # Shade and texture extraction
        shade1 = np.clip(1.0 / (1.0 + 0.08 * depth1[ir1, ic1]), 0.3, 1.0)
        shade2 = np.clip(1.0 / (1.0 + 0.08 * depth2[ir2, ic2]), 0.3, 1.0)
        
        mod1 = float(np.mean(img1[ir1, ic1] / (R.FLOOR * shade1)))
        mod2 = float(np.mean(img2[ir2, ic2] / (R.FLOOR * shade2)))
        
        checker1 = 1 if mod1 > 0.91 else 0
        checker2 = 1 if mod2 > 0.91 else 0
        
        point_results.append({
            "world_pt": [Xw, Yw],
            "expected_checker": expected_checker,
            "frame1_pixel": [ir1, ic1],
            "frame2_pixel": [ir2, ic2],
            "frame1_mod": round(mod1, 4),
            "frame2_mod": round(mod2, 4),
            "frame1_checker": checker1,
            "frame2_checker": checker2,
            "consistent": (checker1 == expected_checker == checker2)
        })
        assert checker1 == expected_checker, f"Pt ({Xw},{Yw}) frame1 checker {checker1} != {expected_checker}"
        assert checker2 == expected_checker, f"Pt ({Xw},{Yw}) frame2 checker {checker2} != {expected_checker}"

    results["tested_points"] = point_results
    results["all_points_world_anchored"] = all(p["consistent"] for p in point_results)
    assert results["all_points_world_anchored"]
    return results

if __name__ == "__main__":
    res = run_checks()
    import json
    print(json.dumps(res, indent=2))
