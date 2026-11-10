"""K2、K2b 的篡改实验（复核者自写，r2）。只读一个真实的 worlds.jsonl，所有篡改写到输出目录的新文件。

用法：tamper_r2.py <副本根> <worlds.jsonl> <命名空间> <回合数> <登记世界数> <登记查询数> <输出目录>
r1 的 A–E 加上：F 改回合内读回的答案；G 调换两个世界；H 重复一个世界；I 一致地改查询标签；
J 把查询答案改成别的再一致地重答（不碰观察）；K 一致改写观察日志，同时改世界种子字段。
每个文件跑 K2（verify_worlds.py）和 K2b（verify_generation.py），并按 analysis_p3.legality 的口径核对数量（K2(e)）。
"""
import copy, hashlib, importlib.util, json, subprocess, sys
from pathlib import Path

COPY, SRC, NS, NEP, NW, NQ, OUT = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5]), int(sys.argv[6]), Path(sys.argv[7])
OUT.mkdir(parents=True, exist_ok=True)
D = COPY + "/reports/V9-S3-PHASE3/"
spec = importlib.util.spec_from_file_location("vw", D + "verify_worlds.py")
V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)
worlds = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines()]


def sub(script, *args):
    r = subprocess.run([sys.executable, "-I", D + script, *map(str, args)], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else {"passed": False, "error": r.stderr[-300:]}


def run(name, ws, nq=NQ):
    p = OUT / f"{name}.jsonl"
    p.write_text("".join(json.dumps(w, ensure_ascii=False, sort_keys=True) + "\n" for w in ws), encoding="utf-8")
    k2, k2b = sub("verify_worlds.py", p), sub("verify_generation.py", p, NS, NEP)
    k2_gate = bool(k2.get("passed") and k2.get("worlds") == NW and k2.get("queries") == nq)
    k2b_gate = bool(k2b.get("passed") and k2b.get("worlds") == NW and k2b.get("queries") == nq)
    return {"K2_gate": k2_gate, "K2b_gate": k2b_gate, "caught": not (k2_gate and k2b_gate),
            "K2_first_problem": (k2.get("problems") or [None])[0], "K2b_first_problem": (k2b.get("problems") or [None])[0],
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def reanswer(w):
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

ws = copy.deepcopy(worlds); it = ws[w0]["versions"][1]["items"][0]; it[1] = next(k for k in range(1, 9) if k != it[1])
res["A_token_no_rehash"] = run("A", ws)

ws = copy.deepcopy(worlds); W = ws[w0]
iid, old = W["versions"][1]["items"][0][0], W["versions"][1]["items"][0][1]
new = next(k for k in range(1, 9) if k != old)
for v in W["versions"][1:]:
    for it in v["items"]:
        if it[0] == iid and it[1] == old:
            it[1] = new
for i, v in enumerate(W["versions"]):
    v["parent"] = W["versions"][i - 1]["hash"] if i else None
    v["hash"] = V.vhash(v["parent"], v["episode"], v["items"])
for q in W["queries"]:
    in_force = [x for x in W["versions"] if x["episode"] < q["episode"]][-1]
    q["version"] = in_force["hash"]
    slow = V.best([(it[0], it[2], it[3], it[1]) for it in sorted(in_force["items"], key=lambda r: r[0])], q["xy"], q["terrain"])
    q["pred_G"] = q["pred_L"] if slow is None else slow
    q["slow"] = slow
res["B_rehash_versions_and_answers"] = run("B", ws)

ws = copy.deepcopy(worlds); W = ws[w0]
iid, tok, axy, ater, _ = W["versions"][1]["items"][0]
new = next(k for k in range(1, 9) if k != tok); n_obs = 0
for o in W["observations"]:
    ok, _ = V.place(axy, ater, [o[2], o[3]], o[4])
    if ok and o[5] == tok:
        o[5] = new; n_obs += 1
n_changed = reanswer(W)
res["C_consistent_rewrite_of_observations"] = run("C", ws) | {"observations_changed": n_obs, "G_answers_changed": n_changed}

half = worlds[: len(worlds) // 2]
res["D_half_the_worlds_dropped"] = run("D", half, nq=NQ)

ws = copy.deepcopy(worlds); W = ws[w0]
qa = W["queries"][0]
qb = next(q for q in W["queries"][1:] if q["xy"] != qa["xy"] and q["episode"] >= qa["episode"])
qa["xy"], qa["terrain"] = list(qb["xy"]), list(qb["terrain"])
n_changed = reanswer(W)
res["E_query_pose_moved_and_reanswered"] = run("E", ws) | {"G_answers_changed": n_changed}

ws = copy.deepcopy(worlds); fe = ws[w0]["fast_events"][0]; fe[2] = next(k for k in range(1, 9) if k != fe[2])
res["F_fast_event_answer_changed"] = run("F", ws)

ws = copy.deepcopy(worlds); ws[0], ws[1] = ws[1], ws[0]
res["G_two_worlds_swapped"] = run("G", ws)

ws = copy.deepcopy(worlds); ws[1] = copy.deepcopy(ws[0])
res["H_world_duplicated"] = run("H", ws)

ws = copy.deepcopy(worlds); q = next(x for x in ws[w0]["queries"] if x["decoy"] == 0)
q["decoy"] = 1
res["I_query_label_changed"] = run("I", ws)

ws = copy.deepcopy(worlds); q = ws[w0]["queries"][0]; q["answer"] = next(k for k in range(1, 9) if k != q["answer"])
res["J_query_answer_changed"] = run("J", ws)

ws = copy.deepcopy(worlds); W = ws[w0]
for o in W["observations"]:
    ok, _ = V.place(axy, ater, [o[2], o[3]], o[4])
    if ok and o[5] == tok:
        o[5] = new
reanswer(W); W["world_seed"] = 12345
res["K_rewrite_observations_and_seed_field"] = run("K", ws)

json.dump(res, open(OUT / "tamper_r2_results.json", "w"), ensure_ascii=False, indent=1)
for k, v in res.items():
    print(k, v if isinstance(v, str) else {kk: vv for kk, vv in v.items() if kk != "sha256"})
