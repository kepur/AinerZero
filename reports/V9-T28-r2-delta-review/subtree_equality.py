#!/usr/bin/env python3
"""T46 独立复核：卡面点名要求"逐字节相等"的那些子树，逐个做规范 JSON 全等断言。

对每个子树：
  - 若两侧都缺 → 视为相等（并标 absent_both，便于人读）
  - 若一侧缺 → 不等
  - 否则 canonical json（sort_keys, 无空格）逐字节比较

另外做一次"白名单"检查：把 changed 叶子集合按顶层键分组，断言除 4 个允许的顶层键外，
其它任何顶层键下面 0 个变化叶子（比逐个点名更强：能抓到没被点名的地方被动了）。

只读。
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from own_diff import flatten, diff_leaves, resolve, MISSING  # noqa: E402

ALLOWED_TOP_KEYS = {"amendment", "budget", "numerical_parity", "open_items"}

# 卡面"特别核对"点名项 + r2 相对 r1 声称未动的口径
NAMED_SUBTREES = [
    # 数值对拍（卡面点名）
    "/numerical_parity/cpu_float32",
    "/numerical_parity/mps_float16",
    "/numerical_parity/fields",
    "/numerical_parity/rule",
    "/numerical_parity/require_same_shapes_and_finite",
    "/numerical_parity/reference",
    # 负对照全部（含 required_red 常数）
    "/negative_controls",
    "/negative_controls/score",
    "/negative_controls/required_red",
    "/negative_controls/frames",
    "/negative_controls/boundary_rejection",
    "/negative_controls/unrelated_error",
    "/negative_controls/real_forward_controls",
    "/negative_controls/removed_controls",
    "/negative_controls/same_clean_profile",
    "/negative_controls/frame_order_adverse_meaning",
    # 数学口径
    "/split",
    "/alignment",
    "/estimation",
    "/failure_policy",
    "/residual_vector",
    # 预算里的墙钟 / RSS / 单模型常驻 / 重试
    "/budget/single_run_wall_seconds_max",
    "/budget/reserve_before_model_import_seconds",
    "/budget/rss_bytes_max",
    "/budget/max_resident_models",
    "/budget/retry_allowed",
    "/budget/include_loads_postprocess_and_all_controls_in_wall",
    "/budget/reserve_before_model_import_views",
    # 输入身份
    "/input_manifest_sha256",
    "/lead_protocol_observed_sha256",
    "/generator_sha256",
    "/schema",
    "/task_id",
    "/status",
    "/execution_permitted",
]


def canon(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def get(obj, path):
    try:
        return resolve(obj, path)
    except (KeyError, IndexError):
        return MISSING


def main():
    a_path, b_path = sys.argv[1], sys.argv[2]
    A = json.load(open(a_path))
    B = json.load(open(b_path))
    print("=" * 78)
    print(f"子树逐字节相等断言: A={a_path}")
    print(f"                    B={b_path}")
    print("=" * 78)

    fails = 0
    for p in NAMED_SUBTREES:
        va, vb = get(A, p), get(B, p)
        if va is MISSING and vb is MISSING:
            print(f"  ABSENT_BOTH  {p}")
            continue
        if va is MISSING or vb is MISSING:
            print(f"  DIFF         {p}   (one side absent: A={va is MISSING} B={vb is MISSING})")
            fails += 1
            continue
        same = canon(va) == canon(vb)
        n = len(flatten(va, p))
        print(f"  {'EQUAL      ' if same else 'DIFF       '} {p}   ({n} leaves)")
        if not same:
            fails += 1
            print(f"      A={canon(va)[:300]}")
            print(f"      B={canon(vb)[:300]}")

    # 白名单：除 4 个允许顶层键外，不许有变化叶子
    changed, _, _ = diff_leaves(A, B)
    offenders = {}
    for leaf in changed:
        top = leaf.split("/")[1].split("[")[0]
        if top not in ALLOWED_TOP_KEYS:
            offenders.setdefault(top, []).append(leaf)
    print("\n--- 白名单：允许变化的顶层键 = %s ---" % sorted(ALLOWED_TOP_KEYS))
    print(f"白名单外的变化顶层键: {sorted(offenders)}")
    for top, leaves in offenders.items():
        for leaf in leaves:
            print(f"  OFFENDER {leaf}")
    fails += len(offenders)

    print("\n" + "=" * 78)
    print(f"FAILS = {fails}  => {'PASS' if fails == 0 else 'FAIL'}")
    print("=" * 78)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
