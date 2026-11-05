#!/usr/bin/env python3
"""P22 independent cross-check of P18 r3 (step5-9f2k).

Independent re-implementation: does NOT import the ainerzero package, does NOT
import the r3 scripts, does NOT copy their code. Reads only frozen/sealed inputs.
"""
import hashlib, json, math, re, sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
SNAP = Path("/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot")
DIGEST = "8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
DATASET = REPO / "artifacts/v9/s1/datasets" / DIGEST
TRUTH = DATASET / "truth/development.jsonl"
MANIFEST = DATASET / "dataset_manifest.json"
PREREG = SNAP / "artifacts/v9/s1/phase1/r5/pre_registration.json"
P19 = REPO / "reports/V9-P19/analysis/independent_checks.json"

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()

fails = []
def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got={got!r} want={want!r}")

episodes = [json.loads(l) for l in TRUTH.read_text().splitlines() if l.strip()]
manifest = json.loads(MANIFEST.read_text())
prereg = json.loads(PREREG.read_text())
p19 = json.loads(P19.read_text())

# ---------- shape ----------
steps = [len(e["steps"]) for e in episodes]
trans = [s - 1 for s in steps]
check("episodes", len(episodes), 200)
check("steps_total", sum(steps), 950)
check("manifest development_packets", manifest["counts"]["development_packets"], 950)
check("transitions_total", sum(trans), 750)
check("max_transitions_per_world", max(trans), 6)
fams = {}
for e, t in zip(episodes, trans):
    f = e.get("family")
    fams.setdefault(f, []).append(t)
check("families", sorted(fams), ["e3_identity", "navigation", "relation", "time"])
check("family worlds", {f: len(v) for f, v in sorted(fams.items())},
      {"e3_identity": 50, "navigation": 50, "relation": 50, "time": 50})
check("family transitions", {f: sum(v) for f, v in sorted(fams.items())},
      {"e3_identity": 200, "navigation": 300, "relation": 100, "time": 150})

# ---------- k coverage (own implementation) ----------
QL = 8
def cells_of(e):
    poses = [s["agent_world_pose"]["position"] for s in e["steps"]]
    ox, oz = int(round(float(poses[0][0]))), int(round(float(poses[0][2])))
    return [(int(round(float(p[0]))) - ox, int(round(float(p[2]))) - oz) for p in poses]

kc = {}
for k in (0, 1, 2, 4, 8):
    worlds = queries = hits = short_hits = 0
    by_fam = {}
    for e, t in zip(episodes, trans):
        if t < k + 1:
            continue
        worlds += 1
        q = min(QL, t - k)
        queries += q
        cs = cells_of(e)
        mem = set(cs[: k + 1])
        short = set(cs[:k])  # as-coded exclusive stop: only k-1 transitions -> cells[0..k-1]
        f = e.get("family")
        d = by_fam.setdefault(f, {"worlds": 0, "queries": 0})
        d["worlds"] += 1
        d["queries"] += q
        for j in range(k, k + q):
            if cs[j] in mem:
                hits += 1
            if cs[j] in short:
                short_hits += 1
    kc[k] = {"worlds": worlds, "queries": queries, "hits": hits, "short_hits": short_hits,
             "by_fam": {f: d["worlds"] for f, d in sorted(by_fam.items())}}

check("k worlds", [kc[k]["worlds"] for k in (0, 1, 2, 4, 8)], [200, 200, 150, 50, 0])
check("k queries", [kc[k]["queries"] for k in (0, 1, 2, 4, 8)], [750, 550, 350, 100, 0])
check("k=1 start-in-support", (kc[1]["hits"], round(kc[1]["hits"] / kc[1]["queries"], 4)), (350, 0.6364))
check("k=2 start-in-support", kc[2]["hits"], 200)
check("k=4 start-in-support", kc[4]["hits"], 50)
check("k family composition", {k: sorted(kc[k]["by_fam"]) for k in (0, 1, 2, 4, 8)},
      {0: ["e3_identity", "navigation", "relation", "time"], 1: ["e3_identity", "navigation", "relation", "time"],
       2: ["e3_identity", "navigation", "time"], 4: ["navigation"], 8: []})
