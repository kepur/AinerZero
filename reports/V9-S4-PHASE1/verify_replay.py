"""S4 第一阶段合法性门「确定性」：在另一个进程里从落盘的权重重跑一部分世界（DESIGN-r3 §5）。

用 python -I 运行，MLX 只用 CPU。读 replay.json（世界的检测序列、柱子、权重相对路径），对每个学习臂的
登记跟踪格（三个种子、登记滤波器）重新跟踪，轨迹分配的摘要须与 worlds.jsonl 里落盘的逐位相同。
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
    print(json.dumps({"passed": checked > 0 and not bad, "checked": checked, "mismatches": bad[:20]}))


if __name__ == "__main__":
    main()
