#!/usr/bin/env python3
"""Independent recalculation of negative controls and CPU numerical parity for T54:
1. Negative controls (frame_order_adverse):
   Loads raw prediction.safetensors from predictions/ and GT from r2-calib-fixtures/.
   Computes S_clean and S_bad using score = rotation_error_rad + norm(translation_residual3) + depth_abs_rel.
   Computes required_margin = max(0.0001, 0.1 * S_clean).
   Computes turned_red = S_bad >= S_clean + required_margin.
   Compares against calibration_evidence.json within 1e-9 tolerance.
2. CPU parity:
   Loads MPS reference and CPU predictions.
   Recalculates max_abs and failed_elements for depth, confidence, extrinsics, intrinsics.
   Compares with calibration_evidence.json.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LOG_FILE = HERE / "logs" / "recalculate_adverse_and_parity.log"

sys.path.insert(0, str(REPO / "src"))

import numpy as np
from safetensors.numpy import load_file
import ainerzero.v9.teachers.da3_calibration_math as M

EVIDENCE_PATH = REPO / "reports" / "V9-T54" / "calibration_evidence.json"
FIXTURES_DIR = REPO / "reports" / "V9-T6" / "r2-calib-fixtures" / "t6-analytic-room-00"
PRED_DIR = REPO / "reports" / "V9-T54" / "predictions"


def main():
    log = []
    log.append("=== Independent Recalculation: Negative Controls & CPU Parity ===")

    ev = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))

    # Load Ground Truth fixtures
    gt_c2w = [np.load(FIXTURES_DIR / f"view-{i}/camera_to_world.npy") for i in range(3)]
    gt_depths = [np.load(FIXTURES_DIR / f"view-{i}/depth_camera_z.npy") for i in range(3)]

    # 1. Negative controls recalculation
    log.append("\n--- Part 1: Negative Controls (frame_order_adverse) Recalculation ---")
    for variant in ["DA3-SMALL", "DA3-BASE"]:
        log.append(f"\nVariant: {variant}")
        clean_file = PRED_DIR / variant / "calibration" / "t6-analytic-room-00" / "prediction.safetensors"
        bad_file = PRED_DIR / variant / "frame_order_adverse" / "t6-analytic-room-00" / "prediction.safetensors"

        clean_st = load_file(str(clean_file))
        bad_st = load_file(str(bad_file))

        clean_c2w = M.w2c_to_c2w(clean_st["camera_pose"])
        bad_c2w = M.w2c_to_c2w(bad_st["camera_pose"])

        clean_depths = [clean_st["depth"][i] for i in range(3)]
        bad_depths = [bad_st["depth"][i] for i in range(3)]

        m_clean = M.anchored_residual(gt_c2w, list(clean_c2w), gt_depths, clean_depths)
        m_bad = M.anchored_residual(gt_c2w, list(bad_c2w), gt_depths, bad_depths)

        # Custom explicit score calculation: rotation_error_rad + norm(translation_residual3) + depth_abs_rel
        calc_s_clean = float(m_clean["rotation_error_rad"] + m_clean["translation_residual_norm"] + m_clean["depth_abs_rel"])
        calc_s_bad = float(m_bad["rotation_error_rad"] + m_bad["translation_residual_norm"] + m_bad["depth_abs_rel"])

        # Thresholds: max(0.0001, 0.1 * S_clean)
        calc_margin = max(0.0001, 0.1 * calc_s_clean)
        calc_turned_red = bool(calc_s_bad >= calc_s_clean + calc_margin)

        # Compare with evidence
        ev_adverse = ev["stages"][variant]["frame_order_adverse"]
        ev_s_clean = ev_adverse["S_clean"]
        ev_s_bad = ev_adverse["S_bad"]
        ev_margin = ev_adverse["required_margin"]
        ev_turned_red = ev_adverse["turned_red"]

        log.append(f"  Calculated S_clean:        {calc_s_clean:.16f} | Evidence: {ev_s_clean:.16f}")
        log.append(f"  Calculated S_bad:          {calc_s_bad:.16f} | Evidence: {ev_s_bad:.16f}")
        log.append(f"  Calculated required_margin:{calc_margin:.16f} | Evidence: {ev_margin:.16f}")
        log.append(f"  Calculated turned_red:     {calc_turned_red} | Evidence: {ev_turned_red}")

        assert math.isclose(calc_s_clean, ev_s_clean, abs_tol=1e-9), f"S_clean mismatch in {variant}"
        assert math.isclose(calc_s_bad, ev_s_bad, abs_tol=1e-9), f"S_bad mismatch in {variant}"
        assert math.isclose(calc_margin, ev_margin, abs_tol=1e-9), f"Margin mismatch in {variant}"
        assert calc_turned_red == ev_turned_red, f"turned_red mismatch in {variant}"

    log.append("\nNegative controls recalculation PASSED with <= 1e-9 tolerance.")

    # 2. CPU Parity recalculation
    log.append("\n--- Part 2: CPU Numerical Parity Recalculation ---")
    ev_np = ev["numerical_parity"]

    field_map = {
        "depth": ("depth", "depth"),
        "confidence": ("confidence", "confidence"),
        "extrinsics": ("camera_pose", "camera_pose"),
        "intrinsics": ("intrinsics", "intrinsics"),
    }

    for variant in ["DA3-SMALL", "DA3-BASE"]:
        log.append(f"\nVariant: {variant}")
        ref_file = PRED_DIR / variant / "calibration" / "t6-analytic-room-00" / "prediction.safetensors"
        cpu_file = PRED_DIR / variant / "cpu_parity" / "t6-analytic-room-00" / "prediction.safetensors"

        ref_st = load_file(str(ref_file))
        cpu_st = load_file(str(cpu_file))

        ev_fields = ev_np[variant]["cpu_parity"]["fields"]
        atol = ev_np[variant]["cpu_parity"]["atol"]
        rtol = ev_np[variant]["cpu_parity"]["rtol"]

        for f_name, (k_ref, k_cpu) in field_map.items():
            arr_ref = ref_st[k_ref].astype(np.float64)
            arr_cpu = cpu_st[k_cpu].astype(np.float64)

            diff = np.abs(arr_cpu - arr_ref)
            tol = atol + rtol * np.abs(arr_ref)
            calc_failed = int(np.sum(diff > tol))
            calc_max_abs = float(np.max(diff))
            calc_total = int(arr_ref.size)
            calc_pass = bool(calc_failed == 0)

            ev_f = ev_fields[f_name]
            log.append(f"  Field {f_name}:")
            log.append(f"    max_abs: calculated={calc_max_abs:.18e}, evidence={ev_f['max_abs']:.18e}")
            log.append(f"    failed:  calculated={calc_failed}, evidence={ev_f['failed_elements']}")
            log.append(f"    total:   calculated={calc_total}, evidence={ev_f['total_elements']}")
            log.append(f"    pass:    calculated={calc_pass}, evidence={ev_f['pass']}")

            assert math.isclose(calc_max_abs, ev_f["max_abs"], abs_tol=1e-9), f"max_abs mismatch in {variant}/{f_name}"
            assert calc_failed == ev_f["failed_elements"]
            assert calc_total == ev_f["total_elements"]
            assert calc_pass == ev_f["pass"]

    log.append("\nCPU Parity recalculation PASSED with <= 1e-9 tolerance.")

    out_str = "\n".join(log)
    print(out_str)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(out_str + "\n", encoding="utf-8")
    print("\nRECALCULATE ADVERSE AND PARITY STATUS: PASS")


if __name__ == "__main__":
    main()
