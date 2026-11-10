"""LT 回退（往回合在这个真值格子上没有任何驻留观察）在探索命名空间上出现多少次；回退时 shown 与 L 是否不同。复核者自写。"""
import json, sys
import numpy as np
sys.path.insert(0, sys.argv[1] + "/src")
from ainerzero.v9.experiments.s3 import analysis_p3 as A, persist as PS, promotion as PR
n_q = n_fb = n_fb_diff = 0
for w in range(int(sys.argv[2])):
    seq = PS.generate_sequence("s3p3x-explore", w)
    R = PS.records_of(seq)
    ends = list(R.start[1:]) + [len(R.ep)]
    past = []
    for e in range(len(seq.episodes)):
        s0, s1 = R.start[e], ends[e]
        op = np.array(past, dtype=np.int64)
        if e >= 1:
            for c, t in PS.first_arrivals(seq, e):
                qi = s0 + t; n_q += 1
                at = op[(R.truth_cell[op] == np.array(c)).all(1)] if len(op) else op
                if len(at) == 0:
                    n_fb += 1
                    lm = A.latest_match(R, op, qi)
                    latest = int(R.token[qi]) if lm is None else lm
                    n_fb_diff += int(latest != int(R.token[qi]))
        past += [s0 + i for i in PR.dwell_starts(R.xy[s0:s1], R.token[s0:s1])]
print(json.dumps({"worlds": int(sys.argv[2]), "queries": n_q, "lt_fallbacks": n_fb, "fallbacks_where_L_differs_from_shown": n_fb_diff}))
