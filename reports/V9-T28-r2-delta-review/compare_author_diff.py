#!/usr/bin/env python3
"""T46 独立复核：把作者 diff_r1_r2.json 的 32 条路径与我自己算出的叶子级差异逐条对照。

三项检查（缺一即 reject）:
  C1 覆盖：我的每个变化叶子都落在作者某条路径下 —— 否则 = 作者漏列（unlisted differences）
  C2 不虚列：作者的每条路径下至少有一个叶子真的变了 —— 否则 = 作者虚列
  C3 值一致：作者记录的 r1/r2 值与该路径在真实文件里的值逐字节相等 —— 否则 = 作者描述失真

只读。不导入作者的脚本。
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from own_diff import flatten, diff_leaves, resolve, MISSING  # noqa: E402


def leaves_under(path, all_paths):
    return {p for p in all_paths
            if p == path or p.startswith(path + "/") or p.startswith(path + "[")}


def canon(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def main():
    r1_path, r2_path, author_diff_path = sys.argv[1], sys.argv[2], sys.argv[3]
    r1 = json.load(open(r1_path))
    r2 = json.load(open(r2_path))
    author = json.load(open(author_diff_path))

    changed, f1, f2 = diff_leaves(r1, r2)
    all_paths = set(f1) | set(f2)
    author_paths = [c["path"] for c in author["changed_paths"]]

    print("=" * 78)
    print("作者 diff 对照（作者声明 %d 条路径，我算出 %d 个变化叶子）"
          % (len(author_paths), len(changed)))
    print("=" * 78)

    # 作者声明的 r1/r2 SHA 是否等于实测
    import hashlib
    for name, p, claimed in (("r1", r1_path, author.get("r1_sha256")),
                             ("r2", r2_path, author.get("r2_sha256"))):
        actual = hashlib.sha256(open(p, "rb").read()).hexdigest()
        print(f"[SHA] {name}: 声明={claimed}  实测={actual}  一致={claimed == actual}")

    # ---- C1 覆盖 ----
    print("\n--- C1 覆盖：我的变化叶子是否全被作者列出 ---")
    uncovered = []
    for leaf in changed:
        if not any(leaf == ap or leaf.startswith(ap + "/") or leaf.startswith(ap + "[")
                   for ap in author_paths):
            uncovered.append(leaf)
    print(f"未覆盖的变化叶子: {len(uncovered)}")
    for u in uncovered:
        print("  MISSING:", u, "| r1=", canon(changed[u][0])[:120],
              "| r2=", canon(changed[u][1])[:120])

    # ---- C2 不虚列 ----
    print("\n--- C2 不虚列：作者每条路径是否真的变了 ---")
    empty = []
    for ap in author_paths:
        sub = leaves_under(ap, all_paths)
        if not (sub & set(changed)):
            empty.append(ap)
        print(f"  {ap}: 子树叶子={len(sub)} 其中变化={len(sub & set(changed))}"
              + ("   <== 虚列" if not (sub & set(changed)) else ""))
    print(f"虚列路径: {len(empty)} {empty}")

    # ---- C3 值一致 ----
    print("\n--- C3 值一致：作者记录的 r1/r2 值 vs 真实文件 ---")
    bad = []
    for c in author["changed_paths"]:
        ap = c["path"]
        try:
            real1 = resolve(r1, ap)
        except (KeyError, IndexError):
            real1 = MISSING
        try:
            real2 = resolve(r2, ap)
        except (KeyError, IndexError):
            real2 = MISSING
        claimed1 = c.get("r1", MISSING)
        claimed2 = c.get("r2", MISSING)
        ok = canon(real1) == canon(claimed1) and canon(real2) == canon(claimed2)
        if not ok:
            bad.append((ap, real1, claimed1, real2, claimed2))
            print(f"  MISMATCH {ap}")
            print(f"     r1 真实={canon(real1)[:200]}")
            print(f"     r1 声明={canon(claimed1)[:200]}")
            print(f"     r2 真实={canon(real2)[:200]}")
            print(f"     r2 声明={canon(claimed2)[:200]}")
        else:
            print(f"  OK {ap}")
    print(f"值不一致的路径: {len(bad)}")

    print("\n" + "=" * 78)
    verdict = (len(uncovered) == 0 and len(empty) == 0 and len(bad) == 0)
    print(f"结论: 覆盖={len(uncovered)==0} 不虚列={len(empty)==0} 值一致={len(bad)==0}"
          f"  => 作者 diff {'与实测完全一致' if verdict else '有出入'}")
    print("=" * 78)
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
