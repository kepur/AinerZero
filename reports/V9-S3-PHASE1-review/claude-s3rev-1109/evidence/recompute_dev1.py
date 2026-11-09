"""从 dev1.json 的 cells 复算 result；核对分子是否为整数（分母取自只读生成的 dev 事件数）。P208 第二路。"""
import json, numpy as np, sys
d = json.load(open("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S3-PHASE1/dev1.json"))
C, R = d["cells"], d["result"]
S = (1, 2, 3); MAIN = ("A0","A1","A2","A3"); ALL = MAIN + ("O","N")
DEN = {"f1": (321, 260), "f1_after_f2": (321, 260), "f2": (355, 253)}
bad_int, rows = [], {}
for k, c in C.items():
    for st, (np_, nu) in DEN.items():
        if st not in c: continue
        if c[st]["n_primary"] != np_: bad_int.append((k, st, "n_primary", c[st]["n_primary"]))
        for field, n in (("primary", np_), ("unswapped", nu)):
            v = c[st][field] * n
            if abs(v - round(v)) > 1e-6: bad_int.append((k, st, field, v))
print("non_integer_numerators", bad_int)
pool = lambda arm, f: sum(C[f"{arm}/{s}"]["f1"][f] * C[f"{arm}/{s}"]["f1"]["n_primary"] for s in S) / sum(C[f"{arm}/{s}"]["f1"]["n_primary"] for s in S) if f == "primary" else np.mean([C[f"{arm}/{s}"]["f1"][f] for s in S])
prim = {a: pool(a, "primary") for a in ALL}; uns = {a: pool(a, "unswapped") for a in ALL}
drops = {a: float(np.mean([C[f"{a}/{s}"]["f1"]["primary"] - C[f"{a}/{s}"]["f1_after_f2"]["primary"] for s in S])) for a in MAIN}
def close(a, b): return abs(a - b) < 1e-12
print("primary_match", {a: close(prim[a], R["primary"][a]) for a in ALL})
print("unswapped_match", {a: close(uns[a], R["unswapped"][a]) for a in ALL})
print("h1_delta", prim["A2"] - prim["A1"], R["h1"]["delta"], close(prim["A2"] - prim["A1"], R["h1"]["delta"]))
print("h2_delta", prim["A3"] - prim["A2"], R["h2"]["delta"], close(prim["A3"] - prim["A2"], R["h2"]["delta"]))
print("h3_drop_match", {a: close(drops[a], R["h3_drop"][a]) for a in MAIN})
F = 1/7 + 0.03
leg = {"floor_A0": prim["A0"] <= F, "upper_O": prim["O"] >= 0.9, "negative_N": prim["N"] <= F, "unswapped_A2": uns["A2"] >= .8, "unswapped_A3": uns["A3"] >= .8}
print("legality_match", leg == R["legality"], "valid", all(leg.values()), R["valid"])
print("h1_pass_rule", prim["A2"] - prim["A1"] >= .10, "h2_fails_on_delta_alone", prim["A3"] - prim["A2"] < .05)
print("per_seed_A2_minus_A1", [round(C[f"A2/{s}"]["f1"]["primary"] - C[f"A1/{s}"]["f1"]["primary"], 4) for s in S])
print("per_seed_A3_minus_A2", [round(C[f"A3/{s}"]["f1"]["primary"] - C[f"A2/{s}"]["f1"]["primary"], 4) for s in S])
print("h3_pass_match", {a: (drops[a] <= .05) == R["h3_pass"][a] for a in MAIN})
print("unswapped_f1_after_f2_collapse", {a: [round(C[f"{a}/{s}"]["f1_after_f2"]["unswapped"], 3) for s in S] for a in MAIN})
print("per_event_keys_in_dev1", [k for k in C["A2/1"]["f1"].keys()], "(no per-event arrays; bootstrap CI not recomputable)")
