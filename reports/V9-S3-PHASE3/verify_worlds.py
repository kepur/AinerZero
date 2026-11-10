"""S3 第三阶段契约门 K2：独立复核 worlds.jsonl（DESIGN-r1 §4）。

只用标准库，不导入任何项目代码；由运行器在另一个进程里用 python -I 调用。
从落盘的观察日志出发，独立重建条目、投票和规则 R2，重算版本链，和记录的版本逐个比对；
再用查询所用的版本和观察日志重答每个固定格查询，与记录的 G、L 逐条比对。

用法：python -I verify_worlds.py <worlds.jsonl>   结果以一行 JSON 打到标准输出。
"""
import collections, hashlib, json, sys

D_MAX, SCALE, LAM, MIN_VOTES, T = 5.0, 49.0, 1.0, 2, 360


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def vhash(parent, episode, items):
    return hashlib.sha256(canon({"parent": parent, "episode": episode, "items": items}).encode()).hexdigest()


def place(axy, ater, xy, ter):
    d = abs(float(axy[0]) - float(xy[0])) + abs(float(axy[1]) - float(xy[1]))
    sim = sum(1 for a, b in zip(ater, ter) if int(a) == int(b)) / len(ater)
    return (d <= D_MAX and sim >= 1.0), sim * SCALE * LAM - d


def best(cands, xy, ter):
    """cands: (id, anchor_xy, anchor_ter, payload) in id order -> payload of the best eligible, ties to lowest id."""
    out, top = None, None
    for _id, axy, ater, payload in cands:
        ok, s = place(axy, ater, xy, ter)
        if ok and (top is None or s > top):
            out, top = payload, s
    return out


def pick(cands, counts, votes):
    last = {k: max(i for i, x in enumerate(votes) if x == k) for k in cands}
    return max(cands, key=lambda k: (counts[k], last[k]))


def rule(votes, slow):
    if slow is None:
        cnt = collections.Counter(votes)
        ok = [k for k, n in cnt.items() if n >= MIN_VOTES]
        return pick(ok, cnt, votes) if ok else None
    last = max([i for i, x in enumerate(votes) if x == slow] or [-1])
    after = collections.Counter(votes[last + 1:])
    ok = [k for k, n in after.items() if n >= MIN_VOTES and k != slow]
    return pick(ok, after, votes) if ok else slow


def rebuild(observations):
    """Independent re-implementation of the promotion store with rollback; returns the version list."""
    items = []  # [id, anchor_xy, anchor_ter, votes, slow]
    versions = [{"parent": None, "episode": -1, "items": []}]
    versions[0]["hash"] = vhash(None, -1, [])
    by_ep = collections.defaultdict(list)
    for e, t, x, y, ter, tok in observations:
        by_ep[e].append((t, [x, y], ter, tok))
    last_ep = max(by_ep) if by_ep else -1
    for e in range(last_ep + 1):
        per = {}
        for t, xy, ter, tok in by_ep.get(e, []):
            j = best([(it[0], it[1], it[2], it[0]) for it in items], xy, ter)
            if j is None:
                j = len(items)
                items.append([j, [float(xy[0]), float(xy[1])], [int(v) for v in ter], [], None])
            per.setdefault(j, collections.Counter())[int(tok)] += 1
        changed = False
        for j in sorted(per):
            items[j][3].append([e, per[j].most_common(1)[0][0]])
            new = rule([k for _, k in items[j][3]], items[j][4])
            if new != items[j][4]:
                items[j][4] = new
                changed = True
        if changed:
            snap = [[it[0], it[4], list(it[1]), list(it[2]), [list(v) for v in it[3]]] for it in items if it[4] is not None]
            parent = versions[-1]["hash"]
            versions.append({"parent": parent, "episode": e, "items": snap, "hash": vhash(parent, e, snap)})
    return versions


def check_world(w):
    bad = []
    versions = w["versions"]
    for i, v in enumerate(versions):
        parent = versions[i - 1]["hash"] if i else None
        if v["parent"] != parent:
            bad.append(f"world {w['world']} version {i}: parent link broken")
        if vhash(v["parent"], v["episode"], v["items"]) != v["hash"]:
            bad.append(f"world {w['world']} version {i}: hash does not recompute")
        prev = {it[0]: it for it in versions[i - 1]["items"]} if i else {}
        cur = {it[0]: it for it in v["items"]}
        for iid in prev:
            if iid not in cur:
                bad.append(f"world {w['world']} version {i}: promoted item {iid} disappeared")
        for iid, tok, axy, ater, votes in v["items"]:
            eps = [e for e, _ in votes]
            toks = [k for _, k in votes]
            if eps != sorted(set(eps)) or (eps and eps[-1] > v["episode"]):
                bad.append(f"world {w['world']} version {i} item {iid}: votes not one per earlier episode")
            if toks.count(tok) < MIN_VOTES:
                bad.append(f"world {w['world']} version {i} item {iid}: fewer than {MIN_VOTES} votes for its token")
            if iid in prev:
                old = prev[iid]
                if old[2] != axy or old[3] != ater:
                    bad.append(f"world {w['world']} version {i} item {iid}: anchor changed")
                if old[1] != tok:
                    last = max([j for j, k in enumerate(toks) if k == old[1]] or [-1])
                    if toks[last + 1:].count(tok) < MIN_VOTES:
                        bad.append(f"world {w['world']} version {i} item {iid}: replaced without {MIN_VOTES} later votes")
    rebuilt = rebuild(w["observations"])
    if [v["hash"] for v in rebuilt] != [v["hash"] for v in versions]:
        bad.append(f"world {w['world']}: versions do not follow from the observation log")
    by_hash = {v["hash"]: v for v in versions}
    obs = w["observations"]
    for q in w["queries"]:
        v = by_hash.get(q["version"])
        in_force = [x for x in versions if x["episode"] < q["episode"]]
        if v is None or not in_force or in_force[-1]["hash"] != q["version"]:
            bad.append(f"world {w['world']} episode {q['episode']} t {q['t']}: query does not use the version in force")
            continue
        slow = best([(it[0], it[2], it[3], it[1]) for it in sorted(v["items"], key=lambda r: r[0])], q["xy"], q["terrain"])
        latest, when = None, None
        for e, t, x, y, ter, tok in obs:
            if e < q["episode"]:
                ok, _ = place([x, y], ter, q["xy"], q["terrain"])
                if ok and (when is None or e * T + t > when):
                    latest, when = tok, e * T + t
        L = q["shown"] if latest is None else latest
        G = L if slow is None else slow
        if L != q["pred_L"] or G != q["pred_G"]:
            bad.append(f"world {w['world']} episode {q['episode']} t {q['t']}: re-answer differs (L {L} vs {q['pred_L']}, G {G} vs {q['pred_G']})")
    return bad, len(w["queries"]), len(versions) - 1


def main(path):
    problems, n_q, n_v, n_w = [], 0, 0, 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            w = json.loads(line)
            bad, q, v = check_world(w)
            problems += bad
            n_q, n_v, n_w = n_q + q, n_v + v, n_w + 1
    out = {"worlds": n_w, "queries": n_q, "versions": n_v, "n_problems": len(problems), "problems": problems[:20],
           "passed": bool(n_w > 0 and n_q > 0 and not problems)}
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
