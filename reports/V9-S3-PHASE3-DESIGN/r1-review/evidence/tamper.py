"""K2 的篡改实验（复核者自写）。只读一个真实的 worlds.jsonl，所有篡改写到输出目录的新文件。

用法：tamper.py <副本根> <worlds.jsonl> <输出目录>
A 只改版本 token（不重算）；B 改 token 并重算整条哈希链和查询答案（不改观察日志）；
C 改观察日志里的 token，并用校验器自己的规则重建版本、重答查询（一致的伪造）；
D 删掉若干世界；E 把查询记录的位姿换成别处并一致地重答。
"""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

COPY, SRC, OUT = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
VPATH = COPY + "/reports/V9-S3-PHASE3/verify_worlds.py"
spec = importlib.util.spec_from_file_location("vw", VPATH)
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)  # 只用标准库
worlds = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines()]


def run(name, ws):
    p = OUT / f"{name}.jsonl"
    p.write_text("".join(json.dumps(w, ensure_ascii=False, sort_keys=True) + "\n" for w in ws), encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", VPATH, str(p)], capture_output=True, text=True)
    out = json.loads(r.stdout)
    return {"passed": out["passed"], "worlds": out["worlds"], "queries": out["queries"], "n_problems": out["n_problems"],
            "first_problem": (out["problems"] or [None])[0], "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def reanswer(w):
    """用校验器自己的函数，按观察日志重建版本并重答全部查询。返回改变了的 G 答案个数。"""
    w["versions"] = V.rebuild(w["observations"])
    changed = 0
    for q in w["queries"]:
        in_force = [x for x in w["versions"] if x["episode"] < q["episode"]][-1]
        q["version"] = in_force["hash"]
        slow = V.best([(it[0], it[2], it[3], it[1]) for it in sorted(in_force["items"], key=lambda r: r[0])], q["xy"], q["terrain"])
        latest, when = None, None
        for e, t, x, y, ter, tok in w["observations"]:
            if e < q["episode"]:
                ok, _ = V.place([x, y], ter, q["xy"], q["terrain"])
                if ok and (when is None or e * V.T + t > when):
                    latest, when = tok, e * V.T + t
        L = q["shown"] if latest is None else latest
        G = L if slow is None else slow
        changed += int(G != q["pred_G"])
        q["pred_L"], q["pred_G"], q["slow"] = L, G, slow
    return changed


res = {"source_sha256": hashlib.sha256(SRC.read_bytes()).hexdigest(), "true_log": run("true", worlds)}
w0 = next(i for i, w in enumerate(worlds) if len(w["versions"]) > 2)

# A：只改一个版本的 token
ws = copy.deepcopy(worlds); v = ws[w0]["versions"][1]; it = v["items"][0]
it[1] = next(k for k in range(1, 9) if k != it[1])
res["A_token_no_rehash"] = run("A", ws)

# B：改 token，重算整条链，并把查询改成一致的答案；观察日志不动
ws = copy.deepcopy(worlds); W = ws[w0]
old = W["versions"][1]["items"][0][1]; new = next(k for k in range(1, 9) if k != old)
for v in W["versions"][1:]:
    for it in v["items"]:
        if it[0] == W["versions"][1]["items"][0][0] and it[1] == old:
            it[1] = new
for i, v in enumerate(W["versions"]):
    v["parent"] = W["versions"][i - 1]["hash"] if i else None
    v["hash"] = V.vhash(v["parent"], v["episode"], v["items"])
by_ep = {}
for q in W["queries"]:
    in_force = [x for x in W["versions"] if x["episode"] < q["episode"]][-1]
    q["version"] = in_force["hash"]
    slow = V.best([(it[0], it[2], it[3], it[1]) for it in sorted(in_force["items"], key=lambda r: r[0])], q["xy"], q["terrain"])
    q["pred_G"] = q["pred_L"] if slow is None else slow
    q["slow"] = slow
res["B_rehash_versions_and_answers"] = run("B", ws)

# C：一致地改写观察日志：把第一个已晋升条目附近、投给它的 token 的观察全部换成另一个 token
ws = copy.deepcopy(worlds); W = ws[w0]
iid, tok, axy, ater, _ = W["versions"][1]["items"][0]
new = next(k for k in range(1, 9) if k != tok)
n_obs = 0
for o in W["observations"]:
    ok, _ = V.place(axy, ater, [o[2], o[3]], o[4])
    if ok and o[5] == tok:
        o[5] = new; n_obs += 1
n_changed = reanswer(W)
res["C_consistent_rewrite_of_observations"] = run("C", ws) | {"observations_changed": n_obs, "G_answers_changed": n_changed}

# D：删掉一半世界
res["D_half_the_worlds_dropped"] = run("D", worlds[: len(worlds) // 2])

# E：把一个查询的位姿换成另一个查询的位姿，并一致地重答
ws = copy.deepcopy(worlds); W = ws[w0]
qa, qb = W["queries"][0], next(q for q in W["queries"][1:] if q["xy"] != W["queries"][0]["xy"] and q["episode"] >= W["queries"][0]["episode"])
qa["xy"], qa["terrain"] = list(qb["xy"]), list(qb["terrain"])
n_changed = reanswer(W)
res["E_query_pose_moved_and_reanswered"] = run("E", ws) | {"G_answers_changed": n_changed}

json.dump(res, open(OUT / "tamper_results.json", "w"), ensure_ascii=False, indent=1)
for k, v in res.items():
    print(k, v if isinstance(v, str) else {kk: vv for kk, vv in v.items() if kk != "sha256"})
