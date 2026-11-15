"""S6 一期运行器（reports/V9-S6-DESIGN/DESIGN-r2.md；预登记 reports/V9-S6-PHASE1/PREREG-r1.json）。

用法（都要经共享锁 artifacts/locks/m0-worker.lock，本脚本自己拿锁）：
  python -I -X pycache_prefix=<新目录> run_s6p1.py train --set smoke|probe|final
  python -I -X pycache_prefix=<新目录> run_s6p1.py eval  --set smoke|probe|final --report <json> [--approval <批准行>]

两段分开（DESIGN-r2 §7）：
- train：只用候选池命名空间，按「臂 × 重复」逐格训练、挑选、落盘，可以断点续跑；从不生成测试世界。
  已完成的格（cell.json 在且逐文件 SHA 对得上）跳过；没写完的格改名为 *.aborted-N 保留，重跑。
  final 的训练墙钟按账本跨次累计，超过登记上限就拒绝再开新格。
- eval：先在另一个 python -I 进程里做重放与复训校验（verify_s6p1.py），不过就停，不花 final 的一次读取；
  再生成测试世界（final 先写只读一次标记），在 CPU 上评测全部格、全部轮次的权重，落盘逐世界误差，算门。

冒烟只用 s6t-* 替身命名空间与极小尺寸；探针用 s6p1-pcand / s6p1-probe，每臂 1 个重复。
"""
import time

STARTED = time.time()
import argparse, hashlib, json, resource, subprocess, sys  # noqa: E401
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx  # noqa: E402

from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s6 import cells as C  # noqa: E402

HERE = REPO / "reports/V9-S6-PHASE1"
ROOT = REPO / "artifacts/v9/s6/phase1"
PREREG = HERE / "PREREG-r1.json"
VERIFY = HERE / "verify_s6p1.py"
LOCK = REPO / "artifacts/locks/m0-worker.lock"
THIRD_PARTY = ("numpy", "mlx")
SMOKE_SIZES = C.Sizes(per=60, rounds=2, steps=30, pool=1500, cand_worlds=8)
SETS = {
    "smoke": {"cand_ns": "s6t-smoke-cand", "test_ns": "s6t-smoke-test", "sizes": SMOKE_SIZES,
              "reps": {**{a: 2 for a in C.ARMS}, "G": 1}, "worlds": (3, 2), "train_cap_s": 1800, "eval_limit_s": 1800},
    "probe": {"cand_ns": "s6p1-pcand", "test_ns": "s6p1-probe", "sizes": C.FULL,
              "reps": {a: 1 for a in C.ARMS}, "worlds": (50, 25), "train_cap_s": 2.5 * 3600, "eval_limit_s": 3600},
    "final": {"cand_ns": "s6p1-cand", "test_ns": "s6p1-final", "sizes": C.FULL,
              "reps": dict(C.REPLICATES), "worlds": (200, 100), "train_cap_s": 5.0 * 3600, "eval_limit_s": 3600},
}
REGISTERED_SETS = ("final",)
DANGLING_CHARGE_S = 900          # an invocation that died after its last heartbeat is charged this much more


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def code_manifest():
    return GD.build_manifest(REPO, [Path(__file__).resolve()], src_root=REPO / "src", extra=[VERIFY])


def manifest_sha(m):
    return hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def check_partitions():
    """Candidate, probe-candidate, probe and final namespaces are distinct; only final is registered;
    the smoke set touches nothing of S6 phase 1."""
    names = [SETS[s][k] for s in SETS for k in ("cand_ns", "test_ns")]
    if len(set(names)) != len(names):
        raise GD.GuardError(f"namespaces must be distinct: {names}")
    if SETS["final"]["test_ns"] not in W.REGISTERED:
        raise GD.GuardError("the final test partition must be registered in the world module")
    for s, cfg in SETS.items():
        for k in ("cand_ns", "test_ns"):
            ns = cfg[k]
            if ns in W.REGISTERED and not (s == "final" and k == "test_ns"):
                raise GD.GuardError(f"{s}/{k} must not be a registered partition: {ns}")
            if s == "smoke" and not ns.startswith("s6t-"):
                raise GD.GuardError(f"smoke must use stand-in namespaces: {ns}")


