"""S4 第二阶段运行器（reports/V9-S4-P2-DESIGN；预登记 reports/V9-S4-PHASE2/PREREG-r1.json）。

用法：
  python -I -X pycache_prefix=<新目录> run_s4p2.py --stage final --approval <批准行> --report <json>
  python -I run_s4p2.py --stage smoke|probe --use-id <名字> --report <json>

- 不训练。一期 final 的 L-int#1–3、L-ind#1–3 权重只读，启动时逐个核对 SHA，不符即拒绝；
- smoke 只读替身命名空间 s4p2x-smoke-eval（主评测 4 个、外推 2 个世界），不碰登记分区；
- probe 评测 s4p2-probe（主评测 0–49 号 6 盘，外推 1000–1024 号 10 盘）；
- final 评测 s4p2-final（主评测 0–199 号，外推 1000–1099 号）。

启动顺序：拿锁 → python -I、新字节码目录、冻结清单、已加载模块、第三方版本、git（final）→ 权重 SHA → 分区
→ 请求 → final 只读一次标记是否已存在 → 运行目录、占报告。任何一步失败都不写标记。
final 的只读一次标记写在剩余墙钟够评测预留之后、生成第一个登记世界之前。
评测在 spawn 出的 CPU 工作进程里，世界只由主进程生成后传入，逐世界追加落盘。
合法性门：标签与确定性由 verify_labels_p2.py、verify_replay_p2.py 在另一个 python -I 进程里复核；
学生视图在主进程里做字段白名单与未来帧变异。
"""
import time

STARTED = time.time()
import argparse, hashlib, json, math, multiprocessing as mp, resource, subprocess, sys  # noqa: E401,F401
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx  # noqa: E402

from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis_p2 as P2  # noqa: E402
from ainerzero.v9.experiments.s4 import filter as F  # noqa: E402
from ainerzero.v9.experiments.s4 import models as Mo  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s4 import worker_p2 as WK  # noqa: E402

