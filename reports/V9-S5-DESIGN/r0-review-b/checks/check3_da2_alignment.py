#!/usr/bin/env python3
"""Check 3: DA2 Frame Alignment and render.py parameter audit.

Design §2 states:
- DA2 rendered at 518 x 392 with focal length f = 196 px.
- Central 392 x 392 corresponds exactly to student 224 x 224 FOV.
- Downsampled to 56 x 56 distillation target.

This check:
1. Proves analytically the pinhole equivalence between student (224x224, f=112)
   and central DA2 crop (392x392, f=196) downsampled to 56x56.
2. Analyzes current render.py implementation and quantifies misalignment if
   render(width=518, height=392) is called without focal length control.
3. Specifies exact parameters required to fix render.py.
"""
import math
import numpy as np

def run_checks():
    results = {}
    
    # --- 1. Analytic pinhole verification ---
    # Student: W=224, H=224, FOV=90 deg
    f_student = 112.0
    fov_student_h = 2 * math.atan((224 / 2) / f_student)
    fov_student_v = 2 * math.atan((224 / 2) / f_student)
    
    # DA2 design specification: W=518, H=392, f=196.0
    f_da2_target = 196.0
    w_da2, h_da2 = 518, 392
    crop_w, crop_h = 392, 392
    
    # FOV of central 392 x 392 crop in DA2 with f=196:
    fov_da2_crop_h = 2 * math.atan((crop_w / 2) / f_da2_target)
    fov_da2_crop_v = 2 * math.atan((crop_h / 2) / f_da2_target)
    
    results["student_f"] = f_student
    results["student_fov_h_deg"] = math.degrees(fov_student_h)
    results["student_fov_v_deg"] = math.degrees(fov_student_v)
    results["da2_crop_fov_h_deg"] = math.degrees(fov_da2_crop_h)
    results["da2_crop_fov_v_deg"] = math.degrees(fov_da2_crop_v)
    
    # Verify FOVs match 90 deg exactly
    assert abs(math.degrees(fov_student_h) - 90.0) < 1e-9
    assert abs(math.degrees(fov_da2_crop_h) - 90.0) < 1e-9
    assert abs(math.degrees(fov_student_v) - 90.0) < 1e-9
    assert abs(math.degrees(fov_da2_crop_v) - 90.0) < 1e-9
    
    # Check 56x56 grid alignment:
    # Student: 224 / 56 = 4 px per grid cell. Bin i in [0..55], center = 4 * (i + 0.5) = 4*i + 2.
    # DA2 crop: 392 / 56 = 7 px per grid cell. Bin i in [0..55], center = 7 * (i + 0.5) = 7*i + 3.5.
    max_tan_diff = 0.0
    for i in range(56):
        col_s_center = 4 * i + 2.0 - 112.0   # offset from student optical axis
        tan_theta_s = col_s_center / f_student
        
        col_d_crop_center = 7 * i + 3.5 - 196.0 # offset from DA2 optical axis
        tan_theta_d = col_d_crop_center / f_da2_target
        
        diff = abs(tan_theta_s - tan_theta_d)
        if diff > max_tan_diff:
            max_tan_diff = diff
            
    results["max_tan_theta_discrepancy_56x56"] = float(max_tan_diff)
    assert max_tan_diff < 1e-12, f"Angular mismatch in 56x56 grid: {max_tan_diff}"

    # --- 2. Flaw in current render.py ---
    # In current render.py:
    # f = (width / 2) / math.tan(FOV / 2) with FOV = 90 deg (math.tan(45 deg) = 1.0).
    # If render(width=518, height=392) is called:
    f_current_render = 518 / 2.0  # = 259.0
    fov_current_h = 2 * math.atan((518 / 2.0) / f_current_render)  # 90 deg
    fov_current_v = 2 * math.atan((392 / 2.0) / f_current_render)  # ~74.22 deg
    fov_crop_current_h = 2 * math.atan((392 / 2.0) / f_current_render) # ~74.22 deg
    
    results["current_render_f_for_518"] = f_current_render
    results["current_render_crop_fov_deg"] = math.degrees(fov_crop_current_h)
    
    # Pixel error at bin 55 (corner of 56x56 token map):
    # Desired ray angle theta = atan(27.5 / 28) ≈ 44.485 deg
    # In current render.py, this ray projects to col offset:
    # x = f_current_render * tan(theta) = 259.0 * (27.5 / 28.0) = 254.38 px
    # But central crop assumes it is at 7 * (55.5) - 196 = 192.5 px
    # Error in DA2 pixels:
    pixel_error_da2 = 254.375 - 192.5
    token_error_56 = pixel_error_da2 / 7.0
    
    results["current_render_pixel_error_edge"] = float(pixel_error_da2)
    results["current_render_token_error_edge"] = float(token_error_56)
    
    # --- 3. Solution specification ---
    results["recommended_signature"] = (
        "def render(agent, positions, pillars, *, width=224, height=224, f=None, return_ids=False, texture=False):"
    )
    results["recommended_logic"] = (
        "if f is None: f = (width / 2.0) / math.tan(FOV / 2.0)"
    )
    
    return results

if __name__ == "__main__":
    res = run_checks()
    import json
    print(json.dumps(res, indent=2))