check("as-coded short-memory hits k=1/2/4", [kc[k]["short_hits"] for k in (1, 2, 4)], [300, 150, 0])

# ---------- component arithmetic (own) ----------
topo_calls, topo_frames, topo_trans, topo_probe = 200, 950, 750, 200  # P19 measured component_split.topology
fs_calls = sum(kc[k]["worlds"] for k in (1, 2, 4))
fs_trans = sum(kc[k]["worlds"] * k for k in (1, 2, 4))
fs_frames = sum(kc[k]["worlds"] * (k + 1) for k in (1, 2, 4))
fs_probe = sum(kc[k]["worlds"] for k in (0, 1, 2, 4, 8))
fs_encode = 2 * sum(kc[k]["queries"] for k in (0, 1, 2, 4, 8))
m2 = p19["C_repaired_accounting_measured"]["component_split"]["m2_interference"]
check("topology from P19", (topo_calls, topo_frames, topo_trans, topo_probe),
      (p19["C_repaired_accounting_measured"]["component_split"]["topology"]["step_sequence_calls"],
       p19["C_repaired_accounting_measured"]["component_split"]["topology"]["step_sequence_frames"],
       p19["C_repaired_accounting_measured"]["component_split"]["topology"]["single_step_forward_calls"],
       p19["C_repaired_accounting_measured"]["component_split"]["topology"]["probe_graph_calls"]))
check("m2 from P19", (m2["step_sequence_calls"], m2["single_step_forward_calls"], m2["step_sequence_transitions"], m2["step_sequence_frames"]), (11, 42, 42, 53))
check("step_sequence 611", topo_calls + fs_calls + m2["step_sequence_calls"], 611)
check("single_step 1492", topo_trans + fs_trans + m2["single_step_forward_calls"], 1492)
check("probe_graph 800", topo_probe + fs_probe, 800)
check("encode 3500", fs_encode, 3500)
check("few-shot derived", (fs_calls, fs_trans, fs_frames, fs_probe, fs_encode), (400, 700, 1100, 600, 3500))
prt = p19["C_repaired_accounting_measured"]["per_run_total"]
check("P19 repaired per_run_total", (prt["step_sequence_calls"], prt["single_step_forward_calls"], prt["probe_graph_calls"], prt["encode_calls"]), (611, 1492, 800, 3500))
check("P19 repaired stop_frames", topo_frames + fs_frames + m2["step_sequence_frames"], prt["step_sequence_frames"])
asc = p19["B_as_coded_accounting_measured"]["per_run_total"]
check("P19 as-coded per_run_total", (asc["step_sequence_calls"], asc["single_step_forward_calls"], asc["probe_graph_calls"], asc["encode_calls"]), (212, 792, 400, 1500))
wp = p19["C_repaired_accounting_measured"]["component_split"]["window_probes"]
check("window_probes 175/5x35", (wp["forward_loss_calls"], wp["forward_loss_frames"]), (175, 8250))
check("windows 550 == transitions-episodes", sum(trans) - len(episodes), 550)
check("35 == ceil(550/16)", math.ceil(550 / 16), 35)

