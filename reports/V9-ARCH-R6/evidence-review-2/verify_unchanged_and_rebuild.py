#!/usr/bin/env python3
"""独立验证脚本（纯 CPU，只读）。

1. 逐字节比对候选稿 §13.1 声明未改章节与 r5 原文。
2. 在隔离目录副本重跑 build/build_r6.py，核对 sha256 逐字节一致。
"""
from __future__ import annotations
import hashlib
import re
import shutil
import tempfile
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
R5_FILE = ROOT / "ARCHITECTURE_V9.md"
CAND_FILE = ROOT / "reports" / "V9-ARCH-R6" / "ARCHITECTURE_V9.r6-candidate.md"
BUILD_SCRIPT = ROOT / "reports" / "V9-ARCH-R6" / "build" / "build_r6.py"

r5_text = R5_FILE.read_text(encoding="utf-8")
cand_text = CAND_FILE.read_text(encoding="utf-8")

r5_sha = hashlib.sha256(r5_text.encode("utf-8")).hexdigest()
cand_sha = hashlib.sha256(cand_text.encode("utf-8")).hexdigest()

print(f"r5   sha256: {r5_sha}")
print(f"cand sha256: {cand_sha}")

def extract_section(text: str, start_hdr: str, stop_hdrs: list[str]) -> str:
    lines = text.split("\n")
    start = -1
    end = len(lines)
    for i, line in enumerate(lines):
        if line.strip().startswith(start_hdr):
            start = i
            break
    if start == -1:
        raise ValueError(f"Header not found: {start_hdr}")
    for i in range(start + 1, len(lines)):
        if any(lines[i].strip().startswith(sh) for sh in stop_hdrs):
            end = i
            break
    return "\n".join(lines[start:end]).strip()

sections_to_check = [
    ("### 1.1 三系统与三平面", ["### 1.2", "## 2."]),
    ("## 3. P0 接口", ["## 4."]),
    ("### 7.1 运行模式", ["### 7.2", "## 8."]),
    ("### 7.2 教师 = 带噪声的传感器", ["### 7.3", "## 8."]),
    ("### 7.3 教师清单", ["### 7.4", "## 8."]),
    ("### 7.4 数据与监督", ["### 7.5", "## 8."]),
    ("### 7.5 成本验收", ["### 7.6", "## 8."]),
    ("### 8.1 模块对应", ["### 8.2", "## 9."]),
    ("### 8.2 接口对应", ["### 8.3", "## 9."]),
    ("### 8.4 成本模型", ["### 8.5", "## 9."]),
    ("### 8.5 不做事项", ["### 8.6", "## 9."]),
    ("### 8.6 学习侧的信息边界", ["## 9."]),
    ("## 9. r4 关闭表", ["## 10."]),
    ("## 10. v10 吸收与改正", ["## 11."]),
    ("## 11. r5 关闭表", ["## 12."]),
]

all_passed = True
print("\n--- 逐章节比对 ---")
for hdr, stops in sections_to_check:
    sec_r5 = extract_section(r5_text, hdr, stops)
    sec_cand = extract_section(cand_text, hdr, stops)
    is_same = (sec_r5 == sec_cand)
    status = "相同" if is_same else "不同"
    print(f"[{status}] {hdr}")
    if not is_same:
        all_passed = False

# §4 式 1–13 检查
sec4_r5 = extract_section(r5_text, "## 4. 数学定义", ["## 5."])
sec4_cand = extract_section(cand_text, "## 4. 数学定义", ["14. 规划代价（r6）"])
same_f1_13 = (sec4_r5 == sec4_cand)
print(f"[{'相同' if same_f1_13 else '不同'}] ## 4. 数学定义（式 1–13 与前言约定）")
if not same_f1_13:
    all_passed = False

# §5 原表与前言
sec5_r5 = extract_section(r5_text, "## 5. 研究顺序与门槛", ["## 6."])
sec5_cand = extract_section(cand_text, "## 5. 研究顺序与门槛", ["- **r6 记录的执行缺口**"])
same_sec5 = (sec5_r5 == sec5_cand)
print(f"[{'相同' if same_sec5 else '不同'}] ## 5. 原表与共同口径")
if not same_sec5:
    all_passed = False

# 隔离目录重跑 build_r6.py
print("\n--- 隔离副本重跑 build/build_r6.py ---")
with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    # 构造目录结构
    shutil.copytree(ROOT / "reports" / "V9-ARCH-R6" / "build", tmp_path / "reports" / "V9-ARCH-R6" / "build")
    # 运行生成脚本
    import subprocess
    run_res = subprocess.run(
        ["python3", str(tmp_path / "reports" / "V9-ARCH-R6" / "build" / "build_r6.py")],
        cwd=str(tmp_path),
        capture_output=True,
        text=True
    )
    built_file = tmp_path / "reports" / "V9-ARCH-R6" / "ARCHITECTURE_V9.r6-candidate.md"
    if built_file.is_file():
        built_sha = hashlib.sha256(built_file.read_bytes()).hexdigest()
        print(f"重跑生成产物 sha256: {built_sha}")
        if built_sha == cand_sha:
            print("重跑产物与提交里的候选稿逐字节相同：完全匹配！")
        else:
            print("重跑产物 sha256 不符！")
            all_passed = False
    else:
        print("重跑失败，未生成产物！")
        print("stderr:", run_res.stderr)
        all_passed = False

print(f"\n全部未改章节与重跑检查：{'通过' if all_passed else '失败'}")
exit(0 if all_passed else 1)