HERE = REPO / "reports/V9-S4-PHASE2"
ROOT = REPO / "artifacts/v9/s4/phase2"
PREREG = HERE / "PREREG-r1.json"
VERIFY_LABELS = HERE / "verify_labels_p2.py"
VERIFY_REPLAY = HERE / "verify_replay_p2.py"
LOCK = REPO / "artifacts/locks/m0-worker.lock"
FINAL_MARKER = ROOT / "FINAL_READ_ONCE.json"
THIRD_PARTY = ("numpy", "mlx")
SMOKE_NS = "s4p2x-smoke-eval"
WEIGHTS_DIR = REPO / "artifacts/v9/s4/phase1/final-final/weights"
WEIGHTS_SHA256 = {   # phase-1 final (reports/V9-S4-PHASE1/final/final.json, files_sha256)
    "L-int#1": "88ea6c9b619098e0b0e5db39f95f9e4c1c61dedaa3e54132c550c4cc4632020c",
    "L-int#2": "c99bc0f709e36f674c7165751348fba0263ac294a996fbc3276a9f36e0437d3f",
    "L-int#3": "241659f14be2b29e655de0f6785672a3f1c4e1529abb7f8db08734002e65cba6",
    "L-ind#1": "a4905a8c79c5ab02ec7e68ef0ba094b4ef4173886a731d9cd8c761d30500fd04",
    "L-ind#2": "8447cee6a2920e853853e3169ac7689db27aedf3ccd441d77736fa8e6208ada5",
    "L-ind#3": "191dcf99913f47e48537d28af4836195adc238adc8e7fe6c9f6869007b0401bc",
}
WORKERS = 6
REPLAY_WORLDS = {"main": 3, "extrap": 2}
STUDENT_WORLDS, STUDENT_CUT = 2, 150
STAGES = {
    "smoke": {"sizes": (4, 2), "limit": 1800},
    "probe": {"sizes": P2.SIZES["probe"], "limit": 2 * 3600},
    "final": {"sizes": P2.SIZES["final"], "limit": 2 * 3600},
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def code_manifest():
    return GD.build_manifest(REPO, [Path(__file__).resolve()], src_root=REPO / "src", extra=[VERIFY_LABELS, VERIFY_REPLAY])


def manifest_sha(m):
    return hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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
    if pre.get("weights_sha256") != WEIGHTS_SHA256:
        raise GD.GuardError("the weights registered in the preregistration differ from the runner's")
    head, dirty = GD.check_git_clean(REPO, list(pre["manifest"]) + [str(PREREG.relative_to(REPO))])
    if dirty:
        raise GD.GuardError("frozen files are not committed: " + "; ".join(dirty[:6]))
    return pre, sha(PREREG), head, versions


def check_weights():
    """Every phase-1 weight file the arms use, present and with its registered SHA. Returns name -> path."""
    out, bad = {}, []
    for name, want in WEIGHTS_SHA256.items():
        p = WEIGHTS_DIR / f"{name}.safetensors"
        if not p.is_file() or sha(p) != want:
            bad.append(name)
        out[name] = str(p)
    if bad:
        raise GD.GuardError(f"weights missing or changed: {bad}")
    if sorted(out) != sorted(WK.weight_names()):
        raise GD.GuardError("the registered weights do not match the arms")
    return out


def namespace(stage):
    if stage == "smoke":
        if SMOKE_NS in set(P2.NAMESPACES.values()) | set(W.REGISTERED):
            raise GD.GuardError(f"smoke must not read a registered partition: {SMOKE_NS}")
        return SMOKE_NS
    ns = P2.NAMESPACES[stage]
    if len(set(P2.NAMESPACES.values())) != 2:
        raise GD.GuardError("partitions must be distinct")
    if stage == "probe" and ns in W.REGISTERED:
        raise GD.GuardError("probe must not read the registered final partition")
    if stage == "final" and ns not in W.REGISTERED:
        raise GD.GuardError("the final partition must be registered in the world module")
    return ns


def check_request(a, pre):
    """Refuse a malformed request before anything is claimed or spent."""
    if a.use_id is not None and not GD.valid_use_id(a.use_id):
        raise GD.GuardError(f"invalid use id: {a.use_id!r}")
    if a.stage in ("smoke", "probe"):
        if not a.use_id:
            raise GD.GuardError(f"a {a.stage} run needs a use id")
        if a.approval:
            raise GD.GuardError("only final takes an approval line")
        return
    if a.use_id is not None:
        raise GD.GuardError("final takes no use id")
    if (a.approval or "").strip() != pre["final_approval_line"]:
        raise GD.GuardError("missing the unique approval line")


# --- legality helpers --------------------------------------------------------------------------------
def student_check(eps, weights):
    """Field whitelist and future-frame mutation (as phase 1), on E-P and L-int-g seed 1."""
    keys_ok = W.STUDENT_KEYS == {"t", "agent", "detections"} and all(set(W.student_view(s)) == W.STUDENT_KEYS for ep in eps for s in ep.steps)
    models, _, _ = WK.build_models(weights)
    use = {"E-P": Mo.true_physics, f"{P2.MAIN_ARM}#1": models[f"{P2.MAIN_ARM}#1"]}
    rows = []
    for ep in eps[:STUDENT_WORLDS]:
        dets = A.student_detections(ep)
        mut = A.future_mutation(dets, STUDENT_CUT)
        for name, m in use.items():
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


def evaluate_parallel(tasks, weights, deadline, say, partial):
    """Worlds in parallel workers; each record is appended to ``partial`` as soon as it arrives."""
    ctx = mp.get_context("spawn")
    results = [None] * len(tasks)
    fh = partial.open("x", encoding="utf-8")
    with ProcessPoolExecutor(WORKERS, mp_context=ctx, initializer=WK.init, initargs=(weights,)) as ex:
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


def label_log(kind, ep):
    return A.label_log(kind, ep)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=sorted(STAGES))
    ap.add_argument("--use-id")
    ap.add_argument("--approval")
    ap.add_argument("--report", required=True)
    a = ap.parse_args()
    cfg = STAGES[a.stage]
    deadline = GD.Deadline(cfg["limit"])
    t0 = time.monotonic()
    mx.set_default_device(mx.cpu)

    with GD.RunLock(LOCK) as lock:
        pre, pre_sha, head, versions = startup_checks(a.stage)
        weights = check_weights()
        ns = namespace(a.stage)
        check_request(a, pre)
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
        R = {"schema": "s4.phase2.v1", "stage": a.stage, "use_id": a.use_id, "namespace": ns, "sizes": cfg["sizes"],
             "prereg_sha256": pre_sha, "git_head": head or code_head, "code_manifest_sha256": manifest_sha(code),
             "code_dirty": code_dirty, "third_party": versions, "arms": list(P2.HAND + P2.LEARNED), "gates": P2.GATES,
             "weights_sha256": {n: sha(p) for n, p in weights.items()}, "workers": WORKERS}

        def save():
            R["elapsed_s"] = round(time.monotonic() - t0, 1)
            R["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")

        def say(*x):
            print(f"[{time.monotonic() - t0:8.1f}s]", *x, flush=True)

        save()
        deadline.check()
        R["pre_eval_seconds"] = round(time.monotonic() - t0, 1)

        registered = a.stage == "final"
        if registered:
            reserve = float(pre["budget"]["eval_reserve_s"])
            if deadline.left() < reserve:
                raise GD.GuardError(f"only {deadline.left():.0f} s left, the evaluation needs {reserve:.0f} s: the final read is not spent")
            # The one read of the registered partition starts here; nothing above generates it.
            GD.consume_final_read(lock, FINAL_MARKER, a.approval, pre["final_approval_line"], prereg_sha256=pre_sha, expected_lock=LOCK)
            R["final_read_marker_sha256"] = sha(FINAL_MARKER)
            save()
        t_post = time.monotonic()                                   # everything from here on is what the reserve must cover
        eval_eps = [(kind, W.generate_episode(ns, w, n, allow_registered=registered)) for kind, w, n in P2.eval_world_ids(cfg["sizes"])]
        say("evaluation worlds", len(eval_eps))
        tasks = [{"kind": kind, "ns": ns, "episode": ep} for kind, ep in eval_eps]
        t_eval = time.monotonic()
        records = evaluate_parallel(tasks, weights, deadline, say, out / "worlds.partial.jsonl")
        R["eval_seconds"] = round(time.monotonic() - t_eval, 1)

        worlds = out / "worlds.jsonl"
        with worlds.open("x", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        labels = out / "labels.jsonl"
        with labels.open("x", encoding="utf-8") as fh:
            for kind, ep in eval_eps:
                fh.write(json.dumps(label_log(kind, ep), sort_keys=True) + "\n")
        replay = out / "replay.json"
        picks = []
        for kind, k in REPLAY_WORLDS.items():
            picks += [(kd, ep) for kd, ep in eval_eps if kd == kind][:k]
        replay.write_text(json.dumps({"ns": ns, "weights": {n: str(Path(p).relative_to(REPO)) for n, p in weights.items()},
                                      "worlds": [{"kind": kd, "world": ep.world_index, "pillars": [list(p) for p in ep.pillars],
                                                  "detections": [d.tolist() for d in A.student_detections(ep)],
                                                  "truth_ids": [s.truth_ids.tolist() for s in ep.steps]} for kd, ep in picks]}), encoding="utf-8")
        R["files_sha256"] = {f.name: sha(f) for f in (worlds, out / "worlds.partial.jsonl", labels, replay)}
        save()

        t_chk = time.monotonic()
        st = student_check([ep for kind, ep in eval_eps if kind == "main"], weights)
        lab = independent_check(VERIFY_LABELS, labels, worlds, deadline=deadline)
        rep = independent_check(VERIFY_REPLAY, replay, worlds, deadline=deadline)
        R["check_seconds"] = round(time.monotonic() - t_chk, 1)
        on_disk = [json.loads(line) for line in worlds.read_text(encoding="utf-8").splitlines()]
        main_r = [r for r in on_disk if r["kind"] == "main"]
        ext_r = [r for r in on_disk if r["kind"] == "extrap"]
        weights_ok = all(sha(p) == WEIGHTS_SHA256[n] for n, p in weights.items())
        R["checks"] = {"student_view": st, "labels": lab, "replay": rep, "weights": {"passed": weights_ok}}
        R["result"] = P2.evaluate(main_r, ext_r, n_main=cfg["sizes"][0], n_extrap=cfg["sizes"][1], labels_ok=bool(lab.get("passed")),
                                  student_ok=st["passed"], replay_ok=bool(rep.get("passed")), weights_ok=weights_ok)
        R["descriptive"] = P2.summarize_descriptive(main_r, ext_r, P2.HAND + P2.LEARNED)
        R["descriptive"]["kstep_position_error"] = kstep_summary(main_r)
        if pre:
            late = GD.check_manifest(REPO, pre["manifest"]) + GD.check_loaded_modules(REPO, pre["manifest"])
            R["late_violations"] = late
            if late:
                R["result"]["valid"] = False
                for g in R["result"]["gates"].values():
                    g["passed"], g["void"] = False, "frozen files or modules changed during the run"
        R["post_marker_seconds"] = round(time.monotonic() - t_post, 1)
        save()
        say("valid", R["result"]["valid"], {k: v["passed"] for k, v in R["result"]["gates"].items()})


def kstep_summary(main_r):
    ks = {}
    for r in main_r:
        for name, sums in r.get("kstep", {}).items():
            arm = name.split("#")[0]
            for k, (s, n) in sums.items():
                acc = ks.setdefault(arm, {}).setdefault(k, [0.0, 0])
                acc[0] += s; acc[1] += n
    return {a: {k: v[0] / v[1] for k, v in d.items() if v[1]} for a, d in ks.items()}


if __name__ == "__main__":
    main()
