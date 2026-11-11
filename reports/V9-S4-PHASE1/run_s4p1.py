"""S4 第一阶段运行器（DESIGN-r3；预登记 reports/V9-S4-PHASE1/PREREG-r1.json）。

用法：
  python -I -X pycache_prefix=<新目录> run_s4p1.py --stage final --approval <批准行> --report <json>
  python -I run_s4p1.py --stage smoke|probe --use-id <名字> --steps <训练步数> --batch <批大小> --report <json>

- smoke 只读替身命名空间 s4p1x-smoke-train、s4p1x-smoke-eval，不碰登记分区；
- probe 训练用 s4p1-train，评测用 s4p1-probe（主评测 50 个世界，外推 25 个）；
- final 训练用 s4p1-train，评测用 s4p1-final（主评测 0–199 号 6 盘，外推 1000–1099 号 10 盘），
  训练步数与批大小取自预登记，命令行不得再给。

启动顺序：拿锁 → python -I、新字节码目录、冻结清单、已加载模块、第三方版本、git（final）→ 分区 → 请求
→ final 只读一次标记是否已存在 → 运行目录、占报告。任何一步失败都不写标记。
训练只读 train 分区。final 的只读一次标记在训练全部完成之后、生成登记分区的第一个世界之前写下：训练中途失败
（超时、损失非有限、断电）不花掉这一次读取；留下的运行目录会挡住重跑，须由一级存档后再启动。
训练在本机 MLX 的 GPU 上依次进行；评测在 spawn 出的 CPU 工作进程里，世界只由主进程生成后传入。
合法性门：标签与确定性由 verify_labels.py、verify_replay.py 在另一个 python -I 进程里复核；
学生视图在主进程里做字段白名单与未来帧变异。全部中间产物（权重、训练日志、逐世界记录）落盘并记 SHA。
"""
import time

STARTED = time.time()
import argparse, hashlib, json, multiprocessing as mp, resource, subprocess, sys  # noqa: E401
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx  # noqa: E402

from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import filter as F  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import models as Mo  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s4 import worker_mlx as WK  # noqa: E402

