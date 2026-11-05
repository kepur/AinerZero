#!/usr/bin/env python3
"""T46 独立差异复核：自写脚本，不导入作者的 build_proposal_r2.py / build_docs_r2.py / check_r2.py。

用法:
  python3 own_diff.py <A.json> <B.json> [--label A=.. B=..]

输出:
  1) 叶子级差异（含 list 索引，完全显式）
  2) 最大"整棵子树全变"节点集合（与作者 diff 的粒度可比）
  3) 叶子级差异按作者粒度聚合成覆盖集合

只读，不写仓库任何文件（结果打到 stdout，由调用方重定向）。
"""
import json
import sys
from collections import OrderedDict

MISSING = "<absent>"


def flatten(obj, prefix="", out=None):
    """把 JSON 摊平成 {叶子路径: 值}。空 dict/list 本身算一个叶子。"""
    if out is None:
        out = OrderedDict()
    if isinstance(obj, dict):
        if not obj:
            out[prefix or "/"] = {}
        for k, v in obj.items():
            flatten(v, f"{prefix}/{k}", out)
    elif isinstance(obj, list):
        if not obj:
            out[prefix or "/"] = []
        for i, v in enumerate(obj):
            flatten(v, f"{prefix}[{i}]", out)
    else:
        out[prefix or "/"] = obj
    return out


def leaf_paths_of_subtree(obj, prefix):
    return set(flatten(obj, prefix).keys())


def children_of(path, obj):
    """返回 path 节点下的直接子路径（含 list 索引形式）。"""
    node = obj
    if path == "/":
        node = obj
    else:
        # 解析 path
        node = resolve(obj, path)
    if isinstance(node, dict):
        return [f"{path}/{k}" if path != "/" else f"/{k}" for k in node]
    if isinstance(node, list):
        return [f"{path}[{i}]" for i in range(len(node))]
    return []


def resolve(obj, path):
    if path in ("", "/"):
        return obj
    node = obj
    i = 0
    n = len(path)
    while i < n:
        if path[i] == "/":
            j = i + 1
            while j < n and path[j] not in "/[":
                j += 1
            node = node[path[i + 1:j]]
            i = j
        elif path[i] == "[":
            j = path.index("]", i)
            node = node[int(path[i + 1:j])]
            i = j + 1
        else:
            raise ValueError(path)
    return node


def diff_leaves(a, b):
    fa, fb = flatten(a), flatten(b)
    keys = list(OrderedDict.fromkeys(list(fa) + list(fb)))
    changed = OrderedDict()
    for k in keys:
        va, vb = fa.get(k, MISSING), fb.get(k, MISSING)
        if va != vb or (k not in fa) != (k not in fb):
            changed[k] = (va, vb)
    return changed, fa, fb


def maximal_full_subtrees(a, b, changed_leaf_set):
    """找出所有"其下每个叶子都变了"的最大节点 —— 与作者 diff 粒度可比。"""
    all_paths = set()
    for src in (a, b):
        all_paths |= set(flatten(src).keys())

    # 收集候选前缀节点：所有叶子的所有祖先
    candidates = set()
    for p in all_paths:
        # 生成祖先：/a/b[0]/c -> /a, /a/b, /a/b[0]
        cur = ""
        i = 0
        while i < len(p):
            ch = p[i]
            if ch == "/":
                j = i + 1
                while j < len(p) and p[j] not in "/[":
                    j += 1
                cur = p[:j]
                candidates.add(cur)
                i = j
            elif ch == "[":
                j = p.index("]", i)
                cur = p[:j + 1]
                candidates.add(cur)
                i = j + 1
            else:
                i += 1

    full = []
    for c in candidates:
        sub = {p for p in all_paths if p == c or p.startswith(c + "/") or p.startswith(c + "[")}
        if sub and sub <= changed_leaf_set:
            full.append(c)

    # 只保留极大者
    maximal = []
    for c in sorted(full, key=len):
        if not any(c == m or c.startswith(m + "/") or c.startswith(m + "[") for m in maximal):
            maximal.append(c)
    return maximal


def coverage_ok(author_path, changed_leaf_set, all_paths):
    """作者的一条路径是否"整块变了"（其下所有叶子都变）。"""
    sub = {p for p in all_paths if p == author_path or p.startswith(author_path + "/") or p.startswith(author_path + "[")}
    return bool(sub) and sub <= changed_leaf_set, sub


def main():
    pa, pb = sys.argv[1], sys.argv[2]
    label = "A vs B"
    if "--label" in sys.argv:
        label = sys.argv[sys.argv.index("--label") + 1]

    A = json.load(open(pa))
    B = json.load(open(pb))

    changed, fa, fb = diff_leaves(A, B)
    all_paths = set(fa) | set(fb)

    print("=" * 78)
    print(f"{label}")
    print(f"A = {pa}")
    print(f"B = {pb}")
    print("=" * 78)
    print(f"\n叶子总数: A={len(fa)}  B={len(fb)}  变化叶子={len(changed)}")
    print(f"变化的顶层键: {sorted({p.split('/')[1] for p in changed})}")

    print("\n--- 1) 叶子级差异（完全显式）---")
    for k, (va, vb) in changed.items():
        print(f"{k}")
        print(f"    A: {json.dumps(va, ensure_ascii=False)[:400]}")
        print(f"    B: {json.dumps(vb, ensure_ascii=False)[:400]}")

    maximal = maximal_full_subtrees(A, B, set(changed))
    print("\n--- 2) 最大整块变化节点（作者 diff 粒度）---")
    print(f"count={len(maximal)}")
    for m in maximal:
        print(m)

    print("\n--- 3) 变化叶子所属的顶层键分布 ---")
    from collections import Counter
    c = Counter(p.split("/")[1] for p in changed)
    for k, v in sorted(c.items()):
        print(f"  /{k}: {v}")


if __name__ == "__main__":
    main()
