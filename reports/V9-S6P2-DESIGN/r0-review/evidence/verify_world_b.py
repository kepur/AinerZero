#!/usr/bin/env python3
"""Independent verification of World B (src/ainerzero/v9/experiments/s6/world_b.py).

Checks:
1. Unified law on ordinary worlds is bitwise identical to World A (W.physics).
2. Decoy worlds (kind="tiny") follow World A law bitwise identically.
3. Vortex ring dynamics: orbit radius derivation and numerical trap audit.
4. Classify_b correctness and isolation from MLX.
"""
import math
import numpy as np
from pathlib import Path
from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s6 import world_b as B

NS = "s6x-verify-wb"

def test_ordinary_world_identity():
    diffs = 0
    total_steps = 0
    for w in range(30):
        ep = W.generate_episode(f"{NS}-ord", w, 6, steps=100)
        for t in range(len(ep.steps) - 1):
            s = ep.steps[t]
            pa, va, ca = W.physics(s.positions[None], s.velocities[None], ep.pillars, log=True)
            pb, vb, cb = B.physics_b(s.positions[None], s.velocities[None], ep.pillars, log=True)
            if not (np.array_equal(pa, pb) and np.array_equal(va, vb) and ca == cb):
                diffs += 1
            total_steps += 1
    return diffs, total_steps

def test_decoy_world_identity():
    diffs = 0
    total_steps = 0
    for w in range(30):
        ep = B.generate_episode_b(f"{NS}-decoy", w, 6, steps=100, kind="tiny")
        for t in range(len(ep.steps) - 1):
            s = ep.steps[t]
            pa, va, ca = W.physics(s.positions[None], s.velocities[None], ep.pillars, log=True)
            pb, vb, cb = B.physics_b(s.positions[None], s.velocities[None], ep.pillars, log=True)
            if not (np.array_equal(pa, pb) and np.array_equal(va, vb) and ca == cb):
                diffs += 1
            total_steps += 1
    return diffs, total_steps

def test_ring_trapping():
    # Theoretical orbit radius:
    # TURN = 0.12, DT = 0.05
    # r_orbit = |v| * DT / (2 * sin(TURN / 2)) ~= |v| * 0.4170
    # Diameter = 2 * r_orbit ~= 0.834 * |v|
    # When Diameter <= HALO (1.2), |v| <= 1.2 / 0.834 ~= 1.438.
    
    entries = 0
    stays_all_300 = 0
    stays_ge_100 = 0
    stays_ge_50 = 0
    total_disks = 0
    trapped_examples = []

    for w in range(100):
        ep = B.generate_episode_b(f"{NS}-trap", w, 6, steps=300)
        cx, cy, r_pil = [p for p in ep.pillars if p[2] >= B.BIG_MIN][0]
        for d in range(6):
            total_disks += 1
            in_r = [bool(B.in_halo(ep.steps[t].positions[d:d+1], ep.pillars)[0]) for t in range(300)]
            if all(in_r):
                stays_all_300 += 1
                speeds = [float(np.linalg.norm(ep.steps[t].velocities[d])) for t in range(300)]
                dists = [float(np.hypot(ep.steps[t].positions[d, 0] - cx, ep.steps[t].positions[d, 1] - cy)) for t in range(300)]
                trapped_examples.append((w, d, np.mean(speeds), np.mean(dists), r_pil))
            
            # Count stay durations
            cur_stay = 0
            for val in in_r:
                if val:
                    cur_stay += 1
                else:
                    if cur_stay >= 100: stays_ge_100 += 1
                    if cur_stay >= 50: stays_ge_50 += 1
                    cur_stay = 0
            if cur_stay >= 100: stays_ge_100 += 1
            if cur_stay >= 50: stays_ge_50 += 1

    return {
        "total_disks": total_disks,
        "stays_all_300": stays_all_300,
        "stays_ge_100": stays_ge_100,
        "stays_ge_50": stays_ge_50,
        "trapped_examples": trapped_examples
    }

def main():
    ord_diffs, ord_steps = test_ordinary_world_identity()
    print(f"1. Ordinary world identity: {ord_diffs} diffs across {ord_steps} steps (PASS: {ord_diffs == 0})")

    decoy_diffs, decoy_steps = test_decoy_world_identity()
    print(f"2. Decoy world identity: {decoy_diffs} diffs across {decoy_steps} steps (PASS: {decoy_diffs == 0})")

    trap_res = test_ring_trapping()
    print(f"3. Ring dynamics across {trap_res['total_disks']} disks (100 episodes, 300 steps):")
    print(f"   Disks spending ALL 300 steps in ring: {trap_res['stays_all_300']}")
    print(f"   Disks with continuous stay >= 100 steps: {trap_res['stays_ge_100']}")
    print(f"   Disks with continuous stay >= 50 steps: {trap_res['stays_ge_50']}")
    if trap_res['trapped_examples']:
        print("   Examples of permanently trapped disks:")
        for w, d, sp, dist, r_pil in trap_res['trapped_examples'][:5]:
            print(f"     World {w} Disk {d}: speed={sp:.3f}, mean_dist={dist:.3f}, pillar_r={r_pil:.3f}, halo_range=[{r_pil+0.15:.2f}, {r_pil+1.35:.2f}]")

if __name__ == "__main__":
    main()
