"""S3 第三阶段契约门 K2b：日志与生成器一致（DESIGN-r2 §4）。

在另一个进程里用 python -I 运行，只导入世界生成器（s3/persist.py 及其依赖的第一阶段冻结模块），
不导入 promotion、analysis_p3、cues。按种子重新生成每个世界，独立重算：
  - 驻留观察（估计位姿或中心 token 一变就切分，无 token 的一步结束驻留）；
  - 固定格查询：第 1 回合起每个固定格的真值首次到达，含位姿、地形、显示 token、答案、诱饵、已改；
  - 回合内读回：长间隔且已换的事件；
  - 世界种子与布局哈希。
与 worlds.jsonl 逐条比对。K2 证明「给定这份日志，机制按规格运行」，K2b 把日志钉回生成器。

登记分区只在本阶段那次登记运行内部放行：s3p3-final 要求日志就是 final-final/worlds.jsonl
（解析符号链接后），并且 final 只读一次标记已经写下；本阶段 dev 上限登记为 0，s3p3-dev 一律拒绝。
拒绝都发生在生成任何世界之前。

用法：python -I verify_generation.py <worlds.jsonl> <命名空间> <每个世界的回合数>
"""
import json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import persist as PS, spec  # noqa: E402
from ainerzero.v9.experiments.s3.store import parse_student_step  # noqa: E402

ROOT = REPO / "artifacts/v9/s3/phase3"
FINAL_NAMES = frozenset({"s3p3-final"})
DEV_NAMES = frozenset({"s3p3-dev"})
FORBIDDEN = ("ainerzero.v9.experiments.s3.promotion", "ainerzero.v9.experiments.s3.analysis_p3", "ainerzero.v9.experiments.s3.cues")


def expected(seq):
    obs, queries, fast = [], [], []
    for ep in seq.episodes:
        e = ep.index
        recs = [parse_student_step(s) for s in ep.raw["steps"]]
        prev = None
        for r in recs:
            if r.observed_token > 0:
                key = (r.est_pose[0], r.est_pose[1], r.observed_token)
                if key != prev:
                    obs.append([e, r.t, float(r.est_pose[0]), float(r.est_pose[1]), [int(v) for v in r.world_terrain.reshape(-1)], int(r.observed_token)])
                prev = key
            else:
                prev = None
        if e >= 1:
            for c in seq.persistent:
                for s, r in zip(ep.raw["steps"], recs):
                    if (int(s["truth"]["x"]), int(s["truth"]["y"])) == c:
                        queries.append({
                            "episode": e, "t": r.t, "xy": [float(r.est_pose[0]), float(r.est_pose[1])],
                            "terrain": [int(v) for v in r.world_terrain.reshape(-1)], "shown": int(r.observed_token),
                            "answer": ep.regime[c], "decoy": int(ep.decoy[c]),
                            "relocated": int(e >= PS.RELOCATION_EPISODE and c in seq.relocated),
                        })
                        break
        for ev in ep.raw["events"]:
            if ev["bucket"] == spec.BUCKET_LONG and ev["swapped"]:
                fast.append([e, int(ev["t"]), int(ev["answer"])])
    return obs, queries, fast


KEYS = ("episode", "t", "xy", "terrain", "shown", "answer", "decoy", "relocated")


def authorize(path, ns, *, root, final_names, dev_names, registered):
    """(allowed, reason). A registered partition is regenerated only inside its own registered run."""
    if ns not in registered:
        return True, None
    p, root = Path(path).resolve(), Path(root).resolve()
    if p.name != "worlds.jsonl":
        return False, f"{ns}: the log must be a run's worlds.jsonl"
    if ns in final_names:
        if p.parent != root / "final-final" or not (root / "FINAL_READ_ONCE.json").is_file():
            return False, f"{ns}: only inside the final run, after its read-once marker"
        return True, None
    if ns in dev_names:
        return False, f"{ns}: dev is not used in this phase (its limit is 0)"
    return False, f"{ns}: registered partition with no registered run"


def check_world(lg, ns, n_episodes):
    w = lg["world"]
    seq = PS.generate_sequence(ns, w, n_episodes=n_episodes, allow_registered=ns in PS.REGISTERED)
    obs, queries, fast = expected(seq)
    bad = []
    if lg.get("world_seed") != seq.world_seed or lg.get("layout_sha256") != seq.layout_sha256:
        bad.append(f"world {w}: seed or layout differs from the generator")
    if lg["observations"] != obs:
        bad.append(f"world {w}: observation log differs from the generator ({len(lg['observations'])} vs {len(obs)})")
    logged = [{k: q[k] for k in KEYS} for q in lg["queries"]]
    if logged != queries:
        bad.append(f"world {w}: queries differ from the generator ({len(logged)} vs {len(queries)})")
    if lg["fast_events"] != fast:
        bad.append(f"world {w}: within-episode events differ from the generator ({len(lg['fast_events'])} vs {len(fast)})")
    return bad, len(queries), len(fast), len(obs)


def main(path, ns, n_episodes):
    if FINAL_NAMES | DEV_NAMES != PS.REGISTERED:
        raise SystemExit(f"registered names out of step with the generator: {sorted(PS.REGISTERED)}")
    ok, why = authorize(path, ns, root=ROOT, final_names=FINAL_NAMES, dev_names=DEV_NAMES, registered=PS.REGISTERED)
    if not ok:
        print(json.dumps({"worlds": 0, "queries": 0, "fast_events": 0, "observations": 0, "namespace": ns,
                          "n_problems": 1, "problems": [why], "forbidden_loaded": [], "passed": False}, ensure_ascii=False))
        return
    problems, worlds, n_q, n_f, n_o = [], [], 0, 0, 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            lg = json.loads(line)
            bad, q, f, o = check_world(lg, ns, n_episodes)
            problems += bad
            worlds.append(lg["world"])
            n_q, n_f, n_o = n_q + q, n_f + f, n_o + o
    if worlds != list(range(len(worlds))):
        problems.append("worlds are not 0..n-1 in order")
    loaded = sorted(m for m in sys.modules if m in FORBIDDEN)
    if loaded:
        problems.append(f"forbidden modules loaded: {loaded}")
    out = {"worlds": len(worlds), "queries": n_q, "fast_events": n_f, "observations": n_o, "namespace": ns,
           "n_problems": len(problems), "problems": problems[:20], "forbidden_loaded": loaded,
           "passed": bool(worlds and n_q > 0 and not problems)}
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]))
