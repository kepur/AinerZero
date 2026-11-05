#!/usr/bin/env python3
"""T46 独立复核：核对 numerical_parity.retired_stages[*].evidence 的文件/行号/SHA。

每条 evidence 项形如 {file, line, sha256}。三项都要独立验：
  E1 文件存在且 sha256 与声明一致（文件没被改写、声明没抄错）
  E2 该行号确实落在文件内
  E3 该行内容与"退役理由"所述代码位置一致（按每份文件预先规定的 marker 断言，
     而不是只信行号 —— 行号对但内容不对，等价于证据造假）

marker 表是本复核人自己从源码里读出后写死的：cam_dec.py 的 fc_t(feat.float())、
pipeline.py 的 ExplicitPrecisionDA3 类定义。
"""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")

# 我自己从源码核出的期望 marker（不是作者提供的）
EXPECTED_MARKERS = {
    "envs/teachers/t6/Depth-Anything-3/src/depth_anything_3/model/cam_dec.py": "self.fc_t(feat.float())",
    "envs/teachers/t6/pipeline.py": "class ExplicitPrecisionDA3",
}


def main() -> int:
    prop_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "reports/V9-T28/r2/proposal.json"
    prop = json.loads(Path(prop_path).read_text(encoding="utf-8"))
    retired = prop["numerical_parity"].get("retired_stages", [])
    print("=" * 78)
    print(f"retired_stages.evidence 独立核验: {prop_path}")
    print("=" * 78)
    if not retired:
        print("没有 retired_stages —— 与本卡对象不符")
        return 1

    fails = 0
    for rec in retired:
        print(f"\n[stage] {rec.get('stage')}  (tolerance_key={rec.get('tolerance_key')})")
        for name, ev in rec.get("evidence", {}).items():
            if not isinstance(ev, dict) or "file" not in ev:
                print(f"  {name}: 不是文件型证据 -> {str(ev)[:120]}")
                continue
            f = REPO / ev["file"]
            if not f.is_file():
                print(f"  {name}: 文件不存在 {ev['file']}")
                fails += 1
                continue
            real_sha = hashlib.sha256(f.read_bytes()).hexdigest()
            ok_sha = real_sha == ev["sha256"]
            lines = f.read_text(encoding="utf-8").splitlines()
            line_no = int(ev["line"])
            ok_range = 1 <= line_no <= len(lines)
            text = lines[line_no - 1].strip() if ok_range else "<out of range>"
            marker = EXPECTED_MARKERS.get(ev["file"])
            ok_marker = (marker is not None and marker in text) if marker else None
            print(f"  {name}: {ev['file']}")
            print(f"      line {line_no}/{len(lines)}  内容: {text[:100]}")
            print(f"      sha256 声明={ev['sha256'][:16]}… 实测={real_sha[:16]}… 一致={ok_sha}")
            print(f"      行号在范围内={ok_range}  与期望 marker({marker!r}) 相符={ok_marker}")
            if not (ok_sha and ok_range and ok_marker is not False):
                fails += 1

    # 交叉一致性：退役阶段的容差键必须真的存在于容差表里，且声明为"未使用"
    print("\n[交叉一致性]")
    np_ = prop["numerical_parity"]
    for rec in retired:
        tk = rec.get("tolerance_key")
        exists = isinstance(np_.get(tk), dict) and "atol" in np_[tk]
        print(f"  tolerance_key={tk} 在容差表里={exists} 声明未使用={rec.get('tolerance_kept_unchanged_and_unused')}")
        if not exists:
            fails += 1
    # 退役理由里点到的 stage 名不得出现在 budget 里
    stage_names = {s["stage"] for m in prop["budget"]["models"] for s in m["stages"]}
    for rec in retired:
        back = rec["stage"] in stage_names
        print(f"  retired stage {rec['stage']!r} 仍在 budget 里={back}")
        if back:
            fails += 1

    print("\n" + "=" * 78)
    print(f"FAILS={fails} => {'PASS' if fails == 0 else 'FAIL'}")
    print("=" * 78)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
