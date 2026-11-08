import sys, time, tempfile
from pathlib import Path
import numpy as np, mlx.core as mx
from ainerzero.v9.experiments.s2 import smoke, adapters_mlx, spec, learned_planning, eval as s2_eval
from ainerzero.v9.experiments.s2.fwd_counter import ForwardCounter
root = Path(tempfile.mkdtemp(dir=sys.argv[1]))
_, batches, layout_specs = smoke.generate_smoke_partition(output_root=root, seed_namespace=smoke.SMOKE_SEED_NAMESPACE)
print("n layout_specs", len(layout_specs))
L=[]
for item in layout_specs[:3]:
    L.append(item if isinstance(item, tuple) else (item.get("layout"), item.get("spec") or item))
for arm_id in ("arm_a","arm_b","arm_c"):
    arm = adapters_mlx.make_mlx_arm(arm_id); arm.init(seed=42)
    kind = learned_planning.arm_kind_of(arm_id)
    for dev in ("gpu","cpu","gpu","cpu"):
        mx.set_default_device(mx.gpu if dev=="gpu" else mx.cpu)
        plan_fn = learned_planning.make_plan_fn(arm, arm_id, spec.SMOKE_PLAN_CHOICE[kind], spec.N_FWD)
        ts=[]; info=[]
        for i,(layout, sd) in enumerate(L):
            t=time.perf_counter()
            r = s2_eval.run_episode(layout=layout, spec=sd, plan_fn=plan_fn, counter=ForwardCounter(budget=spec.N_FWD), rng=42+i, m=1, catch_budget_exceeded=True)
            ts.append(round(time.perf_counter()-t,2)); info.append((r.success, r.steps_used, r.max_steps))
        print(arm_id, dev, ts, "median", round(float(np.median(ts)),2), info)
    mx.set_default_device(mx.gpu)
