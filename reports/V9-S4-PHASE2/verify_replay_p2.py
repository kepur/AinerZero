"""S4 第二阶段合法性门「确定性」：在另一个进程里从权重重跑一部分世界的全部跟踪格。

用 python -I 运行，MLX 只用 CPU。读 replay.json（世界的检测序列、真值编号、柱子、权重的仓库相对路径），
按 worker_p2.build_models 重建每个跟踪格（手写臂三个种子、学习臂三个种子），用登记的滤波器种子重新跟踪
（随机门、散射响应这类有随机数的臂，先按登记规则重设它们自己的生成器）：
轨迹分配的摘要须与 worlds.jsonl 里落盘的逐位相同，由重放的分配与真值编号重算的每个事件的对错须与落盘的相同。
一个格都没核对时判不过。
用法：python -I verify_replay_p2.py <replay.json> <worlds.jsonl>，结果以 JSON 打印到标准输出。
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx  # noqa: E402
import numpy as np  # noqa: E402

from ainerzero.v9.experiments.s4 import analysis_p2 as P2  # noqa: E402
from ainerzero.v9.experiments.s4 import filter as F  # noqa: E402
from ainerzero.v9.experiments.s4 import worker_p2 as WK  # noqa: E402


def main():
    mx.set_default_device(mx.cpu)
    rep = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    records = {(r["kind"], r["world"]): r for r in map(json.loads, open(sys.argv[2], encoding="utf-8"))}
    models, _, _ = WK.build_models({n: str(REPO / p) for n, p in rep["weights"].items()})
    cells = []
    for name, m in models.items():
        seeds = [int(name.split("#")[1])] if "#" in name else list(P2.SEEDS)
        cells += [(name.split("#")[0], s, m) for s in seeds]
    checked, bad = 0, []
    for w in rep["worlds"]:
        rec = records[(w["kind"], w["world"])]
        dets = [np.array(d, dtype=np.float64).reshape(-1, 2) for d in w["detections"]]
        pillars = tuple(tuple(p) for p in w["pillars"])
        for arm, s, m in cells:
            key = P2.cell_key(arm, s)
            P2.reseed_if_stochastic(m, P2.rng_seed(rep["ns"], w["world"], s, arm, "track"))
            rng = np.random.default_rng(P2.filter_seed(rep["ns"], w["world"], s))
            ids, _ = F.track(dets, pillars, m, rng, F.FilterConfig())
            checked += 1
            if key not in rec["cells"] or P2.ids_digest(ids) != rec["cells"][key]["ids_sha256"]:
                bad.append(f"{w['kind']} {w['world']} {key}")
                continue
            at = [dict(zip(t, np.asarray(i).tolist())) for t, i in zip(w["truth_ids"], ids)]
            correct = [int(at[a][k] == at[b][k]) for k, a, b, _, _ in rec["events"]]
            if correct != rec["cells"][key]["correct"]:
                bad.append(f"{w['kind']} {w['world']} {key} reid")
    expected = len(rep["worlds"]) * len(cells)
    print(json.dumps({"passed": expected > 0 and checked == expected and not bad, "checked": checked, "cells_per_world": len(cells),
                      "mismatches": bad[:20]}))


if __name__ == "__main__":
    main()