def startup_checks(set_name):
    """After the lock. For final: python -I, fresh bytecode, frozen manifest, loaded modules, versions,
    committed files. Returns (prereg or None, its sha, git head, versions)."""
    versions = GD.third_party_versions(REPO, THIRD_PARTY)
    check_partitions()
    if set_name not in REGISTERED_SETS:
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
    if pre.get("sets", {}).get("final") != set_summary("final"):
        raise GD.GuardError("the final set in the preregistration differs from the runner's")
    head, dirty = GD.check_git_clean(REPO, list(pre["manifest"]) + [str(PREREG.relative_to(REPO))])
    if dirty:
        raise GD.GuardError("frozen files are not committed: " + "; ".join(dirty[:6]))
    return pre, sha(PREREG), head, versions


def set_summary(set_name):
    cfg = SETS[set_name]
    return {"cand_ns": cfg["cand_ns"], "test_ns": cfg["test_ns"], "sizes": cfg["sizes"].__dict__, "reps": cfg["reps"],
            "worlds": list(cfg["worlds"]), "train_cap_s": cfg["train_cap_s"], "eval_limit_s": cfg["eval_limit_s"]}


def cell_dir(set_root, arm, k):
    return set_root / "cells" / f"{arm}-r{k}"


def all_cells(cfg):
    return [(a, k) for k in range(max(cfg["reps"].values())) for a in C.ARMS if k < cfg["reps"][a]]


# --- training ledger (wall clock across invocations) ---------------------------------------------------------
def ledger_used(ledger):
    if not ledger.is_file():
        return 0.0, []
    rows = json.loads(ledger.read_text(encoding="utf-8"))
    used = 0.0
    for r in rows:
        used += r["last_beat"] - r["start"] + (0 if r.get("closed") else DANGLING_CHARGE_S)
    return used, rows


def ledger_write(ledger, rows):
    tmp = ledger.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    tmp.rename(ledger)


def train(a, say):
    cfg = SETS[a.set]
    set_root = ROOT / a.set
    with GD.RunLock(LOCK):
        pre, pre_sha, head, versions = startup_checks(a.set)
        set_root.mkdir(parents=True, exist_ok=True)
        ledger = set_root / "train-ledger.json"
        used, rows = ledger_used(ledger)
        left = cfg["train_cap_s"] - used
        if left <= 0:
            raise GD.GuardError(f"training wall clock used up: {used:.0f} s of {cfg['train_cap_s']:.0f} s")
        deadline = GD.Deadline(left)
        me = {"start": time.time(), "last_beat": time.time(), "closed": False, "cells": [], "prereg_sha256": pre_sha,
              "code_manifest_sha256": manifest_sha(code_manifest()), "git_head": head, "third_party": versions}
        rows.append(me)
        ledger_write(ledger, rows)
        pools = set_root / "pools.json"
        pool_sha = json.loads(pools.read_text()) if pools.is_file() else {}
        mx.set_default_device(mx.gpu)
        todo_by_k = {}
        for arm, k in all_cells(cfg):
            d = cell_dir(set_root, arm, k)
            if (d / "cell.json").is_file():
                C.verify_cell_dir(d, cfg["sizes"])
                continue
            if d.exists():
                n = 1
                while d.with_name(f"{d.name}.aborted-{n}").exists():
                    n += 1
                d.rename(d.with_name(f"{d.name}.aborted-{n}"))
                say("kept unfinished cell as", d.with_name(f"{d.name}.aborted-{n}").name)
            todo_by_k.setdefault(k, []).append(arm)
        for k, arms in sorted(todo_by_k.items()):
            deadline.check()
            t = time.time()
            source = C.candidate_source(cfg["cand_ns"], k, cfg["sizes"])
            dig = C.pool_digest(source)
            if pool_sha.setdefault(str(k), dig) != dig:
                raise GD.GuardError(f"candidate pool of replicate {k} differs from the one recorded earlier")
            pools.write_text(json.dumps(pool_sha, indent=1), encoding="utf-8")
            say(f"replicate {k}: pool {C.n_states(source)} in {time.time() - t:.0f}s; cells {arms}")
            for arm in arms:
                deadline.check()
                rec = C.run_cell(arm, k, source, cell_dir(set_root, arm, k), cand_ns=cfg["cand_ns"], sizes=cfg["sizes"],
                                 say=say, check_time=deadline.check)
                me["cells"].append({"arm": arm, "replicate": k, "seconds": rec["seconds"]})
                me["last_beat"] = time.time()
                ledger_write(ledger, rows)
                say(f"cell {arm}-r{k} done in {rec['seconds']:.0f}s; used {ledger_used(ledger)[0]:.0f}s of {cfg['train_cap_s']:.0f}s")
        me["last_beat"], me["closed"] = time.time(), True
        ledger_write(ledger, rows)
        missing = [f"{x}-r{k}" for x, k in all_cells(cfg) if not (cell_dir(set_root, x, k) / "cell.json").is_file()]
        say("training complete" if not missing else f"still missing: {missing}")


