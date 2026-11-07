PE = "src/ainerzero/v9/experiments/s2/probe_eval.py"
MUTS = {
 "W6b-M1_holdout_optional": (PE, "    holdout_idx = {int(w) for w in get_holdout_world_indices(root)}", "    holdout_idx = set()"),
 "W6b-M2_flat_fallback": (PE, '        raise FileNotFoundError(f"no world_NNNN directories under {root}")', "        return [(0, ep) for ep in sorted(root.glob('*.json'))]"),
 "W6b-M3_k_literal": (PE, "    k: int = spec.PROBE_GATE_STEP,", "    k: int = 1,"),
}
TESTS = ["tests/v9/experiments/test_s2_probe_eval.py"]
