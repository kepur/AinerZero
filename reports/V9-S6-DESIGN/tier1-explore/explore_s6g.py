#!/usr/bin/env python3
"""S6 exploration round G: the r1 review found that the candidate pool of rounds C-F held only 29245
distinct states of 60000 (make_pool draws with replacement), so top-k arms picked duplicates (~7000
distinct experiments of 12000) and trained on them twice. This round reruns the arms on the
deduplicated pool of DESIGN-r2 (distinct (world, step) pairs, outcomes simulated on reveal), through the
formal modules (s6/cells.py, s6/sandbox.py, s6/epinet_mlx.py), one replicate, full sizes.

Usage (MLX; under the shared lock):
  explore_s6g.py <cand_ns> <test_ns> <arms,comma> <out.json> [k]
Weights go to artifacts/v9/s6/explore/<cand_ns>-r<k>/<arm>/ (not evidence; the JSON is).
Test worlds: 30 main (6 disks, worlds 0-29) and 15 extrapolation (10 disks, worlds 1000-1014).
"""
import json
import sys
import time
from pathlib import Path

import mlx.core as mx
import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s6 import cells as C

REPO = Path(__file__).resolve().parents[3]


def main():
    cand_ns, test_ns, arms, out = sys.argv[1], sys.argv[2], sys.argv[3].split(","), Path(sys.argv[4])
    k = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    t0 = time.time()
    source = C.candidate_source(cand_ns, k)
    print(f"pool {C.n_states(source)} distinct states, {time.time() - t0:.0f}s", flush=True)
    wdir = REPO / f"artifacts/v9/s6/explore/{cand_ns}-r{k}"
    ids = A.eval_world_ids((30, 15))
    tests = {"main6": [C.prepare_world(W.generate_episode(test_ns, w, n)) for kind, w, n in ids if kind == "main"],
             "extrap10": [C.prepare_world(W.generate_episode(test_ns, w, n)) for kind, w, n in ids if kind == "extrap"]}
    counts = {t: np.stack([C.world_counts(tw)[0] for tw in v]) for t, v in tests.items()}
    eb = {t: np.array([C.world_counts(tw)[1] for tw in v]) for t, v in tests.items()}
    res = {"cand_ns": cand_ns, "test_ns": test_ns, "replicate": k, "sizes": C.FULL.__dict__, "arms": {}}
    for arm in arms:
        d = wdir / arm
        if (d / "cell.json").is_file():
            rec = C.verify_cell_dir(d)
        else:
            rec = C.run_cell(arm, k, source, d, cand_ns=cand_ns, say=lambda *a: print(*a, flush=True))
        mx.set_default_device(mx.cpu)
        cp = C.make_candidate_pool(source)
        shares = []
        for tr in rec["tracks"][:1]:
            for r, picks in enumerate(tr["picks"]):
                got = cp.reveal(np.array(picks, dtype=np.int64))
                shares.append(float(np.mean(np.concatenate([e["contact"].sum((1, 2)) > 0 for e in got.by_n.values()]))))
        row = {"seconds": rec["seconds"], "contact_share_by_round": shares, "rounds": []}
        for r in range(C.FULL.rounds):
            per = {}
            for t, tws in tests.items():
                sums = np.zeros((C.N_LEARNERS, len(tws), 4))
                for j in range(C.N_LEARNERS):
                    m = C.load_model(arm, d / f"r{r}-n{j}.safetensors")
                    for w, tw in enumerate(tws):
                        sums[j, w] = C.world_sums(m, tw)
                S, Cn, B = sums.sum(1), counts[t].sum(0), eb[t].sum()
                per[t] = {"D": float(np.mean(1 - S[:, 0] / B)), "D_per_net": (1 - S[:, 0] / B).tolist(),
                          **{name: float(np.mean(S[:, c] / Cn[c])) for c, name in enumerate(C.KINDS)},
                          "all": float(np.mean(S.sum(1) / Cn.sum())), "sums": sums.tolist()}
            row["rounds"].append(per)
            m6, x10 = per["main6"], per["extrap10"]
            print(f"{arm} round {r} main6 D={m6['D']:.3f} {['%.3f' % x for x in m6['D_per_net']]} graze={m6['graze']:.4f} "
                  f"wall={m6['wall_pillar']:.4f} free={m6['free']:.4f} all={m6['all']:.4f} | extrap10 D={x10['D']:.3f}  "
                  f"{time.time() - t0:.0f}s", flush=True)
        print(f"{arm} contact share of picks by round {['%.3f' % s for s in shares]}", flush=True)
        res["arms"][arm] = row
        res["counts"] = {t: v.tolist() for t, v in counts.items()}
        res["eb"] = {t: v.tolist() for t, v in eb.items()}
        out.write_text(json.dumps(res), encoding="utf-8")
        mx.set_default_device(mx.gpu)
    print(f"total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
