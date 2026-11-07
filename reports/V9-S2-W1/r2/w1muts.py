CM = "src/ainerzero/v9/experiments/s2/commands.py"
TR = "src/ainerzero/v9/experiments/s2/train_runner.py"
MUTS = {
 "W1r2-M1_failed_smoke_ok": (CM, '                if metrics.get("passed") is not True:\n                    return None', "                pass"),
 "W1r2-M2_no_tamper_check": (TR, "    if recorded_worlds != set(expected_holdout):", "    if False:"),
 "W1r2-M3_cadence_5": (TR, "    clock: Callable[[], float] | None = None,\n    eval_every: int = spec.MODEL_SELECTION_EVERY_STEPS,", "    clock: Callable[[], float] | None = None,\n    eval_every: int = 5,"),
 "W1r2-M4_data_dir": (CM, '(Path(output_root) / "datasets" / "train")', '(Path(output_root) / "data")'),
 "W1r2-M5_no_canonical": (CM, "        arm = canonical_arm(arm)\n", "        pass\n"),
 "W1r2-M6_cwd_root": (CM, "        repo_root = Path(__file__).resolve().parents[5]", "        repo_root = Path.cwd().resolve()"),
}
TESTS = ["tests/v9/experiments/test_s2_w1_wiring.py", "tests/v9/experiments/test_s2_wiring.py", "tests/v9/experiments/test_s2_train_runner.py"]
