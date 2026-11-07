ER = "src/ainerzero/v9/experiments/s2/eval_runner.py"
MUTS = {
 "W3r3-M1_collusion_gate_off": (ER, "        collusion = bool(drop < subgoal_drop_threshold)", "        collusion = False"),
 "W3r3-M2_sensitivity_gate_off": (ER, "        if sens < sensitivity_threshold:\n            unplannable_arms.append(arm_name)", "        if False:\n            unplannable_arms.append(arm_name)"),
 "W3r3-M3_default_plan_choice_back": (ER, '        raise ValueError(f"frozen plan config has no plan_choice for arm {arm_name!r}")', '        return {"H": 32}'),
}
TESTS = ["tests/v9/experiments/test_s2_production_e2e.py", "tests/v9/experiments/test_s2_eval_runner.py"]