# ---------- budget (own arithmetic, values parsed from frozen prereg) ----------
t = prereg["timing"]; proto = prereg["training_protocol"]; be = prereg["budget_estimate"]
step = t["measured_step_seconds"]; d_step = be["arm1_step_seconds"]
duty = proto["duty_cycle"]; eb = proto["eval_batches"]; ckpt = len(proto["checkpoint_fractions"])
target = proto["target_estimate_seconds"]; upd = proto["updates"]
df = t["deadline_factor"]; smoke_gen = t["smoke"]["data_generation_seconds"]
spec_text = (SNAP / "src/ainerzero/v9/experiments/s1/spec.py").read_text()
cmds_text = (SNAP / "src/ainerzero/v9/experiments/s1/commands.py").read_text()
wk_text = (SNAP / "src/ainerzero/v9/experiments/s1/worker.py").read_text()
oh = float(re.search(r'"estimate_eval_overhead_factor":\s*([0-9.]+)', spec_text).group(1))
sup_extra = float(re.search(r'"supervision_extra_seconds":\s*([0-9.]+)', spec_text).group(1))
prep_eval = float(re.search(r'PREP_BUDGET\s*=\s*\{[^}]*"eval":\s*([0-9.]+)', cmds_text).group(1))
res_cap = float(re.search(r"active_seconds=min\(([0-9.]+),", wk_text).group(1))
res_floor = float(re.search(r"active_seconds=min\([0-9.]+,\s*max\(([0-9.]+),", wk_text).group(1))
res_share = float(re.search(r"active_seconds=min\([0-9.]+,\s*max\([0-9.]+,\s*([0-9.]+)\s*\*\s*budget\)\)", wk_text).group(1))
check("overhead/duty/step/eval_batches", (oh, duty, step, eb), (1.2, 0.25, 0.0069624580000891, 48))
check("supervision_extra / prep_eval / reserve", (sup_extra, prep_eval, res_cap, res_floor, res_share), (50.0, 300.0, 120.0, 10.0, 0.5))
update_cost = 3.0 * step
eval_cost = eb * step * ckpt
raw_updates = math.floor((target * duty / oh - eval_cost) / update_cost)
estimate = (upd * update_cost + eval_cost) / duty * oh
deadline = math.ceil(df * estimate)
supervision = deadline + sup_extra
arm1_active = eb * d_step * ckpt
arm1 = arm1_active / duty * oh
arm1_deadline = math.ceil(df * arm1)
arm1_sup = arm1_deadline + sup_extra
phase_wall = 9 * deadline + 1 * arm1_deadline + smoke_gen
cap = t["phase_wall_max_seconds"]
headroom = cap - phase_wall
check("raw_updates", raw_updates, 3510)
check("estimate", round(estimate, 10), round(359.9312287726061, 10))
check("deadline/supervision", (deadline, supervision), (450, 500))
check("arm1 active/estimate/deadline/sup", (round(arm1_active, 11), round(arm1, 10), arm1_deadline, arm1_sup), (0.31284984005, 1.5016792322, 2, 52))
check("phase_wall", round(phase_wall, 9), 4099.605202459)
check("headroom", round(headroom, 9), 10300.394797541)
check("eval ledger reserve 120", min(res_cap, max(res_floor, res_share * prep_eval)), 120.0)
check("eval supervisor timeout 350", prep_eval + sup_extra, 350.0)
check("static 9x300", round(phase_wall + 9 * 300, 9), 6799.605202459)
check("static 9x350", round(phase_wall + 9 * 350, 9), 7249.605202459)
check("static 9x120", round(phase_wall + 9 * 120, 9), 5179.605202459)
check("worst case 9x450+9x350+2", 9 * deadline + 9 * 350 + arm1_deadline, 7202)
check("all below cap", max(phase_wall + 9 * 350, 9 * deadline + 9 * 350 + arm1_deadline) < cap, True)
check("frozen deltas vs prereg", (estimate - be["estimate_seconds"], deadline - be["deadline_seconds"],
      arm1 - be["arm1_estimate_seconds"], phase_wall - t["phase_wall_seconds"], headroom - t["phase_wall_headroom_seconds"]),
      (0.0, 0, 0.0, 0.0, 0.0))
check("48-batch ratios", (round(eval_cost / (35 * step * 5), 3), round(arm1_active / d_step, 1)), (1.371, 240.0))