# --- evaluation ------------------------------------------------------------------------------------------------
def independent_verify(set_name, out_json, deadline):
    left = deadline.left()
    if left <= 0:
        raise GD.GuardError("wall-clock limit reached")
    try:
        r = subprocess.run([sys.executable, "-I", str(VERIFY), set_name, str(out_json)], capture_output=True, text=True, timeout=left)
    except subprocess.TimeoutExpired as exc:
        raise GD.GuardError("wall-clock limit reached during verification") from exc
    if r.returncode != 0 or not Path(out_json).is_file():
        return {"passed": False, "error": (r.stderr or r.stdout)[-3000:]}
    return json.loads(Path(out_json).read_text(encoding="utf-8"))


def evaluate(cfg, set_root, cells, test_eps, say, deadline):
    """CPU. Returns (arrays dict for npz, counts/eb per test set)."""
    mx.set_default_device(mx.cpu)
    sizes = cfg["sizes"]
    models = {(arm, k, r, j): C.load_model(arm, cell_dir(set_root, arm, k) / f"r{r}-n{j}.safetensors")
              for arm, k in cells for r in range(sizes.rounds) for j in range(C.N_LEARNERS)}
    out = {}
    for tset, eps in test_eps.items():
        W_ = len(eps)
        counts = np.zeros((W_, 4), dtype=np.int64)
        eb = np.zeros(W_)
        sums = {arm: np.zeros((cfg["reps"][arm], C.N_LEARNERS, sizes.rounds, W_, 4)) for arm in C.ARMS}
        for w, ep in enumerate(eps):
            deadline.check()
            tw = C.prepare_world(ep)
            counts[w], eb[w] = C.world_counts(tw)
            for (arm, k, r, j), m in models.items():
                sums[arm][k, j, r, w] = C.world_sums(m, tw)
            if (w + 1) % 25 == 0:
                say(f"{tset}: {w + 1} of {W_} worlds")
        out[f"{tset}/counts"], out[f"{tset}/eb"] = counts, eb
        for arm in C.ARMS:
            out[f"{tset}/sums/{arm}"] = sums[arm]
    return out


def analysis_input(arrays, rnd):
    """The analysis module's input at one round: per test set, sums[arm] [R_arm, N_net, W, 4], counts, eb."""
    return {t: {"sums": {arm: arrays[f"{t}/sums/{arm}"][:, :, rnd] for arm in C.ARMS},
                "counts": arrays[f"{t}/counts"], "eb": arrays[f"{t}/eb"]} for t in ("main6", "extrap10")}


