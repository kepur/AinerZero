ER = "src/ainerzero/v9/experiments/s2/eval_runner.py"
MUTS = {
 "W3r3-M3_default_plan_choice_back": (ER, '        raise ValueError(f"frozen plan config has no plan_choice for arm {arm_name!r}")', '        return {"H": 32}'),
 "W3r3-M4_c_choice_default_back": (ER, '''        if c_cfg_info is None:
            raise ValueError(''', '''        if c_cfg_info is None:
            c_cfg_info = {"plan_choice": {"macro_horizon": 6, "budget_ratio": 0.5}}
        if False:
            raise ValueError('''),
}
TESTS = ["tests/v9/experiments/test_s2_eval_runner.py"]
