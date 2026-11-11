"""诊断 S4 一期探针 r1 评测中的 `cost must be finite`：只读落盘权重，重新生成 s4p1-probe 评测世界，
逐格跟踪，每步检查预测的集合是否有限；记下首个非有限的世界、格、步与出事轨迹的状态。只写到输出目录。
用法：python -I diag_nonfinite.py <仓库根> <输出 json> [世界数上限]"""
import json, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import multiprocessing as mp

REPO = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(REPO / "src"))
import numpy as np  # noqa: E402

RUN = REPO / "artifacts/v9/s4/phase1/probe-r1"
LEARNED = ("L-ind", "L-int", "L-int-c", "L-int-e8", "L-int-c-e8", "L-int-s")


def init():
    import mlx.core as mx
    from ainerzero.v9.experiments.s4 import worker_mlx as WK
    mx.set_default_device(mx.cpu)
    weights = {f"{a}#{s}": str(RUN / "weights" / f"{a}#{s}.safetensors") for s in (1, 2, 3) for a in LEARNED}
    WK.init(weights, {})


def one(args):
    kind, w, n = args
    from ainerzero.v9.experiments.s4 import analysis as A, filter as F, world as W, worker_mlx as WK
    ns = A.NAMESPACES["probe"]
    ep = W.generate_episode(ns, w, n)
    cells = A.plan_cells(LEARNED) if kind == "main" else [c for c in A.plan_cells(LEARNED) if c.variant == "base"]
    dets = A.student_detections(ep)
    found = []
    for c in cells:
        if c.arm == "S-P":
            continue
        model = WK._MODELS.get(f"{c.arm}#{c.seed}", WK._MODELS.get(c.arm))
        rng = np.random.default_rng(A.filter_seed(ns, ep.world_index, c.seed, c.variant))
        hit = {}
        calls = [0]

        def wm(P, V, pil, _m=model):
            out = _m(P, V, pil)
            calls[0] += 1
            if not hit:
                okp = np.isfinite(out[0]).all(axis=(0, 2)) & np.isfinite(out[1]).all(axis=(0, 2))
                far = np.abs(np.nan_to_num(out[0], nan=1e9, posinf=1e9, neginf=-1e9)).max(axis=(0, 2)) > 50
                if (~okp).any() or far.any():
                    k = int(np.flatnonzero(~okp | far)[0])
                    hit.update({"call": calls[0], "n_tracks": int(P.shape[1]), "n_nonfinite": int((~okp).sum()), "n_far": int(far.sum()),
                                "track": k, "in_pos": P[:, k].mean(0).tolist(), "in_vel": V[:, k].mean(0).tolist(),
                                "in_maxabs_pos": float(np.abs(P).max()), "in_maxabs_vel": float(np.abs(V).max()),
                                "out_pos": np.nan_to_num(out[0][:, k].mean(0), nan=1e9).tolist()})
            return out
        try:
            F.track(dets, ep.pillars, wm, rng, A.variant_config(c.variant))
            err = None
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
        if hit or err:
            found.append({"kind": kind, "world": w, "cell": c.key, "error": err, **hit})
    return found


def main():
    from ainerzero.v9.experiments.s4 import analysis as A
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
    ids = A.eval_world_ids(A.SIZES["probe"])[:limit]
    t0 = time.monotonic()
    with ProcessPoolExecutor(6, mp_context=mp.get_context("spawn"), initializer=init) as ex:
        res = [r for rs in ex.map(one, ids) for r in rs]
    out = {"worlds": len(ids), "seconds": round(time.monotonic() - t0, 1), "findings": res}
    Path(sys.argv[2]).write_text(json.dumps(out, indent=1))
    by = {}
    for r in res:
        by.setdefault(r["cell"].split("#")[0] + ("" if r["cell"].count("#") < 2 else ""), 0)
    print("worlds", len(ids), "seconds", out["seconds"], "findings", len(res))
    for r in res[:40]:
        print(r["kind"], r["world"], r["cell"], (r["error"] or "")[:40], "call", r.get("call"), "tracks", r.get("n_tracks"), "nonfin", r.get("n_nonfinite"),
              "far", r.get("n_far"), "in_pos", [round(x, 2) for x in r.get("in_pos", [])], "in_vel", [round(x, 2) for x in r.get("in_vel", [])],
              "maxP", round(r.get("in_maxabs_pos", 0), 1), "maxV", round(r.get("in_maxabs_vel", 0), 1))


if __name__ == "__main__":
    main()
