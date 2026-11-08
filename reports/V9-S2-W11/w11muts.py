WD = "src/ainerzero/v9/experiments/s2/world.py"
SP = "src/ainerzero/v9/experiments/s2/spec.py"
MUTS = {
 "W11-M1_cap_hardcoded_5": (WD, "        max_world_redraws = int(spec.MAX_REDRAW_RETRIES)\n", "        max_world_redraws = 5\n"),
 "W11-M2_spec_override_dropped": (SP, "MAX_REDRAW_RETRIES = 30\n", "MAX_REDRAW_RETRIES = 5\n"),
 "W11-M3_threshold_hardcoded": (WD, "    limit = float(spec.MAX_REJECTION_RATE) if threshold is None else float(threshold)\n", "    limit = 0.30 if threshold is None else float(threshold)\n"),
 "W11-M4_threshold_loosened_in_prepare": (WD, "        rejection_threshold = float(spec.MAX_REJECTION_RATE)\n", "        rejection_threshold = 0.5\n"),
 "W11-M5_no_cap_guard": (WD, "    if int(max_world_redraws) < 1:\n", "    if False:\n"),
}
TESTS = ["tests/v9/experiments/test_s2_world_redraw.py"]
