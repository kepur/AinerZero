"""S4 第一阶段合法性门「确定性」：在另一个进程里从落盘的权重重跑一部分世界（DESIGN-r3 §5）。

用 python -I 运行，MLX 只用 CPU。读 replay.json（世界的检测序列、真值编号、柱子、权重相对路径），对每个学习臂
和 E-B、E-P 的登记跟踪格（三个种子、登记滤波器）重新跟踪：轨迹分配的摘要须与 worlds.jsonl 里落盘的逐位相同，
由重放的分配与真值编号重算的每个事件的对错须与落盘的相同。一个格都没核对时判不过。
用法：python -I verify_replay.py <replay.json> <worlds.jsonl> <运行目录>，结果以 JSON 打印到标准输出。
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx  # noqa: E402
import numpy as np  # noqa: E402

from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import filter as F  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import models as Mo  # noqa: E402

HAND = ("E-B", "E-P")


def base_arm(name):
    arm = name.split("#")[0]
    return arm[:-3] if arm.endswith("-e8") else arm


def main():
    mx.set_default_device(mx.cpu)
    rep = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    records = {(r["kind"], r["world"]): r for r in map(json.loads, open(sys.argv[2], encoding="utf-8"))}
    run = Path(sys.argv[3])
    models = {}
    for name, rel in rep["weights"].items():
        net = L.load(base_arm(name), str(run / rel))
        models[name] = L.as_process_model(net, with_variance=base_arm(name) == "L-int-s")
    for arm in HAND:                       # E-B and E-P are the denominator of C: replay them too
        for s in A.SEEDS:
            models[f"{arm}#{s}"] = Mo.HAND_MODELS[arm]
    checked, bad = 0, []
    for w in rep["worlds"]:
        rec = records[(w["kind"], w["world"])]
        dets = [np.array(d, dtype=np.float64).reshape(-1, 2) for d in w["detections"]]
        pillars = tuple(tuple(p) for p in w["pillars"])
        for name, m in models.items():
            arm, seed = name.split("#")
            cell = A.Cell(arm, int(seed))
            rng = np.random.default_rng(A.filter_seed(rep["ns"], w["world"], cell.seed, cell.variant))
            ids, _ = F.track(dets, pillars, m, rng, A.variant_config(cell.variant))
            checked += 1
            if A.ids_digest(ids) != rec["ids_sha256"][cell.key]:
                bad.append(f"{w['kind']} {w['world']} {cell.key}")
            # the correctness of every event, recomputed from the replayed ids and the truth identities
            at = [dict(zip(t, np.asarray(i).tolist())) for t, i in zip(w["truth_ids"], ids)]
            correct = [int(at[a][k] == at[b][k]) for k, a, b, _ in rec["events"]]
            if correct != rec["reid"][cell.key]:
                bad.append(f"{w['kind']} {w['world']} {cell.key} reid")
    expected = len(rep["worlds"]) * len(models)
    print(json.dumps({"passed": expected > 0 and checked == expected and not bad, "checked": checked, "mismatches": bad[:20]}))


if __name__ == "__main__":
    main()
