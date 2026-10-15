"""B5: evaluator for the GridLab public tracking baselines (truth read only here).

The evaluator receives the tracker outputs after the run, plus evaluator-private
per-step states; nothing it computes is fed back to a tracker.

Mapping: truth object k is mapped to a tracker track at the first step where it is
visible and uniquely matchable, i.e. exactly one observed track of its appearance
sits on its cell and no other same-appearance truth object is visible on that cell.
Steps where that fails because two same-appearance objects share a cell are counted
as ``ambiguous``; nothing is back-filled from the future. The mapping is never
re-assigned, so identity switches cannot be hidden.

Per object/episode counts (all kept, rates are num/den or null when den == 0):
* visible_position: visible steps after mapping where the mapped track is observed
  (L1 error summed) vs. visible steps where it is not (``visible_miss``);
* reappearance: first visible step after >=1 unseen step (after mapping); correct if
  the uniquely matchable observed track on the cell is the mapped track; same-cell
  same-appearance reappearances are counted as ``unidentifiable`` separately;
* id_switches: change of the uniquely matchable observed track id between
  consecutive identified sightings;
* hidden_prediction: unseen steps after mapping; covered if the mapped track still
  outputs a prediction (L1 error over covered steps) plus coverage = covered / steps.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ainerzero.learning import gridlab_tracking as gt

SUBSETS = ("all", "random", "scripted", "occlusion", "similar_objects", "identity_swap", "unseen_paths")
COUNT_KEYS = ("visible_steps", "visible_matched", "visible_miss", "visible_l1_sum",
              "reappearances", "reappearance_correct", "reappearance_unidentifiable",
              "id_switches", "identified_sightings", "hidden_steps", "hidden_covered", "hidden_l1_sum",
              "ambiguous_steps", "unmapped_objects", "objects")


def _rate(num, den):
    return None if den == 0 else num / den


def _cell_tracks(frame, xy, appearance):
    return [t for t in frame["tracks"] if t["observed"] and t["appearance"] == appearance
            and t["xy"] == [float(xy[0]), float(xy[1])]]


def evaluate_episode(outputs: list[dict], private: list[dict]) -> dict:
    if len(outputs) != len(private) or any(o["step"] != p["step"] for o, p in zip(outputs, private)):
        raise ValueError("tracker outputs and truth must cover the same steps")
    counts = dict.fromkeys(COUNT_KEYS, 0)
    per_object = []
    n = len(private[0]["objects"]) if private else 0
    counts["objects"] = n
    for k in range(n):
        c = dict.fromkeys(COUNT_KEYS, 0)
        mapped, prev_visible, last_identified = None, None, None
        for frame, state in zip(outputs, private):
            obj = state["objects"][k]
            visible = obj["visibility"] == "visible"
            same_cell = [o for i, o in enumerate(state["objects"]) if i != k and o["visibility"] == "visible"
                         and o["appearance"] == obj["appearance"] and o["xy"] == obj["xy"]]
            cands = _cell_tracks(frame, obj["xy"], obj["appearance"]) if visible else []
            unique = visible and not same_cell and len(cands) == 1
            if mapped is None:
                if visible and unique:
                    mapped = cands[0]["track_id"]
                elif visible and same_cell:
                    c["ambiguous_steps"] += 1
                if mapped is None:
                    prev_visible = visible
                    continue
                last_identified = mapped
                c["identified_sightings"] += 1
                c["visible_steps"] += 1
                c["visible_matched"] += 1
                prev_visible = True
                continue
            mine = next((t for t in frame["tracks"] if t["track_id"] == mapped), None)
            if visible:
                c["visible_steps"] += 1
                if mine is not None and mine["observed"]:
                    c["visible_matched"] += 1
                    c["visible_l1_sum"] += abs(mine["xy"][0] - obj["xy"][0]) + abs(mine["xy"][1] - obj["xy"][1])
                else:
                    c["visible_miss"] += 1
                if prev_visible is False:
                    c["reappearances"] += 1
                    if same_cell:
                        c["reappearance_unidentifiable"] += 1
                    elif unique and cands[0]["track_id"] == mapped:
                        c["reappearance_correct"] += 1
                if unique:
                    c["identified_sightings"] += 1
                    if last_identified is not None and cands[0]["track_id"] != last_identified:
                        c["id_switches"] += 1
                    last_identified = cands[0]["track_id"]
                elif same_cell:
                    c["ambiguous_steps"] += 1
            else:
                c["hidden_steps"] += 1
                if mine is not None:
                    c["hidden_covered"] += 1
                    c["hidden_l1_sum"] += abs(mine["xy"][0] - obj["xy"][0]) + abs(mine["xy"][1] - obj["xy"][1])
            prev_visible = visible
        if mapped is None:
            c["unmapped_objects"] = 1
        per_object.append({"object_index": k, "mapped_track": mapped,
                           **{key: c[key] for key in COUNT_KEYS if key != "objects"}})
        for key in COUNT_KEYS:
            if key != "objects":
                counts[key] += c[key]
    return {"counts": counts, "per_object": per_object, "metrics": metrics(counts)}


def metrics(counts: dict) -> dict:
    return {
        "visible_position_l1_mean": _rate(counts["visible_l1_sum"], counts["visible_matched"]),
        "visible_match_rate": _rate(counts["visible_matched"], counts["visible_steps"]),
        "reappearance_correct": [counts["reappearance_correct"],
                                 counts["reappearances"] - counts["reappearance_unidentifiable"]],
        "reappearance_correct_rate": _rate(counts["reappearance_correct"],
                                           counts["reappearances"] - counts["reappearance_unidentifiable"]),
        "reappearance_unidentifiable": counts["reappearance_unidentifiable"],
        "id_switches": counts["id_switches"],
        "hidden_prediction_l1_mean": _rate(counts["hidden_l1_sum"], counts["hidden_covered"]),
        "hidden_prediction_coverage": _rate(counts["hidden_covered"], counts["hidden_steps"]),
        "ambiguous_steps": counts["ambiguous_steps"],
        "unmapped_objects": [counts["unmapped_objects"], counts["objects"]],
    }


def episode_subsets(meta: dict) -> list[str]:
    """meta: {scripted: bool, flags: {occlusion, similar_objects}, events: [...], unseen_paths: bool}."""
    out = ["all", "scripted" if meta["scripted"] else "random"]
    flags = meta.get("flags", {})
    if flags.get("occlusion"):
        out.append("occlusion")
    if flags.get("similar_objects"):
        out.append("similar_objects")
    if any(e.get("type") == "identity_swap" for e in meta.get("events", [])):
        out.append("identity_swap")
    if meta.get("unseen_paths"):
        out.append("unseen_paths")
    return out


def aggregate(episodes: list[dict]) -> dict:
    """episodes: [{episode_id, subsets, counts}]. Overlapping subsets; empty -> null."""
    out = {}
    for name in SUBSETS:
        members = [e for e in episodes if name in e["subsets"]]
        if not members:
            out[name] = None
            continue
        counts = {k: sum(e["counts"][k] for e in members) for k in COUNT_KEYS}
        out[name] = {"episodes": [e["episode_id"] for e in members], "counts": counts,
                     "metrics": metrics(counts)}
    out["note"] = "subsets overlap; do not add them up as independent samples"
    return out


def run_baselines(episodes: list[dict]) -> dict:
    """episodes: [{episode_id, public: [...], private: [...], meta: {...}}].

    The tracker is given only ``public``; ``private`` reaches the evaluator only.
    """
    result = {"version": gt.VERSION, "parameters": {"association_l1_max": gt.ASSOCIATION_L1_MAX,
                                                     "retention_ticks": gt.RETENTION_TICKS},
              "source_sha256": source_digests(), "baselines": {}}
    for baseline in gt.BASELINES:
        rows = []
        for ep in episodes:
            outputs = gt.run_tracker(baseline, ep["public"])
            ev = evaluate_episode(outputs, ep["private"])
            rows.append({"episode_id": ep["episode_id"], "subsets": episode_subsets(ep["meta"]),
                         "counts": ev["counts"], "metrics": ev["metrics"], "per_object": ev["per_object"],
                         "tracker_output_sha256": _digest(outputs)})
        result["baselines"][baseline] = {"episodes": rows, "subsets": aggregate(rows)}
    result["capability_gate"] = None  # B4: no model capability pass gate
    return result


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_digests() -> dict:
    here = Path(__file__).resolve().parent
    return {name: hashlib.sha256((here / name).read_bytes()).hexdigest()
            for name in ("gridlab_tracking.py", "gridlab_tracking_eval.py")}
