AD = "src/ainerzero/v9/experiments/s2/adapters_mlx.py"
MK = "def make_mlx_arm(arm_id: str, counter: ForwardCounter | None = None) -> Any:"
RAISE = '            raise RuntimeError("train_step called before init(seed): the registered seed must be set explicitly (W10)")\n'
C_TAIL = '        for k in spec.BATCH_REQUIRED_KEYS:\n            if k not in batch:\n                raise ValueError(f"MLXArmCAdapter.train_step'
MUTS = {
 "W10-M1_device_ignored": (AD, "        with mx.stream(target):\n            return fn(*args, **kwargs)", "        return fn(*args, **kwargs)"),
 "W10-M2_train_on_planning_device": (AD, MK, "MLXArmBAdapter.train_step = _planning_device(MLXArmBAdapter.train_step)\n\n\n" + MK),
 "W10-M3_predict_l2_unwrapped": (AD, "    @_planning_device\n    def predict_l2(", "    def predict_l2("),
 "W10-M4_unknown_device_falls_back": (AD, "            raise ValueError(f\"spec.PLAN_INFERENCE_DEVICE must be 'cpu' or 'gpu', got {device!r}\")", "            target = mx.gpu"),
 "W10-M5_init_no_rebuild_arm_b": (AD, "        mx.random.seed(int(seed))\n        self.model = arms_mlx.FlatJEPAArm()\n", "        mx.random.seed(int(seed))\n"),
 "W10-M6_silent_seed42_fallback_back_arm_c": (AD, RAISE + C_TAIL, "            self.init(seed=42)\n" + C_TAIL),
}
TESTS = ["--native-mlx", "tests/v9/experiments/test_s2_plan_device_native.py"]
