PR = "src/ainerzero/v9/experiments/s2/prereg.py"
MUTS = {
 "W7-M1_planning_field_loop_off": (PR, "        if planning.get(key) != expected:\n            raise SpecValidationError(f\"Planning {key} mismatch", "        if False:\n            raise SpecValidationError(f\"Planning {key} mismatch"),
 "W7-M2_probe_field_loop_off": (PR, "        if probe_doc.get(key) != expected:", "        if False:"),
 "W7-M3_old_m_key_allowed": (PR, '    if "replan_m_steps" in planning:', "    if False:"),
}
TESTS = ["tests/v9/experiments/test_s2_prereg.py"]
