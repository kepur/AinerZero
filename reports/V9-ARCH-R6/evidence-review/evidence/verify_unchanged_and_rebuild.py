#!/usr/bin/env python3
"""
evidence/verify_unchanged_and_rebuild.py
Independent CPU verification of:
1. §13.1 unchanged sections between ARCHITECTURE_V9.md (r5) and ARCHITECTURE_V9.r6-candidate.md (r6 candidate).
2. Isolated build test of build_r6.py producing byte-identical candidate matching candidate_sha256.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

def get_section(text: str, heading: str, next_headings: list[str]) -> str:
    start_pos = text.find("\n" + heading)
    if start_pos == -1:
        if text.startswith(heading):
            start_pos = 0
        else:
            raise ValueError(f"Heading not found: {heading}")
    else:
        start_pos += 1  # skip leading newline
        
    end_pos = len(text)
    for nh in next_headings:
        pos = text.find("\n" + nh, start_pos)
        if pos != -1 and pos < end_pos:
            end_pos = pos
            
    return text[start_pos:end_pos].strip()

def check_unchanged_sections(r5_text: str, r6_text: str):
    print("--- 1. Checking Unchanged Sections per §13.1 ---")
    sections_to_check = [
        ("§1.1 三系统与三平面", "### 1.1 三系统与三平面（r5，F1）", ["## 2. 结构"]),
        ("§3 P0 接口", "## 3. P0 接口（ainerzero.V9.B2", ["## 4. 数学定义"]),
        ("§7.1 运行模式", "### 7.1 运行模式", ["### 7.2 教师 = 带噪声的传感器"]),
        ("§7.2 教师 = 带噪声的传感器", "### 7.2 教师 = 带噪声的传感器", ["### 7.3 教师清单"]),
        ("§7.3 教师清单", "### 7.3 教师清单", ["### 7.4 数据与监督"]),
        ("§7.4 数据与监督", "### 7.4 数据与监督", ["### 7.5 成本验收"]),
        ("§7.5 成本验收", "### 7.5 成本验收", ["### 7.6"]),
        ("§8.1 模块对应", "### 8.1 模块对应", ["### 8.2 接口对应"]),
        ("§8.2 接口对应", "### 8.2 接口对应", ["### 8.3"]),
        ("§8.4 成本模型", "### 8.4 成本模型", ["### 8.5 不做事项"]),
        ("§8.5 不做事项", "### 8.5 不做事项", ["### 8.6 学习侧的信息边界（r5，F2）"]),
        ("§8.6 学习侧的信息边界", "### 8.6 学习侧的信息边界（r5，F2）", ["## 9. r4 关闭表"]),
        ("§9 r4 关闭表", "## 9. r4 关闭表（回应 Codex 2026-10-16 平级审议）", ["## 10. v10 吸收与改正"]),
        ("§10 v10 吸收与改正", "## 10. v10 吸收与改正", ["## 11. r5 关闭表"]),
        ("§11 r5 关闭表", "## 11. r5 关闭表（回应 Codex 对 r4 的非作者审议 ainerzero.V9.A6）", ["## 12. r6 证据回写（截至 2026-11-17）"]),
    ]
    
    all_matched = True
    for label, heading, next_h in sections_to_check:
        sec_r5 = get_section(r5_text, heading, [next_h[0]] if next_h[0] != "## 12. r6 证据回写（截至 2026-11-17）" else ["\n--- END ---"])
        sec_r6 = get_section(r6_text, heading, next_h)
        if sec_r5 == sec_r6:
            print(f"  [MATCH] {label} ({len(sec_r5)} chars)")
        else:
            all_matched = False
            print(f"  [FAIL]  {label}: r5 {len(sec_r5)} chars != r6 {len(sec_r6)} chars")
            # find first mismatch
            for i, (c1, c2) in enumerate(zip(sec_r5, sec_r6)):
                if c1 != c2:
                    print(f"    Mismatch at offset {i}: r5[{c1!r}] != r6[{c2!r}]")
                    break

    # Check Equations 1-13 in §4
    print("\nChecking Equations 1-13 in §4:")
    sec_math_r5 = get_section(r5_text, "## 4. 数学定义", ["## 5. 研究顺序与门槛"])
    # In r6, 式 14-17 are appended
    sec_math_r6 = get_section(r6_text, "## 4. 数学定义", ["14. 规划代价（r6）"])
    if sec_math_r5 == sec_math_r6:
        print(f"  [MATCH] §4 约定段与式 1–13 完全一致 ({len(sec_math_r5)} chars)")
    else:
        all_matched = False
        print(f"  [FAIL]  §4 式 1-13 不一致")

    # Check §5 original content
    print("\nChecking §5 original content:")
    sec_s5_r5 = get_section(r5_text, "## 5. 研究顺序与门槛", ["## 6. 验收维度"])
    sec_s5_r6 = get_section(r6_text, "## 5. 研究顺序与门槛", ["- **r6 记录的执行缺口**"])
    if sec_s5_r5 == sec_s5_r6:
        print(f"  [MATCH] §5 原表、S1共同口径与常设对照前3条完全一致 ({len(sec_s5_r5)} chars)")
    else:
        all_matched = False
        print(f"  [FAIL]  §5 原文不一致")

    # Check §6 original content
    print("\nChecking §6 original rows:")
    sec_s6_r5 = get_section(r5_text, "## 6. 验收维度", ["## 7. 本机集成"])
    sec_s6_r6 = get_section(r6_text, "## 6. 验收维度", ["| 学习组件的净收益（r6）"])
    if sec_s6_r5 == sec_s6_r6:
        print(f"  [MATCH] §6 V10-E0–E6 原有各行完全一致 ({len(sec_s6_r5)} chars)")
    else:
        all_matched = False
        print(f"  [FAIL]  §6 原有行不一致")

    assert all_matched, "Unchanged sections verification failed!"
    print("\n[RESULT] PASS: All declared unchanged sections are bitwise / verbatim identical.")

def test_isolated_rebuild(repo_root):
    print("\n--- 2. Testing Isolated Rebuild of build_r6.py ---")
    candidate_path = repo_root / "reports/V9-ARCH-R6/ARCHITECTURE_V9.r6-candidate.md"
    expected_sha = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    print(f"Candidate file expected sha256: {expected_sha}")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # copy build directory and r5-base.md
        build_src = repo_root / "reports/V9-ARCH-R6/build"
        tmp_build = tmp_path / "build"
        shutil.copytree(build_src, tmp_build)
        
        # modify OUT path in a copied build_r6.py or run it in place
        # In build_r6.py: OUT = HERE.parent / "ARCHITECTURE_V9.r6-candidate.md"
        # So it writes to tmp_path / "ARCHITECTURE_V9.r6-candidate.md"
        cmd = [sys.executable, str(tmp_build / "build_r6.py")]
        res = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True)
        if res.returncode != 0:
            print("Build stdout:", res.stdout)
            print("Build stderr:", res.stderr)
            raise RuntimeError(f"Isolated build failed with code {res.returncode}")
            
        generated_file = tmp_path / "ARCHITECTURE_V9.r6-candidate.md"
        assert generated_file.exists(), "Generated candidate file does not exist"
        generated_sha = hashlib.sha256(generated_file.read_bytes()).hexdigest()
        print(f"Generated candidate sha256:     {generated_sha}")
        
        assert generated_sha == expected_sha, f"Generated sha {generated_sha} != expected {expected_sha}"
        
        # Compare byte for byte
        orig_bytes = candidate_path.read_bytes()
        gen_bytes = generated_file.read_bytes()
        assert orig_bytes == gen_bytes, "Generated file differs byte-for-byte from target candidate!"
        print("[RESULT] PASS: Isolated build produces byte-identical output matching candidate_sha256 exactly.")

def main():
    repo_root = Path(__file__).resolve().parents[4]
    r5_path = repo_root / "ARCHITECTURE_V9.md"
    r6_path = repo_root / "reports/V9-ARCH-R6/ARCHITECTURE_V9.r6-candidate.md"
    
    r5_text = r5_path.read_text(encoding="utf-8")
    r6_text = r6_path.read_text(encoding="utf-8")
    
    check_unchanged_sections(r5_text, r6_text)
    test_isolated_rebuild(repo_root)
    print("\n[ALL UNCHANGED SECTIONS & REBUILD VERIFICATIONS PASSED]")

if __name__ == "__main__":
    main()
