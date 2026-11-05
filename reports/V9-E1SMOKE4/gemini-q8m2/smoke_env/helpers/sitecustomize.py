"""Helper sitecustomize to inject data generation counts & capture metadata."""
from __future__ import annotations
import json, os

try:
    from ainerzero.v9.experiments.e1 import worker
    _orig_gen = worker.DefaultCellRunner.run_generate_data
    def _patched_gen(self, data_dir, output_root, clock_fn, deadline, budget, **kwargs):
        c = os.environ.get("E1_SMOKE_COUNTS")
        if c and "counts" not in kwargs:
            kwargs["counts"] = json.loads(c)
        return _orig_gen(self, data_dir, output_root, clock_fn, deadline, budget, **kwargs)
    worker.DefaultCellRunner.run_generate_data = _patched_gen
except ImportError:
    pass

try:
    from ainerzero.v9.experiments.e1 import arms_nonnet, eval_runner

    _orig_arm5_predict = arms_nonnet.IdentifyArm.predict
    def _patched_arm5_predict(self, observed_prefix, static_env, n_future, **kwargs):
        res = _orig_arm5_predict(self, observed_prefix, static_env, n_future, **kwargs)
        self.last_identified_subspace_dim = getattr(res, "identified_subspace_dim", None)
        return res
    arms_nonnet.IdentifyArm.predict = _patched_arm5_predict

    _orig_eval_ep = eval_runner.evaluate_episode
    def _patched_eval_ep(arm, student_ep, truth_ep, arm_name=None):
        res = _orig_eval_ep(arm, student_ep, truth_ep, arm_name=arm_name)
        if hasattr(arm, "last_identified_subspace_dim") and arm.last_identified_subspace_dim is not None:
            res["identified_subspace_dim"] = arm.last_identified_subspace_dim
        return res
    eval_runner.evaluate_episode = _patched_eval_ep
except ImportError:
    pass
