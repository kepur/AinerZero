"""Independent pure in-memory label recomputation for S4 Phase 2 final.

Regenerates all 300 worlds (200 main + 100 extrap) for namespace 's4p2-final'
in memory with allow_registered=True, extracts reappearance events and
contact classifications, and verifies 100% item-by-item match against
artifacts/v9/s4/phase2/final-final/labels.jsonl and worlds.jsonl.
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

# Add src to sys.path
REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import analysis_p2 as P2

LABELS_PATH = REPO / "artifacts/v9/s4/phase2/final-final/labels.jsonl"
WORLDS_PATH = REPO / "artifacts/v9/s4/phase2/final-final/worlds.jsonl"

def events_from_log(log):
    """Recompute reappearance events from label_log format (same logic as verify_labels_p2.py)."""
    vis = [[c == "1" for c in row] for row in log["visible"]]
    det = [set(d) for d in log["detected"]]
    touched = []
    for pairs in log["disk_contacts"]:
        s = set()
        for i, j in pairs:
            s.add(i)
            s.add(j)
        touched.append(s)
    out = []
    for k in range(log["n_disks"]):
        last = None
        for t in range(len(vis)):
            if not vis[t][k]:
                continue
            if last is not None and t - last >= 2 and k in det[last] and k in det[t]:
                out.append([k, last, t, int(any(k in touched[s] for s in range(last, t))), t - last - 1])
            last = t
    n_coll = sum(len(touched[s]) for s in range(len(touched) - 1))
    return out, n_coll


def main():
    t0 = time.time()
    print("=== Item 3: Independent In-Memory Label Recomputation ===")
    print(f"Reading recorded labels: {LABELS_PATH}")
    with open(LABELS_PATH, encoding="utf-8") as f:
        recorded_labels = [json.loads(line) for line in f]
    print(f"Loaded {len(recorded_labels)} recorded label records.")

    print(f"Reading recorded worlds: {WORLDS_PATH}")
    with open(WORLDS_PATH, encoding="utf-8") as f:
        recorded_worlds = [json.loads(line) for line in f]
    print(f"Loaded {len(recorded_worlds)} recorded world records.")

    eval_ids = P2.eval_world_ids([200, 100])
    assert len(eval_ids) == 300, f"Expected 300 eval world ids, got {len(eval_ids)}"

    mismatches = []

    # Distribution accumulators
    mem_main_event_counts = []
    mem_extrap_event_counts = []
    mem_main_coll_counts = []
    mem_extrap_coll_counts = []

    mem_main_gap_counter = Counter()
    rec_main_gap_counter = Counter()
    mem_extrap_gap_counter = Counter()
    rec_extrap_gap_counter = Counter()

    total_mem_events = 0
    total_rec_events = 0
    total_mem_coll_events = 0
    total_rec_coll_events = 0

    print("Generating 300 worlds in memory with allow_registered=True and recomputing...")

    for i, (kind, w_idx, n_disks) in enumerate(eval_ids):
        # 1. Regenerate episode in memory
        ep = W.generate_episode("s4p2-final", w_idx, n_disks, allow_registered=True)
        assert ep.world_index == w_idx
        assert ep.n_disks == n_disks

        # 2. Compute label log in memory
        mem_log = A.label_log(kind, ep)
        rec_log = recorded_labels[i]

        # Check label log identical
        if mem_log != rec_log:
            mismatches.append(f"World {kind}:{w_idx} label_log differs from recorded labels.jsonl")

        # 3. Extract events via both W.reappearances and events_from_log
        w_events = W.reappearances(ep)
        # Convert W.reappearances to list format: [k, a, b, int(collision), gap]
        w_events_list = sorted([[e["k"], e["a"], e["b"], int(e["collision"]), e["gap"]] for e in w_events])

        log_events, log_n_coll = events_from_log(mem_log)
        log_events_sorted = sorted(log_events)

        if w_events_list != log_events_sorted:
            mismatches.append(f"World {kind}:{w_idx} W.reappearances differs from log_events")

        # 4. Compare with recorded worlds.jsonl events
        rec_world = recorded_worlds[i]
        rec_events = sorted(rec_world["events"])

        if w_events_list != rec_events:
            mismatches.append(f"World {kind}:{w_idx} events differ from recorded worlds.jsonl")

        # 5. Check collision disk steps n_coll
        rec_n_coll = rec_world["dyn"]["E-B"]["n_coll"]
        if log_n_coll != rec_n_coll:
            mismatches.append(f"World {kind}:{w_idx} n_coll mismatch: mem {log_n_coll} vs rec {rec_n_coll}")

        # Accumulate distribution stats
        n_ev = len(w_events_list)
        n_cev = sum(e[3] for e in w_events_list)
        total_mem_events += n_ev
        total_rec_events += len(rec_events)
        total_mem_coll_events += n_cev
        total_rec_coll_events += sum(e[3] for e in rec_events)

        if kind == "main":
            mem_main_event_counts.append(n_ev)
            mem_main_coll_counts.append(n_cev)
            for e in w_events_list:
                mem_main_gap_counter[e[4]] += 1
            for e in rec_events:
                rec_main_gap_counter[e[4]] += 1
        else:
            mem_extrap_event_counts.append(n_ev)
            mem_extrap_coll_counts.append(n_cev)
            for e in w_events_list:
                mem_extrap_gap_counter[e[4]] += 1
            for e in rec_events:
                rec_extrap_gap_counter[e[4]] += 1

        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/300 worlds...")

    t1 = time.time()
    print(f"\nRecomputation completed in {t1 - t0:.2f} s.")
    print(f"Total mismatches: {len(mismatches)}")
    if mismatches:
        print("First 10 mismatches:")
        for m in mismatches[:10]:
            print(f"  - {m}")
    else:
        print("ALL 300 WORLDS MATCHED PERFECTLY (0 MISMATCHES).")

    print("\n--- Event Count Distribution ---")
    print(f"Main worlds (200):")
    print(f"  Total events: in-memory={sum(mem_main_event_counts)}, recorded={sum(len(r['events']) for r in recorded_worlds if r['kind']=='main')}")
    print(f"  Mean events per world: {sum(mem_main_event_counts)/len(mem_main_event_counts):.2f}")
    print(f"  Min / Median / Max: {min(mem_main_event_counts)} / {sorted(mem_main_event_counts)[100]} / {max(mem_main_event_counts)}")
    print(f"Extrap worlds (100):")
    print(f"  Total events: in-memory={sum(mem_extrap_event_counts)}, recorded={sum(len(r['events']) for r in recorded_worlds if r['kind']=='extrap')}")
    print(f"  Mean events per world: {sum(mem_extrap_event_counts)/len(mem_extrap_event_counts):.2f}")
    print(f"  Min / Median / Max: {min(mem_extrap_event_counts)} / {sorted(mem_extrap_event_counts)[50]} / {max(mem_extrap_event_counts)}")

    print("\n--- Collision vs Non-Collision Distribution ---")
    print(f"Main worlds (200):")
    print(f"  Collision events: in-memory={sum(mem_main_coll_counts)}, recorded={sum(rec_main_gap_counter.values()) - (sum(mem_main_event_counts)-sum(mem_main_coll_counts))}")
    print(f"  Non-collision events: in-memory={sum(mem_main_event_counts)-sum(mem_main_coll_counts)}")
    print(f"  Collision event ratio: {sum(mem_main_coll_counts)/sum(mem_main_event_counts):.4f}")
    print(f"Extrap worlds (100):")
    print(f"  Collision events: in-memory={sum(mem_extrap_coll_counts)}")
    print(f"  Non-collision events: in-memory={sum(mem_extrap_event_counts)-sum(mem_extrap_coll_counts)}")
    print(f"  Collision event ratio: {sum(mem_extrap_coll_counts)/sum(mem_extrap_event_counts):.4f}")

    print("\n--- Hidden Length (Gap) Distribution ---")
    print("Main worlds gap breakdown (in-memory vs recorded):")
    bins = [(1, 9), (10, 24), (25, 49), (50, 999)]
    for low, high in bins:
        mem_b = sum(c for g, c in mem_main_gap_counter.items() if low <= g <= high)
        rec_b = sum(c for g, c in rec_main_gap_counter.items() if low <= g <= high)
        print(f"  Gap [{low:2d}, {high:3d}]: in-memory={mem_b:4d}, recorded={rec_b:4d}, diff={mem_b - rec_b}")

    print("Extrap worlds gap breakdown (in-memory vs recorded):")
    for low, high in bins:
        mem_b = sum(c for g, c in mem_extrap_gap_counter.items() if low <= g <= high)
        rec_b = sum(c for g, c in rec_extrap_gap_counter.items() if low <= g <= high)
        print(f"  Gap [{low:2d}, {high:3d}]: in-memory={mem_b:4d}, recorded={rec_b:4d}, diff={mem_b - rec_b}")

    assert len(mismatches) == 0, f"Found {len(mismatches)} mismatches!"
    print("\n>>> CONCLUSION: ITEM 3 VERIFICATION PASSED (逐项一致，无歧义).")


if __name__ == "__main__":
    main()
