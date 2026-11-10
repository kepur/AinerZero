"""S3 第三阶段运行器（DESIGN-r1；预登记 reports/V9-S3-PHASE3/PREREG-r1.json）。纯 CPU，不导入 MLX。

用法（dev、final 必须带新建的字节码目录）：
  python -I -X pycache_prefix=<新目录> run_phase3.py --stage dev --use-id dev1 --purpose <用途> --report <json>
  python -I -X pycache_prefix=<新目录> run_phase3.py --stage final --approval <批准行> --report <json>
  python -I run_phase3.py --stage probe|smoke --use-id <名字> --report <json>

启动顺序：拿锁 → 校验清单、已加载模块、git → 校验分区 → 校验请求 → 检查运行目录、占报告 → 记账。
任何一步失败都不扣次数。smoke、probe 只读 s3p3-probe，不记账，预登记冻结前也能跑。
不用 MLX 也持 m0-worker.lock，与 MLX 运行串行。契约门 K2 由 verify_worlds.py 在子进程里独立复核。
"""
import time

STARTED = time.time()
import argparse, hashlib, json, resource, subprocess, sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import analysis_p3 as A, persist as PS, run_guard as GD

ROOT = REPO / "artifacts/v9/s3/phase3"
PREREG = REPO / "reports/V9-S3-PHASE3/PREREG-r1.json"
VERIFY = REPO / "reports/V9-S3-PHASE3/verify_worlds.py"
LOCK = REPO / "artifacts/locks/m0-worker.lock"
THIRD_PARTY = ("numpy",)
STAGES = {
    "smoke": {"ns": "probe", "worlds": 4, "episodes": 8, "limit": 600},
    "probe": {"ns": "probe", "worlds": 100, "episodes": PS.N_EPISODES, "limit": 1800},
    "dev": {"ns": "dev", "worlds": 100, "episodes": PS.N_EPISODES, "limit": 1800},
    "final": {"ns": "final", "worlds": 200, "episodes": PS.N_EPISODES, "limit": 1800},
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def startup_checks(stage):
    """Run after the lock is held. Returns (prereg or None, its sha, git head, versions)."""
    versions = GD.third_party_versions(REPO, THIRD_PARTY)
    if stage not in ("dev", "final"):
        return None, None, None, versions
    if not sys.flags.isolated:
        raise GD.GuardError("dev and final must run with python -I")
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


def check_request(a, pre):
    """Refuse a malformed request before anything is claimed or spent."""
    if a.use_id is not None and not GD.valid_use_id(a.use_id):
        raise GD.GuardError(f"invalid use id: {a.use_id!r}")
    if a.stage == "dev" and (not a.use_id or not (a.purpose or "").strip()):
        raise GD.GuardError("a dev use needs both a use id and a purpose")
    if a.stage == "final" and (a.approval or "").strip() != pre["final_approval_line"]:
        raise GD.GuardError("missing the unique approval line")


def analyse(ns, n_worlds, n_episodes, *, registered, deadline, say):
    """Main analysis (offset 0, with contract checks and evidence) plus the start-pose offsets of D6."""
    cols = {k: [] for k in A.FIELDS}
    off = {k: {f: [] for f in A.FIELDS} for k in A.OFFSETS}
    logs = []
    for w in range(n_worlds):
        deadline.check()
        seq = PS.generate_sequence(ns, w, n_episodes=n_episodes, allow_registered=registered)
        c, lg = A.analyse_world(seq)
        for f in cols:
            cols[f] += c[f]
        lg["world_seed"], lg["layout_sha256"] = seq.world_seed, seq.layout_sha256
        logs.append(lg)
        for k in A.OFFSETS:
            ck, _ = A.analyse_world(seq, offset=k, full=False)
            for f in off[k]:
                off[k][f] += ck[f]
        if (w + 1) % 25 == 0:
            say("worlds", w + 1)
    return A.to_arrays(cols), logs, {k: A.to_arrays(v) for k, v in off.items()}


def independent_check(worlds):
    """Contract gate K2: the standard-library verifier in a separate isolated process."""
    r = subprocess.run([sys.executable, "-I", str(VERIFY), str(worlds)], capture_output=True, text=True, timeout=1200)
    if r.returncode != 0:
        return {"passed": False, "error": r.stderr[-2000:]}
    return json.loads(r.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=sorted(STAGES))
    ap.add_argument("--use-id")
    ap.add_argument("--purpose")
    ap.add_argument("--approval")
    ap.add_argument("--report", required=True)
    a = ap.parse_args()
    cfg = STAGES[a.stage]
    deadline = GD.Deadline(cfg["limit"])
    t0 = time.monotonic()

    with GD.RunLock(LOCK) as lock:
        pre, pre_sha, head, versions = startup_checks(a.stage)
        ns = A.NAMESPACES[cfg["ns"]]
        GD.check_stage_namespace(a.stage, ns, **A.NAMESPACES)
        check_request(a, pre)
        report = Path(a.report)
        run_id = f"{a.stage}-{a.use_id or 'final'}"
        out = ROOT / run_id
        if out.exists():
            raise GD.GuardError(f"run directory already exists: {out}")
        GD.claim_report(report)
        out.mkdir(parents=True)
        try:
            if a.stage == "dev":
                GD.consume_dev_use(lock, ROOT / "dev_uses.json", a.use_id, a.purpose, max_uses=pre["dev_max_uses"], expected_lock=LOCK)
            elif a.stage == "final":
                GD.consume_final_read(lock, ROOT / "FINAL_READ_ONCE.json", a.approval, pre["final_approval_line"], prereg_sha256=pre_sha, expected_lock=LOCK)
        except GD.GuardError:
            out.rmdir()
            report.unlink()
            raise

        R = {"schema": "s3.phase3.v1", "stage": a.stage, "use_id": a.use_id, "purpose": a.purpose, "namespace": ns,
             "worlds": cfg["worlds"], "episodes": cfg["episodes"], "prereg_sha256": pre_sha, "git_head": head, "third_party": versions}

        def save():
            R["elapsed_s"] = round(time.monotonic() - t0, 1)
            R["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")

        def say(*x):
            print(f"[{time.monotonic() - t0:8.1f}s]", *x, flush=True)

        save()
        ev, logs, off = analyse(ns, cfg["worlds"], cfg["episodes"], registered=a.stage in ("dev", "final"), deadline=deadline, say=say)
        files = {"events.npz": ev} | {f"events_k{k}.npz": v for k, v in off.items()}
        for name, arrays in files.items():
            np.savez_compressed(out / name, **arrays)
        worlds = out / "worlds.jsonl"
        with worlds.open("x", encoding="utf-8") as fh:
            for lg in logs:
                fh.write(json.dumps(lg, ensure_ascii=False, sort_keys=True) + "\n")
        R["files_sha256"] = {name: sha(out / name) for name in list(files) + [worlds.name]}
        deadline.check()
        external = independent_check(worlds)
        R["result"] = A.evaluate(ev, logs, stage=a.stage if a.stage != "smoke" else None, n_worlds=cfg["worlds"], external=external, offsets=off)
        if pre:
            late = GD.check_manifest(REPO, pre["manifest"]) + GD.check_loaded_modules(REPO, pre["manifest"])
            R["late_violations"] = late
            if late:
                R["result"] = A.invalidated(R["result"], "frozen files or modules changed during the run")
        save()
        lg = R["result"]["legality"]
        say("valid", R["result"]["valid"], {k: v["passed"] for k, v in lg.items() if isinstance(v, dict)})


if __name__ == "__main__":
    main()