# ---------- D2 facts ----------
di = prereg["data_identity"]
check("manifest generation_seconds", manifest.get("generation_seconds"), 45.739918708000005)
check("prereg data_identity == manifest", di.get("generation_seconds"), manifest.get("generation_seconds"))
check("prereg smoke value", t["smoke"].get("data_generation_seconds"), 47.605202458999884)
check("smoke created < manifest created < prereg created",
      t["smoke"]["created_unix"] < manifest["created_unix"] < prereg["created_unix"], True)
print("   smoke_created_unix=%s manifest_created_unix=%s prereg_created_unix=%s" %
      (t["smoke"]["created_unix"], manifest["created_unix"], prereg["created_unix"]))

# ---------- frames / hybrids ----------
check("as-coded stop_frames 1003", topo_frames + 0 + m2["step_sequence_frames"], asc["step_sequence_frames"])
check("repaired stop_frames 2103", topo_frames + fs_frames + m2["step_sequence_frames"], 2103)
check("hybrid 1703 decomposition", 950 + 700 + 53, 1703)
check("hybrid 1503 decomposition", 750 + 700 + 53, 1503)
check("hybrid 1903 decomposition", 1100 + 750 + 53, 1903)

# ---------- B1 illustration (own, same stated assumptions) ----------
W, T = 200, 9
b1_fs_queries = {k: min(max(T - k, 0), 8) * W for k in (0, 1, 2, 4, 8)}
b1 = {
    "topology_calls": W,
    "topology_transitions": W * T,
    "few_shot_calls": 4 * W,
    "few_shot_transitions": (1 + 2 + 4 + 8) * W,
    "few_shot_stop_frames": (2 + 3 + 5 + 9) * W,
    "queries_total": sum(b1_fs_queries.values()),
    "probe_graph": W + 5 * W,
    "encode": 2 * sum(b1_fs_queries.values()),
    "step_sequence_total": W + 4 * W + 11,
    "single_step_total": W * T + (1 + 2 + 4 + 8) * W + 42,
}
check("B1 illustration", (b1["topology_calls"], b1["topology_transitions"], b1["few_shot_calls"],
      b1["few_shot_transitions"], b1["queries_total"], b1["probe_graph"], b1["encode"],
      b1["step_sequence_total"], b1["single_step_total"]),
      (200, 1800, 800, 3000, 5800, 1200, 11600, 1011, 4842))
b1_stop_frames_frames_convention = (W * T + W) + b1["few_shot_stop_frames"] + 53  # frames = transitions+1 per world (matches current 950=750+200)
b1_stop_frames_report = 5653
print(f"INFO  B1 stop_frames: report=5653  own(frames convention, 2000+3800+53)={b1_stop_frames_frames_convention}  own(1800+3800+53)={1800 + b1['few_shot_stop_frames'] + 53}")
if b1_stop_frames_report != b1_stop_frames_frames_convention:
    fails.append("B1 stop_frames total (report 5653 vs frames-convention %d)" % b1_stop_frames_frames_convention)

# ---------- P19 per-k sub-block inconsistency ----------
pk = p19["C_repaired_accounting_measured"].get("per_k_calls")
print("INFO  P19 repaired per_k_calls keys:", list(pk.keys()) if isinstance(pk, dict) else type(pk))
if isinstance(pk, dict):
    for k, v in sorted(pk.items()):
        print("   k=%s: %s" % (k, json.dumps(v, sort_keys=True)[:220]))

# ---------- support/query scope ----------
rounds = {int(e.get("round_index", 0)) for e in episodes}
wkeys = {json.dumps(e["world_key"], sort_keys=True) for e in episodes}
check("round_index all 0", rounds, {0})
check("unique world keys == episodes", len(wkeys), 200)
check("manifest rounds_per_world", manifest["counts"].get("rounds_per_world"), 1)

print()
print("TOTAL FAILURES:", len(fails))
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
