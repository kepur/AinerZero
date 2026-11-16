"""S6 一期的重放与复训校验（DESIGN-r2 §6），由 run_s6p1.py eval 在另一个 python -I 进程里调用。

用法：python -I verify_s6p1.py <set> <out.json>

- 重放：每个格，从同一种子重建候选池（摘要须与训练时登记的一致），按落盘的挑选逐轮揭示，
  从落盘的第 r 轮权重重算挑选，挑出的编号与第 r+1 轮落盘的逐个相同；分数摘要也相同。
  第一轮随机样本由种子重算。R、T、G 的生成器按同样的种子与次序重放。
- 复训：预先指定的两格（E 重复 0 的种子 1 网络、P 重复 0 的学习者 1），按落盘的挑选从头重训，
  每轮参数与落盘权重逐位相同。
- 描述量：每格每轮新揭示样本中有盘间接触的比例（揭示后的标签，合法）。
只读训练产物，不生成测试世界。
"""
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "reports/V9-S6-PHASE1"))
sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx  # noqa: E402
from mlx.utils import tree_flatten  # noqa: E402

import run_s6p1 as RUN  # noqa: E402
from ainerzero.v9.experiments.s6 import cells as C  # noqa: E402
from ainerzero.v9.experiments.s6 import sandbox as S  # noqa: E402

RETRAIN = (("E", 0, 0), ("P", 0, 0))      # (arm, replicate, learner): seed 1 of replicate 0


class _Held:
    def __init__(self, model):
        self.model = model


def replay_cell(arm, k, rec, source, set_root, sizes, cand_ns):
    out = {"first_ok": True, "rounds_ok": [], "contact_share": []}
    first = S.pick_random(np.arange(C.n_states(source)), sizes.per, np.random.default_rng(C.first_seed(cand_ns, k))).tolist()
    d = RUN.cell_dir(set_root, arm, k)
    for ti, tr in enumerate(rec["tracks"]):
        out["first_ok"] &= tr["picks"][0] == first
        cp = C.make_candidate_pool(source)
        rng = np.random.default_rng(C.pick_seed(cand_ns, arm, k))
        shares = []
        for r in range(sizes.rounds):
            got = cp.reveal(np.array(tr["picks"][r], dtype=np.int64))
            shares.append(float(np.mean(np.concatenate([e["contact"].sum((1, 2)) > 0 for e in got.by_n.values()]))))
            if r == sizes.rounds - 1:
                break
            js = [ti] if arm == "P" else list(range(C.N_LEARNERS))
            learners = [_Held(C.load_model(arm, d / f"r{r}-n{j}.safetensors")) for j in js]
            ids, dig = C.select(arm, C.Track(cp, learners), k, sizes.per, cand_ns, rng)
            out["rounds_ok"].append(ids.tolist() == tr["picks"][r + 1] and dig == tr["score_sha256"][r + 1])
        out["contact_share"].append(shares)
    out["passed"] = bool(out["first_ok"] and all(out["rounds_ok"]))
    return out


def retrain(arm, k, j, rec, source, set_root, sizes):
    mx.set_default_device(mx.gpu)
    seed = C.net_seeds(k)[j]
    learner = C.make_learner(arm, seed)
    tr = rec["tracks"][j if arm == "P" else 0]
    cp = C.make_candidate_pool(source)
    rounds = []
    for r in range(sizes.rounds):
        cp.reveal(np.array(tr["picks"][r], dtype=np.int64))
        learner.train(cp.revealed_pool(), sizes.steps, C.T_COLL_SHARE if arm == "T" else 0.0)
        saved = mx.load(str(RUN.cell_dir(set_root, arm, k) / f"r{r}-n{j}.safetensors"))
        mine = dict(tree_flatten(learner.model.parameters()))
        same = set(saved) == set(mine) and all(np.array_equal(np.array(saved[n]), np.array(mine[n])) for n in mine)
        rounds.append(bool(same))
    return {"seed": seed, "rounds_identical": rounds, "passed": all(rounds)}


def main():
    set_name, out_json = sys.argv[1], Path(sys.argv[2])
    cfg = RUN.SETS[set_name]
    sizes, cand_ns = cfg["sizes"], cfg["cand_ns"]
    set_root = RUN.ROOT / set_name
    pool_sha = json.loads((set_root / "pools.json").read_text(encoding="utf-8"))
    cells = RUN.all_cells(cfg)
    R = {"replay": {}, "retrain": {}, "pools_ok": {}}
    for k in sorted({k for _, k in cells}):
        source = C.candidate_source(cand_ns, k, sizes)
        R["pools_ok"][str(k)] = C.pool_digest(source) == pool_sha.get(str(k))
        for arm in [x for x, kk in cells if kk == k]:
            rec = C.verify_cell_dir(RUN.cell_dir(set_root, arm, k), sizes)
            R["replay"][f"{arm}-r{k}"] = replay_cell(arm, k, rec, source, set_root, sizes, cand_ns)
            print(f"replay {arm}-r{k}", R["replay"][f"{arm}-r{k}"]["passed"], flush=True)
        for arm, kk, j in RETRAIN:
            if kk == k and (arm, k) in cells:
                rec = C.verify_cell_dir(RUN.cell_dir(set_root, arm, k), sizes)
                R["retrain"][f"{arm}-r{k}-n{j}"] = retrain(arm, k, j, rec, source, set_root, sizes)
                print(f"retrain {arm}-r{k}-n{j}", R["retrain"][f"{arm}-r{k}-n{j}"]["passed"], flush=True)
    R["passed"] = bool(all(R["pools_ok"].values()) and all(v["passed"] for v in R["replay"].values())
                       and len(R["retrain"]) == len(RETRAIN) and all(v["passed"] for v in R["retrain"].values()))
    with out_json.open("x", encoding="utf-8") as fh:
        json.dump(R, fh, indent=1)


if __name__ == "__main__":
    main()
