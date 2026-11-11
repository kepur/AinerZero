"""Tier-1 spot check of P212: per-world reappearance events from regenerated worlds vs worlds.jsonl (P212 compared totals only)."""
import json, sys
from pathlib import Path
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s4 import world as W
recs = [json.loads(l) for l in (REPO / "artifacts/v9/s4/phase1/final-final/worlds.jsonl").read_text().splitlines()]
bad = 0
for r in recs:
    ep = W.generate_episode("s4p1-final", r["world"], r["n_disks"], allow_registered=True)
    touched = [{c for ck, ci, cj in s.contacts if ck == "disk" for c in (ci, cj)} for s in ep.steps]
    ev = []
    for k in range(ep.n_disks):
        last = None
        for t, s in enumerate(ep.steps):
            if not s.visible[k]:
                continue
            if last is not None and t - last >= 2 and k in set(ep.steps[last].truth_ids) and k in set(s.truth_ids):
                ev.append([k, last, t, int(any(k in touched[u] for u in range(last, t)))])
            last = t
    if sorted(ev) != sorted(r["events"]):
        bad += 1
        if bad <= 3: print("mismatch", r["kind"], r["world"], len(ev), len(r["events"]))
print("worlds", len(recs), "per-world event mismatches", bad, "events", sum(len(r["events"]) for r in recs))
