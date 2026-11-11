#!/usr/bin/env python3
"""S4 Phase 1 Final Review: In-Memory Labels Recomputation.
Only imports s4.world to generate worlds in memory by registered seeds.
Does NOT write to artifacts or disk.
Computes:
- Reappearance events: disk k visible and detected at t1, not visible for steps t1+1..t2-1, visible and detected at t2 (t2 - t1 >= 2).
- Collision events: disk k involved in disk-disk contact during t1 <= s < t2.
Compares with:
- artifacts/v9/s4/phase1/final-final/labels.jsonl (visible, detected, disk_contacts)
- artifacts/v9/s4/phase1/final-final/worlds.jsonl (per-world events list)
- reports/V9-S4-PHASE1/final/final.json checks.labels (total events, collision_events)
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s4 import world as W

def main():
    print("=== S4 Phase 1 Final: In-Memory Labels Recomputation ===")
    final_json = json.loads((REPO / "reports/V9-S4-PHASE1/final/final.json").read_text(encoding="utf-8"))
    recorded_checks = final_json["checks"]["labels"]
    labels_on_disk = [json.loads(line) for line in (REPO / "artifacts/v9/s4/phase1/final-final/labels.jsonl").read_text(encoding="utf-8").splitlines()]
    worlds_on_disk = [json.loads(line) for line in (REPO / "artifacts/v9/s4/phase1/final-final/worlds.jsonl").read_text(encoding="utf-8").splitlines()]

    ns = "s4p1-final"
    world_specs = [("main", w, 6) for w in range(200)] + [("extrap", 1000 + w, 10) for w in range(100)]
    assert len(world_specs) == 300
    assert len(labels_on_disk) == 300
    assert len(worlds_on_disk) == 300

    tot_events = 0
    tot_coll_events = 0
    mismatches = []
    events_mismatches = []

    for i, (kind, w, n_disks) in enumerate(world_specs):
        ep = W.generate_episode(ns, w, n_disks, allow_registered=True)
        disk_contacts = [sorted([min(ci, cj), max(ci, cj)] for ck, ci, cj in s.contacts if ck == "disk") for s in ep.steps]
        vis = [s.visible for s in ep.steps]
        det = [set(s.truth_ids) for s in ep.steps]

        touched = []
        for pairs in disk_contacts:
            st = set()
            for ci, cj in pairs:
                st.add(ci); st.add(cj)
            touched.append(st)

        ev = []
        for k in range(ep.n_disks):
            last = None
            for t in range(len(vis)):
                if not vis[t][k]:
                    continue
                if last is not None and t - last >= 2 and k in det[last] and k in det[t]:
                    has_coll = int(any(k in touched[s] for s in range(last, t)))
                    ev.append([k, last, t, has_coll])
                last = t

        tot_events += len(ev)
        tot_coll_events += sum(e[3] for e in ev)

        lbl = labels_on_disk[i]
        if (lbl["kind"], lbl["world"]) != (kind, w):
            mismatches.append(f"World {i} header mismatch: ({kind}, {w}) vs ({lbl['kind']}, {lbl['world']})")

        act_vis = ["".join("1" if x else "0" for x in s.visible) for s in ep.steps]
        if act_vis != lbl["visible"]:
            mismatches.append(f"World {i} ({kind} {w}) visible mask mismatch")

        act_det = [sorted(s.truth_ids.tolist()) for s in ep.steps]
        if act_det != lbl["detected"]:
            mismatches.append(f"World {i} ({kind} {w}) detected identities mismatch")

        if sorted(disk_contacts) != sorted(lbl["disk_contacts"]):
            mismatches.append(f"World {i} ({kind} {w}) disk_contacts mismatch")

        # Per-world events comparison against worlds.jsonl
        disk_ev = worlds_on_disk[i]["events"]
        if sorted(ev) != sorted(disk_ev):
            events_mismatches.append(f"World {i} ({kind} {w}) events mismatch: recomputed {len(ev)} vs on-disk {len(disk_ev)}")

    print(f"Total evaluated worlds:      {len(world_specs)}")
    print(f"Total recomputed events:     {tot_events} (recorded in final.json: {recorded_checks['events']})")
    print(f"Total collision events:      {tot_coll_events} (recorded in final.json: {recorded_checks['collision_events']})")
    print(f"labels.jsonl mismatches:     {len(mismatches)}")
    print(f"worlds.jsonl mismatches:     {len(events_mismatches)}")

    assert tot_events == recorded_checks["events"], "Event count mismatch!"
    assert tot_coll_events == recorded_checks["collision_events"], "Collision event count mismatch!"
    assert len(mismatches) == 0, f"Found labels.jsonl mismatches: {mismatches}"
    assert len(events_mismatches) == 0, f"Found worlds.jsonl mismatches: {events_mismatches}"
    print("=== IN-MEMORY LABELS RECOMPUTATION PASSED 100% ===")

if __name__ == "__main__":
    main()