HERE = REPO / "reports/V9-S4-PHASE1"
ROOT = REPO / "artifacts/v9/s4/phase1"
PREREG = HERE / "PREREG-r1.json"
VERIFY_LABELS = HERE / "verify_labels.py"
VERIFY_REPLAY = HERE / "verify_replay.py"
LOCK = REPO / "artifacts/locks/m0-worker.lock"
FINAL_MARKER = ROOT / "FINAL_READ_ONCE.json"
THIRD_PARTY = ("numpy", "mlx")
SMOKE = {"train": "s4p1x-smoke-train", "eval": "s4p1x-smoke-eval"}
LEARNED = ("L-ind", "L-int", "L-int-c", "L-int-e8", "L-int-c-e8", "L-int-s")
# L-int-s is trained and gives the calibration description, but it is not a tracking arm: sampling the
# filter's process noise from its variance head feeds back on unobserved tracks and diverges (probe r1:
# non-finite in all 12 worlds checked; DESIGN-r3, implementation notes). It is not tracked, not replayed.
TRACKED = tuple(a for a in LEARNED if a != "L-int-s")
EIGHTH = 8
CELL_LIMIT_S = 600
WORKERS = 6
CALIB_FIT_WORLDS, CALIB_FIT_EVERY = 100, 3
REPLAY_WORLDS = {"main": 3, "extrap": 2}
STUDENT_WORLDS, STUDENT_CUT = 2, 150
STAGES = {
    "smoke": {"n_train": 10, "sizes": (4, 2), "limit": 3600, "pool": 4000, "sigma": 2000},
    "probe": {"n_train": A.N_TRAIN, "sizes": A.SIZES["probe"], "limit": 4 * 3600, "pool": 240_000, "sigma": 120_000},
    "final": {"n_train": A.N_TRAIN, "sizes": A.SIZES["final"], "limit": 4 * 3600, "pool": 240_000, "sigma": 120_000},
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def code_manifest():
    return GD.build_manifest(REPO, [Path(__file__).resolve()], src_root=REPO / "src", extra=[VERIFY_LABELS, VERIFY_REPLAY])


def manifest_sha(m):
    return hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def pool_sha(pool):
    h = hashlib.sha256()
    for n in sorted(pool.by_n):
        for k in sorted(pool.by_n[n]):
            h.update(f"{n}:{k}".encode())
            h.update(np.ascontiguousarray(pool.by_n[n][k]).tobytes())
    return h.hexdigest()


def startup_checks(stage):
    """Run after the lock is held. Returns (prereg or None, its sha, git head, versions)."""
    versions = GD.third_party_versions(REPO, THIRD_PARTY)
    if stage != "final":
        return None, None, None, versions
    if not sys.flags.isolated:
        raise GD.GuardError("final must run with python -I")
    GD.require_fresh_pycache(STARTED)
    pre = json.loads(PREREG.read_text(encoding="utf-8"))
    bad = GD.check_manifest(REPO, pre["manifest"]) + GD.check_loaded_modules(REPO, pre["manifest"])
    if bad:
        raise GD.GuardError("frozen manifest does not hold: " + "; ".join(bad[:6]))
    if versions != pre["third_party"]:
        raise GD.GuardError(f"library versions differ from the preregistration: {versions}")
    head, dirty = GD.check_git_clean(REPO, list(pre["manifest"]) + [str(PREREG.relative_to(REPO))])
    if dirty:
        raise GD.GuardError("frozen files are not committed: " + "; ".join(dirty[:6]))
    return pre, sha(PREREG), head, versions


def namespaces(stage):
    if stage == "smoke":
        ns = dict(SMOKE)
        if set(ns.values()) & (set(A.NAMESPACES.values()) | set(W.REGISTERED)):
            raise GD.GuardError(f"smoke must not read a registered partition: {ns}")
        return ns
    ns = {"train": A.NAMESPACES["train"], "eval": A.NAMESPACES[stage]}
    if len(set(A.NAMESPACES.values())) != 3:
        raise GD.GuardError("partitions must be distinct")
    if stage == "probe" and ns["eval"] in W.REGISTERED:
        raise GD.GuardError("probe must not read the registered final partition")
    return ns


def check_request(a, pre):
    """Refuse a malformed request before anything is claimed or spent."""
    if a.use_id is not None and not GD.valid_use_id(a.use_id):
        raise GD.GuardError(f"invalid use id: {a.use_id!r}")
    if a.stage in ("smoke", "probe"):
        if not a.use_id:
            raise GD.GuardError(f"a {a.stage} run needs a use id")
        if not a.steps or not a.batch or a.steps <= 0 or a.batch <= 0:
            raise GD.GuardError(f"a {a.stage} run needs positive --steps and --batch")
        if a.approval:
            raise GD.GuardError("only final takes an approval line")
        return a.steps, a.batch
    if a.steps is not None or a.batch is not None or a.use_id is not None:
        raise GD.GuardError("final takes its steps and batch from the preregistration only")
    if (a.approval or "").strip() != pre["final_approval_line"]:
        raise GD.GuardError("missing the unique approval line")
    return int(pre["training"]["steps"]), int(pre["training"]["batch"])


# --- training ----------------------------------------------------------------------------------------
def train_all(train_eps, ns, cfg, steps, batch, out, deadline, say):
    """The 18 cells in a fixed order; weights and loss logs on disk. Returns (weights, info)."""
    mx.set_default_device(mx.gpu)
    t = time.monotonic()
    pool = L.make_pool(train_eps, cfg["pool"], np.random.default_rng(W.derive_seed(ns, "pool")), W.physics)
    eighth = L.make_pool(train_eps[: max(1, len(train_eps) // EIGHTH)], cfg["pool"] // EIGHTH, np.random.default_rng(W.derive_seed(ns, "pool-e8")), W.physics)
    sigma = L.make_sigma_pool(train_eps, cfg["sigma"], np.random.default_rng(W.derive_seed(ns, "sigma")))
    info = {"pools": {name: {"size": p.size(), "buckets": {str(n): len(e["p"]) for n, e in p.by_n.items()}, "sha256": pool_sha(p)}
                      for name, p in (("full", pool), ("eighth", eighth), ("sigma", sigma))},
            "pool_seconds": round(time.monotonic() - t, 1), "cells": {}}
    say("pools", {k: v["size"] for k, v in info["pools"].items()})
    wdir = out / "weights"
    wdir.mkdir()
    weights, nets = {}, {}
    for s in A.SEEDS:
        for arm in LEARNED:
            deadline.check()
            name = f"{arm}#{s}"
            t = time.monotonic()
            try:
                if arm == "L-int-s":
                    net, log = L.train("L-int-s", sigma, steps=steps, batch=batch, seed=s, mean_model=nets[f"L-int#{s}"], time_limit=CELL_LIMIT_S)
                else:
                    net, log = L.train(WK.base_arm(name), eighth if arm.endswith("-e8") else pool, steps=steps, batch=batch, seed=s,
                                       time_limit=CELL_LIMIT_S)
            except TimeoutError as exc:
                raise GD.GuardError(f"training cell over its limit: {exc}") from exc
            secs = time.monotonic() - t
            path = wdir / f"{name}.safetensors"
            L.save(net, str(path))
            nets[name], weights[name] = net, str(path)
            info["cells"][name] = {"seconds": round(secs, 1), "loss": log,
                                   "params": L.param_count(net), "weights_sha256": sha(path)}
            say("trained", name, round(secs, 1), "s, last loss", log[-1][1])
    mx.set_default_device(mx.cpu)
    return weights, nets, info


def fit_refs(train_eps, ns, nets):
    """Calibration references per seed, fitted on train rows of the seed's L-int-σ."""
    refs = {}
    for s in A.SEEDS:
        m = L.as_process_model(nets[f"L-int-s#{s}"], with_variance=True)
        rng = np.random.default_rng(W.derive_seed(ns, "calib-fit", s))
        rows = [A.calib_rows(e, m, rng, every=CALIB_FIT_EVERY) for e in train_eps[:CALIB_FIT_WORLDS]]
        merged = {k: np.concatenate([r[k] for r in rows]) for k in rows[0]}
        refs[s] = A.fit_references(merged)
    return refs


# --- legality helpers --------------------------------------------------------------------------------
def student_check(eps, nets):
    """Field whitelist (the trackers read A.student_detections, which refuses other fields) and
    future-frame mutation: after the cut every step loses its last detection and the rest move by
    0.5. Ids up to the cut must not change; after it the tracker must have consumed the mutated
    lists (one id per mutated detection) and its ids must differ from the unmutated run."""
    keys_ok = W.STUDENT_KEYS == {"t", "agent", "detections"} and all(set(W.student_view(s)) == W.STUDENT_KEYS for ep in eps for s in ep.steps)
    models = {"E-P": Mo.true_physics, "L-int#1": L.as_process_model(nets["L-int#1"])}
    rows = []
    for ep in eps[:STUDENT_WORLDS]:
        dets = A.student_detections(ep)
        mut = A.future_mutation(dets, STUDENT_CUT)
        for name, m in models.items():
            a, _ = F.track(dets, ep.pillars, m, np.random.default_rng(7))
            b, _ = F.track(mut, ep.pillars, m, np.random.default_rng(7))
            rows.append({"world": ep.world_index, "model": name, **A.mutation_row(a, b, mut, STUDENT_CUT)})
    ok = keys_ok and rows and all(r["prefix_equal"] and r["consumed"] and r["suffix_changed"] for r in rows)
    return {"passed": bool(ok), "keys_ok": keys_ok, "rows": rows}


def independent_check(script, *args, deadline):
    left = deadline.left()
    if left <= 0:
        raise GD.GuardError("wall-clock limit reached")
    try:
        r = subprocess.run([sys.executable, "-I", str(script), *map(str, args)], capture_output=True, text=True, timeout=left)
    except subprocess.TimeoutExpired as exc:
        raise GD.GuardError("wall-clock limit reached") from exc
    if r.returncode != 0:
        return {"passed": False, "error": r.stderr[-2000:]}
    return json.loads(r.stdout)


def evaluate_parallel(tasks, weights, refs, deadline, say, partial):
    """Worlds in parallel workers; each record is appended to ``partial`` as soon as it arrives, so a
    run stopped by the wall clock keeps what it computed."""
    ctx = mp.get_context("spawn")
    results = [None] * len(tasks)
    fh = partial.open("x", encoding="utf-8")
    with ProcessPoolExecutor(WORKERS, mp_context=ctx, initializer=WK.init, initargs=(weights, {int(k): v for k, v in refs.items()})) as ex:
        pending = {ex.submit(WK.evaluate_world, t): i for i, t in enumerate(tasks)}
        done_n = 0
        while pending:
            left = deadline.left()
            if left <= 0:
                for f in pending:
                    f.cancel()
                raise GD.GuardError("wall-clock limit reached")
            done, _ = wait(list(pending), timeout=min(left, 60), return_when=FIRST_COMPLETED)
            for f in done:
                i = pending.pop(f)
                results[i] = f.result()
                fh.write(json.dumps({"index": i, "record": results[i]}, ensure_ascii=False, sort_keys=True) + "\n")
                fh.flush()
                done_n += 1
                if done_n % 25 == 0:
                    say("worlds evaluated", done_n, "of", len(tasks))
    fh.close()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=sorted(STAGES))
    ap.add_argument("--use-id")
    ap.add_argument("--approval")
    ap.add_argument("--steps", type=int)
    ap.add_argument("--batch", type=int)
    ap.add_argument("--report", required=True)
    a = ap.parse_args()
    cfg = STAGES[a.stage]
    deadline = GD.Deadline(cfg["limit"])
    t0 = time.monotonic()

    with GD.RunLock(LOCK) as lock:
        pre, pre_sha, head, versions = startup_checks(a.stage)
        ns = namespaces(a.stage)
        steps, batch = check_request(a, pre)
        report = Path(a.report)
        run_id = f"{a.stage}-{a.use_id or 'final'}"
        out = ROOT / run_id
        if out.exists():
            raise GD.GuardError(f"run directory already exists: {out}")
        if a.stage == "final" and FINAL_MARKER.exists():
            raise GD.GuardError("final has already been read")
        GD.claim_report(report)
        out.mkdir(parents=True)

        code = code_manifest()
        code_head, code_dirty = GD.check_git_clean(REPO, list(code))
        R = {"schema": "s4.phase1.v1", "stage": a.stage, "use_id": a.use_id, "namespaces": ns, "steps": steps, "batch": batch,
             "sizes": cfg["sizes"], "prereg_sha256": pre_sha, "git_head": head or code_head, "code_manifest_sha256": manifest_sha(code),
             "code_dirty": code_dirty, "third_party": versions, "learned_arms": list(LEARNED), "tracked_arms": list(TRACKED), "workers": WORKERS}

        def save():
            R["elapsed_s"] = round(time.monotonic() - t0, 1)
            R["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")

        def say(*x):
            print(f"[{time.monotonic() - t0:8.1f}s]", *x, flush=True)

        save()
        train_eps = [W.generate_episode(ns["train"], w, A.train_disks(ns["train"], w)) for w in range(cfg["n_train"])]
        weights, nets, R["training"] = train_all(train_eps, ns["train"], cfg, steps, batch, out, deadline, say)
        save()
        refs = fit_refs(train_eps, ns["train"], nets)
        R["calibration_references"] = refs
        deadline.check()
        R["pre_eval_seconds"] = round(time.monotonic() - t0, 1)       # start-up, train worlds, pools, training, references

        registered = a.stage == "final"
        if registered:
            # Enough wall clock for the evaluation measured in the probe must remain, or the one read is not spent.
            reserve = float(pre["budget"]["eval_reserve_s"])
            if deadline.left() < reserve:
                raise GD.GuardError(f"only {deadline.left():.0f} s left, the evaluation needs {reserve:.0f} s: the final read is not spent")
            # The one read of the registered partition starts here; nothing above generates it.
            GD.consume_final_read(lock, FINAL_MARKER, a.approval, pre["final_approval_line"], prereg_sha256=pre_sha, expected_lock=LOCK)
            R["final_read_marker_sha256"] = sha(FINAL_MARKER)
            save()
        t_post = time.monotonic()                                          # everything from here on is what the reserve must cover
        eval_eps = [(kind, W.generate_episode(ns["eval"], w, n, allow_registered=registered)) for kind, w, n in A.eval_world_ids(cfg["sizes"])]
        say("evaluation worlds", len(eval_eps))
        main_cells = [(c.arm, c.seed, c.variant) for c in A.plan_cells(TRACKED)]
        base_cells = [c for c in main_cells if c[2] == "base"]
        tasks = [{"kind": kind, "ns": ns["eval"], "episode": ep, "cells": main_cells if kind == "main" else base_cells} for kind, ep in eval_eps]
        t_eval = time.monotonic()
        records = evaluate_parallel(tasks, weights, refs, deadline, say, out / "worlds.partial.jsonl")
        R["eval_seconds"] = round(time.monotonic() - t_eval, 1)

        worlds = out / "worlds.jsonl"
        with worlds.open("x", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        labels = out / "labels.jsonl"
        with labels.open("x", encoding="utf-8") as fh:
            for kind, ep in eval_eps:
                fh.write(json.dumps(A.label_log(kind, ep), sort_keys=True) + "\n")
        replay = out / "replay.json"
        picks = []
        for kind, k in REPLAY_WORLDS.items():
            picks += [(kd, ep) for kd, ep in eval_eps if kd == kind][:k]
        replay.write_text(json.dumps({"ns": ns["eval"], "weights": {n: str(Path(p).relative_to(out)) for n, p in weights.items() if n.split("#")[0] in TRACKED},
                                      "worlds": [{"kind": kd, "world": ep.world_index, "pillars": [list(p) for p in ep.pillars],
                                                  "detections": [d.tolist() for d in A.student_detections(ep)],
                                                  "truth_ids": [s.truth_ids.tolist() for s in ep.steps]} for kd, ep in picks]}), encoding="utf-8")
        R["files_sha256"] = {f.name: sha(f) for f in (worlds, out / "worlds.partial.jsonl", labels, replay)} | {f"weights/{Path(p).name}": sha(p) for p in weights.values()}
        save()

        t_chk = time.monotonic()
        st = student_check([ep for kind, ep in eval_eps if kind == "main"], nets)
        lab = independent_check(VERIFY_LABELS, labels, worlds, deadline=deadline)
        rep = independent_check(VERIFY_REPLAY, replay, worlds, out, deadline=deadline)
        R["check_seconds"] = round(time.monotonic() - t_chk, 1)
        on_disk = [json.loads(line) for line in worlds.read_text(encoding="utf-8").splitlines()]
        main_r = [r for r in on_disk if r["kind"] == "main"]
        ext_r = [r for r in on_disk if r["kind"] == "extrap"]
        R["checks"] = {"student_view": st, "labels": lab, "replay": rep}
        R["result"] = A.evaluate(main_r, ext_r, n_main=cfg["sizes"][0], n_extrap=cfg["sizes"][1], labels_ok=bool(lab.get("passed")),
                                 student_ok=st["passed"], replay_ok=bool(rep.get("passed")))
        R["descriptive"] = A.summarize_descriptive(main_r, ext_r, TRACKED)
        if pre:
            late = GD.check_manifest(REPO, pre["manifest"]) + GD.check_loaded_modules(REPO, pre["manifest"])
            R["late_violations"] = late
            if late:
                R["result"]["valid"] = False
                for g in R["result"]["gates"].values():
                    g["passed"], g["void"] = False, "frozen files or modules changed during the run"
        R["post_marker_seconds"] = round(time.monotonic() - t_post, 1)    # evaluation worlds, evaluation, files, checks, gates
        save()
        say("valid", R["result"]["valid"], {k: v["passed"] for k, v in R["result"]["gates"].items()})


if __name__ == "__main__":
    main()
