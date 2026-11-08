import sys, time, tempfile
from pathlib import Path
import numpy as np, mlx.core as mx
from ainerzero.v9.experiments.s2 import smoke, adapters_mlx, spec, learned_planning, eval as s2_eval
from ainerzero.v9.experiments.s2.fwd_counter import ForwardCounter
root = Path(tempfile.mkdtemp(dir=sys.argv[1]))
_, batches, layout_specs = smoke.generate_smoke_partition(output_root=root, seed_namespace=smoke.SMOKE_SEED_NAMESPACE)
L=[(item if isinstance(item, tuple) else (item.get("layout"), item.get("spec") or item)) for item in layout_specs[:3]]
mx.set_default_device(mx.cpu)
for arm_id in ("arm_a","arm_b","arm_c"):
    arm = adapters_mlx.make_mlx_arm(arm_id); arm.init(seed=42)
    kind = learned_planning.arm_kind_of(arm_id)
    med={}
    for nf in spec.N_FWD_DEV_LEVELS:
        plan_fn = learned_planning.make_plan_fn(arm, arm_id, spec.SMOKE_PLAN_CHOICE[kind], nf)
        ts=[]
        for i,(layout, sd) in enumerate(L):
            t=time.perf_counter()
            s2_eval.run_episode(layout=layout, spec=sd, plan_fn=plan_fn, counter=ForwardCounter(budget=nf), rng=42+i, m=1, catch_budget_exceeded=True)
            ts.append(time.perf_counter()-t)
        med[nf]=float(np.median(ts))
    base=med[spec.N_FWD]
    print(arm_id, {k:round(v,2) for k,v in med.items()}, "actual curve multiplier", round(sum(med.values())/base,2), "formula", 1+sum(l/spec.N_FWD for l in spec.N_FWD_DEV_LEVELS if l!=spec.N_FWD))
