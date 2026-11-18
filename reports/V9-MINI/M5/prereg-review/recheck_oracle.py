import json
import time
from pathlib import Path
from ainerzero.v9.mini import agents as A, evaluate as E, world as W

ROOT = Path(__file__).resolve().parents[4]
orig_json_path = ROOT / "reports/V9-MINI/M5/prefreeze/oracle_check.json"
orig_data = json.loads(orig_json_path.read_text())

N_LAYOUTS, SEEDS = 80, range(5)
out = {}
t0 = time.time()
for world, cfg in (("m1", W.Config()), ("m2", W.Config(ice_rooms=2, portals=2))):
    for s in SEEDS:
        tasks = E.make_tasks(cfg, N_LAYOUTS, 400, 2, 4, eval_seed0=8_100_000 + 1000 * s)
        ok = 0
        for ti, t in enumerate(tasks):
            layout = W.make_layout(t["layout_seed"], cfg)
            ag = A.Oracle(layout, (t["goal"][0], t["goal"][1]), seed=ti)
            ok += E.run_episode(layout, t, ag, 2 * t["d_star"] + 20)["success"]
        longs = [t for t in tasks if t["kind"] == "long"]
        law = [t for t in tasks if t["law_relevant"]]
        k = f"{world}-s{s}"
        out[k] = {"tasks": len(tasks), "oracle_success": ok, "long": len(longs),
                  "long_layouts": len({t["layout_seed"] for t in longs}),
                  "law_relevant": len(law), "law_layouts": len({t["layout_seed"] for t in law})}
        print(f"Computed {k}: {out[k]}, Elapsed: {time.time()-t0:.1f}s", flush=True)

mismatches = []
for k in orig_data:
    if k not in out:
        mismatches.append(f"Missing key {k}")
    elif orig_data[k] != out[k]:
        mismatches.append(f"Mismatch in {k}: orig={orig_data[k]} vs computed={out[k]}")

if not mismatches:
    print(f"\nALL 10 runs match oracle_check.json EXACTLY! Total time: {time.time()-t0:.1f}s")
    Path(__file__).with_name("recheck_oracle.json").write_text(json.dumps(out, indent=1))
else:
    print("MISMATCHES FOUND:", mismatches)
    sys.exit(1)
