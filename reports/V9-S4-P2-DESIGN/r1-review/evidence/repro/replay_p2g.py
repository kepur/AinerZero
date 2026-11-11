"""P215: replay round G's first main worlds and the first extrapolation world with the registered worker
(worker_p2.init / evaluate_world: all 33 tracking cells, stochastic arms reseeded by the registered rule)
and compare every cell and every dynamics sum with tier1-explore/results-p2g.json.
MLX (CPU) -> run under the shared lock. Usage (repository root): python -I -B <this> results-p2g.json N_MAIN N_EXTRAP"""
import json
import sys

from ainerzero.v9.experiments.s4 import analysis_p2 as P2
from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s4 import worker_p2 as WK

NS = "s4x-p2a"
WDIR = "artifacts/v9/s4/phase1/final-final/weights"
stored = {(r["kind"], r["world"]): r for r in json.load(open(sys.argv[1]))["records"]}
n_main, n_ext = int(sys.argv[2]), int(sys.argv[3])
WK.init({n: f"{WDIR}/{n}.safetensors" for n in WK.weight_names()})
tot = same = 0
for kind, w, d in P2.eval_world_ids((n_main, n_ext)):
    rec = WK.evaluate_world({"kind": kind, "ns": NS, "episode": W.generate_episode(NS, w, d)})
    old = stored[(kind, w)]
    cells_same = {k: rec["cells"][k] == old["cells"][k] for k in old["cells"]}
    tot += len(cells_same); same += sum(cells_same.values())
    print(f"{kind} {w}: cells {len(rec['cells'])} (stored {len(old['cells'])}), identical in every field {sum(cells_same.values())}; "
          f"dyn identical {rec['dyn'] == old['dyn']}; events identical {rec['events'] == old['events']}; kstep identical {rec.get('kstep') == old.get('kstep')}")
    bad = [k for k, v in cells_same.items() if not v]
    if bad:
        print("   differing cells:", bad)
    stoch = [k for k in rec["cells"] if k.split("#")[0] in ("L-sc-g", "L-int-rand")]
    print("   stochastic cells:", {k: rec["cells"][k]["ids_sha256"][:12] for k in stoch})
print(f"total cells {tot}, identical {same}")