def run_eval(a, say):
    cfg = SETS[a.set]
    set_root = ROOT / a.set
    deadline = GD.Deadline(cfg["eval_limit_s"])
    t0 = time.monotonic()
    with GD.RunLock(LOCK) as lock:
        pre, pre_sha, head, versions = startup_checks(a.set)
        registered = a.set in REGISTERED_SETS
        if registered and (a.approval or "").strip() != pre["final_approval_line"]:
            raise GD.GuardError("missing the unique approval line")
        if not registered and a.approval:
            raise GD.GuardError("only final takes an approval line")
        marker = set_root / "FINAL_READ_ONCE.json"
        if registered and marker.exists():
            raise GD.GuardError("final has already been read")
        cells = all_cells(cfg)
        missing = [f"{x}-r{k}" for x, k in cells if not (cell_dir(set_root, x, k) / "cell.json").is_file()]
        if missing:
            raise GD.GuardError(f"training is not complete: {missing}")
        recs = {(x, k): C.verify_cell_dir(cell_dir(set_root, x, k), cfg["sizes"]) for x, k in cells}
        if registered:     # every training invocation ran the frozen code under this preregistration
            _, rows = ledger_used(set_root / "train-ledger.json")
            code_now = manifest_sha(code_manifest())
            if not rows or any(r["prereg_sha256"] != pre_sha or r["code_manifest_sha256"] != code_now for r in rows):
                raise GD.GuardError("some training ran under a different preregistration or code")
        out = set_root / f"eval-{cfg['test_ns']}"
        if out.exists():
            raise GD.GuardError(f"evaluation directory already exists: {out}")
        report = Path(a.report)
        GD.claim_report(report)
        out.mkdir(parents=True)
        code = code_manifest()
        code_head, code_dirty = GD.check_git_clean(REPO, list(code))
        R = {"schema": "s6.phase1.eval.v1", "set": a.set, "config": set_summary(a.set), "prereg_sha256": pre_sha,
             "git_head": head or code_head, "code_manifest_sha256": manifest_sha(code), "code_dirty": code_dirty,
             "third_party": versions, "cells_sha256": {f"{x}-r{k}": sha(cell_dir(set_root, x, k) / "cell.json") for x, k in cells},
             "train_seconds": {f"{x}-r{k}": r["seconds"] for (x, k), r in recs.items()}}

        def save():
            R["elapsed_s"] = round(time.monotonic() - t0, 1)
            R["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")

        save()
        t = time.monotonic()
        R["verify"] = independent_verify(a.set, out / "verify.json", deadline)
        R["verify_seconds"] = round(time.monotonic() - t, 1)
        save()
        if not R["verify"].get("passed"):
            R["result"] = {"valid": False, "reason": "replay or retraining check failed; the test partition was not read"}
            save()
            say("verification failed; stopping before the test partition")
            return
        if registered:
            GD.consume_final_read(lock, marker, a.approval, pre["final_approval_line"], prereg_sha256=pre_sha, expected_lock=LOCK)
            R["final_read_marker_sha256"] = sha(marker)
            save()
        n_main, n_ext = cfg["worlds"]
        ids = A.eval_world_ids((n_main, n_ext))
        test_eps = {"main6": [W.generate_episode(cfg["test_ns"], w, n, allow_registered=registered) for kind, w, n in ids if kind == "main"],
                    "extrap10": [W.generate_episode(cfg["test_ns"], w, n, allow_registered=registered) for kind, w, n in ids if kind == "extrap"]}
        say("test worlds", {k: len(v) for k, v in test_eps.items()})
        t = time.monotonic()
        arrays = evaluate(cfg, set_root, cells, test_eps, say, deadline)
        R["eval_seconds"] = round(time.monotonic() - t, 1)
        npz = out / "errors.npz"
        with npz.open("xb") as fh:
            np.savez(fh, **arrays)
        (out / "worlds.json").write_text(json.dumps({t: [[ep.world_index, ep.n_disks] for ep in eps] for t, eps in test_eps.items()}), encoding="utf-8")
        R["files_sha256"] = {f.name: sha(f) for f in sorted(out.iterdir())}
        save()
        from ainerzero.v9.experiments.s6 import analysis as AN   # P255; imported here so training never needs it
        last = cfg["sizes"].rounds - 1
        R["result"] = AN.decide(analysis_input(arrays, last))
        R["descriptive"] = {f"round{r}": AN.describe(analysis_input(arrays, r)) for r in range(cfg["sizes"].rounds)}
        R["selection"] = selection_summary(recs, cfg)
        if pre:
            late = GD.check_manifest(REPO, pre["manifest"]) + GD.check_loaded_modules(REPO, pre["manifest"])
            R["late_violations"] = late
            if late:
                R["result"]["valid"] = False
        save()
        say("gates", {g: v.get("passed") for g, v in R["result"].get("gates", {}).items()})


def selection_summary(recs, cfg):
    """Descriptive: per cell and round, the share of picked samples with a disk contact is not known without labels
    here, so only the overlap of each arm's picks with E's picks (same replicate) is reported."""
    out = {}
    for (arm, k), rec in recs.items():
        if arm in ("E", "P") or ("E", k) not in recs:
            continue
        e = recs[("E", k)]["tracks"][0]["picks"]
        mine = rec["tracks"][0]["picks"]
        out[f"{arm}-r{k}"] = [len(set(a) & set(b)) / max(len(a), 1) for a, b in zip(mine[1:], e[1:])]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("train", "eval"))
    ap.add_argument("--set", required=True, choices=sorted(SETS))
    ap.add_argument("--report")
    ap.add_argument("--approval")
    a = ap.parse_args()
    t0 = time.monotonic()

    def say(*x):
        print(f"[{time.monotonic() - t0:8.1f}s]", *x, flush=True)

    if a.stage == "train":
        if a.report or a.approval:
            raise GD.GuardError("train takes neither a report nor an approval line")
        train(a, say)
    else:
        if not a.report:
            raise GD.GuardError("eval needs --report")
        run_eval(a, say)


if __name__ == "__main__":
    main()
