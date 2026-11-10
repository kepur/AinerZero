"""世界模块的动能与动量：逐步检查（复核者自写）。墙和柱会改变动量，所以只看动能；多盘同时接触的步单独统计。"""
import collections, json, sys
import numpy as np
sys.path.insert(0, sys.argv[1] + "/src")
from ainerzero.v9.experiments.s4 import world as W
out = {}
for nd in (6, 10):
    c = collections.Counter(); worst = 0.0
    for w in range(40):
        ep = W.generate_episode("s4x-explore", w, nd)
        for s, nx in zip(ep.steps[:-1], ep.steps[1:]):
            ke0, ke1 = (s.velocities ** 2).sum() / 2, (nx.velocities ** 2).sum() / 2
            d = abs(ke1 - ke0)
            disk_pairs = [(i, j) for k, i, j in s.contacts if k == "disk"]
            multi = len({x for p in disk_pairs for x in p}) < 2 * len(disk_pairs)  # 有盘同时碰两个
            c["steps"] += 1; c["steps_with_disk_contact"] += int(bool(disk_pairs)); c["steps_multi_contact"] += int(multi)
            if d > 1e-9:
                c["energy_changed"] += 1; c["energy_changed_multi"] += int(multi); c["energy_changed_with_disk_contact"] += int(bool(disk_pairs))
                worst = max(worst, d / max(ke0, 1e-12))
    out[nd] = dict(c) | {"worst_relative_change": worst}
print(json.dumps(out)); json.dump(out, open(sys.argv[2], "w"), indent=1)
