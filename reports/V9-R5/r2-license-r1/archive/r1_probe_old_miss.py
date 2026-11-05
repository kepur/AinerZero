#!/usr/bin/env python3
"""旧校验器（archive/validate_registry_r5_old.py，未改动）对 R9 四条 MIT→Apache 篡改的漏检证明。

以模块方式加载归档副本，仅调用其 validate_registry()；对 dino-wm / pldm / pushforward / slotssms
逐条做与按下将要新增的 M19–M22 相同的篡改（license.license 设为 Apache-2.0），
期望 4/4 全部【不变红】（绿色通过），从而证明：旧校验器对这四条缺专属 MIT 断言，靠其余检查抓不到。
任何一条变红即本探针失败（exit 1）。
"""
import copy
import json
import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent          # reports/V9-R5/r6-license-guard
OLD = HERE / "archive" / "validate_registry_r5_old.py"
ROOT = HERE.parents[2]                          # 仓库根 /Users/mac/AinerWorkFlow/AinerZero
REG = ROOT / "docs" / "research" / "adapter_registry.json"
MD = ROOT / "docs" / "research" / "ADAPTER_REGISTRY.md"

R9_TARGETS = [
    ("dino-wm", "DINO-WM"),
    ("pldm", "PLDM"),
    ("pushforward", "Pushforward"),
    ("slotssms", "SlotSSMs"),
]

spec = importlib.util.spec_from_file_location("v9r5_old_validator", OLD)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)

data = json.loads(REG.read_text(encoding="utf-8"))
miss = 0
idx = 0
with tempfile.TemporaryDirectory() as td:
    for eid, label in R9_TARGETS:
        idx += 1
        mutated = copy.deepcopy(data)
        hit = False
        for e in mutated["entries"]:
            if e["id"] == eid:
                e["license"] = {"license": "Apache-2.0", "source": "fake"}
                hit = True
                break
        assert hit, f"探针装配错误：找不到 {eid}"
        tj = Path(td) / f"probe-{eid}.json"
        tj.write_text(json.dumps(mutated, ensure_ascii=False), encoding="utf-8")
        try:
            old.validate_registry(tj, MD)
            miss += 1
            print(f"OLD-MISS[{idx}]: {eid}({label}) MIT→Apache 在旧校验器上【未变红】——漏检成立")
        except AssertionError as e:
            print(f"PROBE-FAIL[{idx}]: {eid}({label}) 旧校验器竟然变红（与预期矛盾）-> {e}")
            sys.exit(1)

print(f"=== 旧校验器漏检证明成立：4/{len(R9_TARGETS)} 条 MIT→Apache 篡改未被捕获 ===")
if miss != len(R9_TARGETS):
    sys.exit(1)
sys.exit(0)
