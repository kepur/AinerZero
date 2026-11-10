"""S4 第一阶段合法性门「标签」：由接触日志独立重算重新出现事件与「有碰撞」（DESIGN-r3 §4、§5）。

在另一个进程里用 python -I 运行，只用标准库，不导入 ainerzero。读运行器写下的 labels.jsonl
（每步的可见性、被检测到的真值编号、盘—盘接触）与 worlds.jsonl（逐世界记录），独立重算：
  - 重新出现事件：物体在 a 步可见且被检测到，a+1…b−1 步不可见，b 步可见且被检测到（b − a ≥ 2）；
  - 「有碰撞」：a ≤ s < b 的某一步里接触日志记有它与另一个盘的接触；
  - 动力学门的碰撞盘步数：除最后一步外，每步出现在盘—盘接触里的盘数之和，与 E-B 的 n_coll 比对。
用法：python -I verify_labels.py <labels.jsonl> <worlds.jsonl>，结果以 JSON 打印到标准输出。
"""
import json
import sys


def events(log):
    vis = [[c == "1" for c in row] for row in log["visible"]]
    det = [set(d) for d in log["detected"]]
    touched = []
    for pairs in log["disk_contacts"]:
        s = set()
        for i, j in pairs:
            s.add(i)
            s.add(j)
        touched.append(s)
    out = []
    for k in range(log["n_disks"]):
        last = None
        for t in range(len(vis)):
            if not vis[t][k]:
                continue
            if last is not None and t - last >= 2 and k in det[last] and k in det[t]:
                out.append([k, last, t, int(any(k in touched[s] for s in range(last, t)))])
            last = t
    n_coll = sum(len(touched[s]) for s in range(len(touched) - 1))
    return out, n_coll


def main():
    labels = [json.loads(x) for x in open(sys.argv[1], encoding="utf-8")]
    records = [json.loads(x) for x in open(sys.argv[2], encoding="utf-8")]
    bad = []
    if [(r["kind"], r["world"]) for r in records] != [(g["kind"], g["world"]) for g in labels]:
        bad.append("the world lists differ")
    n_ev = n_cev = 0
    for g, r in zip(labels, records):
        ev, n_coll = events(g)
        n_ev += len(ev)
        n_cev += sum(e[3] for e in ev)
        if sorted(ev) != sorted(r["events"]) or len(ev) != len(r["events"]):
            bad.append(f"{g['kind']} {g['world']}: events differ ({len(ev)} recomputed, {len(r['events'])} recorded)")
        if r["dyn"]["E-B"]["n_coll"] != n_coll:
            bad.append(f"{g['kind']} {g['world']}: collision disk-steps {n_coll} recomputed, {r['dyn']['E-B']['n_coll']} recorded")
        for key, c in r["reid"].items():
            if len(c) != len(r["events"]):
                bad.append(f"{g['kind']} {g['world']}: {key} scored {len(c)} of {len(r['events'])} events")
                break
    print(json.dumps({"passed": not bad, "worlds": len(labels), "events": n_ev, "collision_events": n_cev, "mismatches": bad[:20]}))


if __name__ == "__main__":
    main()
