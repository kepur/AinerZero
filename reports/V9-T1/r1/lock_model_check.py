"""穷举两进程交错，检查运行模式的互斥协议（ainerzero.V9.T1 r1，回应 Codex 2026-10-16 退回）。

用法：python3 -I reports/V9-T1/r1/lock_model_check.py <result.json>
每个进程是一串原子步：try(锁) 非阻塞取锁（失败就放弃退出）、rel(锁) 释放、enter/leave 进入/离开“占用计算”的区间。
两个进程的所有交错都枚举一遍；只要出现两方同时处在占用区间，就是互斥违例。
- r0 协议（被退回的设计）：应能找出违例，作为反例；
- r1 协议（修订设计：所有模式在整个占用区间持有同一把 m0-worker.lock）：任何组合都不得出现违例。
另外故意改坏 r1（例如 Teacher 取锁后马上释放），检查器必须重新找出违例。任一不符即非零退出。只写 result.json。
"""
import itertools
import json
import sys

# ---- 协议 ----
R0 = {
    # 被退回的 r0：§1.2 第 1–3 条
    "teacher": [("try", "m0"), ("rel", "m0"), ("try", "teacher"), ("enter",), ("leave",), ("rel", "teacher")],
    "train_v9": [("try", "m0"), ("try", "teacher"), ("rel", "teacher"), ("enter",), ("leave",), ("rel", "m0")],
    "world_load": [("try", "teacher"), ("enter",), ("leave",), ("rel", "teacher")],
    "legacy_m0": [("try", "m0"), ("enter",), ("leave",), ("rel", "m0")],
}
R1 = {
    # 修订 r1：任何模式在整个占用区间持有 m0-worker.lock；World 模式整段持有，教师加载在其内部
    "teacher": [("try", "m0"), ("enter",), ("leave",), ("rel", "m0")],
    "train_v9": [("try", "m0"), ("enter",), ("leave",), ("rel", "m0")],
    "world": [("try", "m0"), ("enter",), ("leave",), ("rel", "m0")],
    "legacy_m0": [("try", "m0"), ("enter",), ("leave",), ("rel", "m0")],
}


def interleavings(a, b):
    n, m = len(a), len(b)
    for pos in itertools.combinations(range(n + m), n):
        seq, ia, ib, ps = [], 0, 0, set(pos)
        for k in range(n + m):
            if k in ps:
                seq.append(("A", a[ia])); ia += 1
            else:
                seq.append(("B", b[ib])); ib += 1
        yield seq


def run(seq):
    """执行一条交错；try 失败的进程立即退出（并释放它已持有的锁，等同进程结束时内核释放 fcntl 锁）。"""
    held = {}           # 锁 -> 持有进程
    alive = {"A": True, "B": True}
    inside = {"A": False, "B": False}
    mine = {"A": set(), "B": set()}
    for who, step in seq:
        if not alive[who]:
            continue
        op = step[0]
        if op == "try":
            lk = step[1]
            if lk in held:
                alive[who] = False
                for x in list(mine[who]):
                    held.pop(x, None)
                mine[who].clear()
                inside[who] = False
                continue
            held[lk] = who; mine[who].add(lk)
        elif op == "rel":
            lk = step[1]
            if held.get(lk) == who:
                held.pop(lk); mine[who].discard(lk)
        elif op == "enter":
            inside[who] = True
            if inside["A"] and inside["B"]:
                return True
        elif op == "leave":
            inside[who] = False
    return False


def check(protocol, pairs):
    out = {}
    for x, y in pairs:
        bad = None
        total = 0
        for seq in interleavings(protocol[x], protocol[y]):
            total += 1
            if run(seq):
                bad = [f"{w}:{'/'.join(s)}" for w, s in seq]
                break
        out[f"{x}|{y}"] = {"interleavings_checked": total, "violation": bad}
    return out


def main(result_path):
    pairs_r0 = [("teacher", "train_v9"), ("train_v9", "world_load"), ("teacher", "legacy_m0"), ("teacher", "world_load")]
    pairs_r1 = [(x, y) for x in R1 for y in R1]  # 含同类两进程
    r0 = check(R0, pairs_r0)
    r1 = check(R1, pairs_r1)
    sabotaged = dict(R1)
    sabotaged["teacher"] = [("try", "m0"), ("rel", "m0"), ("enter",), ("leave",)]  # 改坏：取锁后马上释放（r0 的错误）
    sab = check(sabotaged, [("teacher", "train_v9")])
    sabotaged2 = dict(R1)
    sabotaged2["world"] = [("enter",), ("try", "m0"), ("leave",), ("rel", "m0")]  # 改坏：先占用再取锁
    sab2 = check(sabotaged2, [("world", "train_v9")])
    fails = []
    if not any(v["violation"] for v in r0.values()):
        fails.append("r0 应能找出违例，但没找到（检查器失效）")
    for k, v in r1.items():
        if v["violation"]:
            fails.append(f"r1 违例：{k}")
    if not sab["teacher|train_v9"]["violation"]:
        fails.append("改坏 r1（取锁后立即释放）未被抓到")
    if not sab2["world|train_v9"]["violation"]:
        fails.append("改坏 r1（先占用再取锁）未被抓到")
    res = {"r0": r0, "r1": r1, "sabotage_release_early": sab, "sabotage_enter_before_lock": sab2, "failures": fails}
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({"r0_violations": [k for k, v in r0.items() if v["violation"]],
                      "r1_pairs": len(r1), "r1_violations": [k for k, v in r1.items() if v["violation"]],
                      "sabotage_caught": [bool(sab["teacher|train_v9"]["violation"]), bool(sab2["world|train_v9"]["violation"])],
                      "failures": fails}, ensure_ascii=False))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
