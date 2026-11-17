#!/usr/bin/env python3
"""
verify_v2_unchanged_and_rebuild.py
Item 2 verification for Architecture r6 candidate v2.
1. Checks that sections declared unchanged in candidate v2 §13.1 match ARCHITECTURE_V9.md (r5) verbatim.
2. Checks §4, §5, §6 base sections match r5 verbatim.
3. Performs an isolated rebuild by running build/build_r6.py in a temp directory and compares sha256.
Pure CPU, zero MLX import.
"""
import sys
import os
import hashlib
import subprocess
import tempfile
import shutil

assert "mlx" not in sys.modules, "MLX must not be imported!"

REPO_ROOT = "/Users/mac/AinerWorkFlow/AinerZero"
R5_PATH = os.path.join(REPO_ROOT, "ARCHITECTURE_V9.md")
CANDIDATE_PATH = os.path.join(REPO_ROOT, "reports/V9-ARCH-R6/ARCHITECTURE_V9.r6-candidate.md")
BUILD_SCRIPT = os.path.join(REPO_ROOT, "reports/V9-ARCH-R6/build/build_r6.py")

EXPECTED_R5_SHA = "0f54a96ace5b9c6fad2f3a16f3e6417a2f521fe131a13400263a0f5d9920f2a4"
EXPECTED_V2_SHA = "567de2349cc2918c79528425e474bd90c48462715bd96e28906a87fbe4fe7746"

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

print(f"[1/4] Verifying file SHA256 hashes...")
r5_sha = sha256_file(R5_PATH)
v2_sha = sha256_file(CANDIDATE_PATH)
print(f"  R5 actual: {r5_sha}")
assert r5_sha == EXPECTED_R5_SHA, f"R5 hash mismatch: {r5_sha} != {EXPECTED_R5_SHA}"
print(f"  Candidate v2 actual: {v2_sha}")
assert v2_sha == EXPECTED_V2_SHA, f"Candidate v2 hash mismatch: {v2_sha} != {EXPECTED_V2_SHA}"

with open(R5_PATH, "r", encoding="utf-8") as f:
    r5_text = f.read()

with open(CANDIDATE_PATH, "r", encoding="utf-8") as f:
    v2_text = f.read()

def extract_section(text, start_heading, end_heading=None):
    pos = text.find(start_heading)
    if pos == -1:
        raise ValueError(f"Start heading not found: {start_heading}")
    if end_heading:
        pos_end = text.find(end_heading, pos + len(start_heading))
        if pos_end == -1:
            raise ValueError(f"End heading not found: {end_heading} after {start_heading}")
        return text[pos:pos_end]
    else:
        return text[pos:]

print("\n[2/4] Verifying declared unchanged sections verbatim against r5...")
sections_to_check = [
    ("### 1.1 三系统与三平面", "### 1.1 三系统与三平面", "\n## 2."),
    ("## 3. P0 接口", "## 3. P0 接口", "\n## 4."),
    ("### 7.1 运行模式", "### 7.1 运行模式", "\n### 7.2"),
    ("### 7.2 教师 = 带噪声的传感器", "### 7.2 教师 = 带噪声的传感器", "\n### 7.3"),
    ("### 7.3 教师清单", "### 7.3 教师清单", "\n### 7.4"),
    ("### 7.4 数据与监督", "### 7.4 数据与监督", "\n### 7.5"),
    ("### 7.5 成本验收", "### 7.5 成本验收", "\n### 7.6"),
    ("### 8.1 模块对应", "### 8.1 模块对应", "\n### 8.2"),
    ("### 8.2 接口对应", "### 8.2 接口对应", "\n### 8.3"),
    ("### 8.4 成本模型", "### 8.4 成本模型", "\n### 8.5"),
    ("### 8.5 不做事项", "### 8.5 不做事项", "\n### 8.6"),
    ("### 8.6 学习侧的信息边界", "### 8.6 学习侧的信息边界", "\n## 9."),
    ("## 9. r4 关闭表", "## 9. r4 关闭表", "\n## 10."),
    ("## 10. v10 吸收与改正", "## 10. v10 吸收与改正", "\n## 11."),
]

mismatches = 0
for name, start_h, end_h in sections_to_check:
    sec_r5 = extract_section(r5_text, start_h, end_h)
    sec_v2 = extract_section(v2_text, start_h, end_h)
    if sec_r5 == sec_v2:
        print(f"  [OK] {name} (length {len(sec_r5)} chars) matches verbatim")
    else:
        print(f"  [MISMATCH] {name}")
        mismatches += 1

# Section 11: r5 ends at EOF, v2 ends before ## 12.
sec11_r5 = extract_section(r5_text, "## 11. r5 关闭表", None).strip()
sec11_v2 = extract_section(v2_text, "## 11. r5 关闭表", "\n## 12.").strip()
if sec11_r5 == sec11_v2:
    print(f"  [OK] ## 11. r5 关闭表 (length {len(sec11_r5)} chars) matches verbatim")
else:
    print(f"  [MISMATCH] ## 11. r5 关闭表")
    mismatches += 1

print("\n[3/4] Verifying section prefixes for §4, §5, §6...")
# Section 4 formulas 1-13
sec4_r5 = extract_section(r5_text, "## 4. 数学定义", "\n## 5.").rstrip()
sec4_v2 = extract_section(v2_text, "## 4. 数学定义", "\n14. 规划代价（r6）").rstrip()
if sec4_r5 == sec4_v2:
    print(f"  [OK] ## 4. 式 1-13 matches r5 verbatim (length {len(sec4_r5)})")
else:
    print(f"  [MISMATCH] ## 4. 式 1-13")
    mismatches += 1

# Section 5 r5 base text
sec5_r5 = extract_section(r5_text, "## 5. 研究顺序与门槛", "\n## 6.").rstrip()
sec5_v2 = extract_section(v2_text, "## 5. 研究顺序与门槛", "\n- **r6 记录的执行缺口**").rstrip()
if sec5_r5 == sec5_v2:
    print(f"  [OK] ## 5. r5 base table and text matches r5 verbatim (length {len(sec5_r5)})")
else:
    print(f"  [MISMATCH] ## 5. r5 base")
    mismatches += 1

# Section 6 existing rows
sec6_r5 = extract_section(r5_text, "## 6. 验收维度（RFC §10 中与世界脑相关的部分）", "\n## 7.").rstrip()
sec6_v2 = extract_section(v2_text, "## 6. 验收维度（RFC §10 中与世界脑相关的部分）", "\n| 学习组件的净收益（r6）").rstrip()
if sec6_r5 == sec6_v2:
    print(f"  [OK] ## 6. r5 base table matches r5 verbatim (length {len(sec6_r5)})")
else:
    print(f"  [MISMATCH] ## 6. r5 base")
    mismatches += 1

assert mismatches == 0, f"{mismatches} sections mismatched!"

print("\n[4/4] Performing isolated build in temporary directory...")
with tempfile.TemporaryDirectory() as tmpdir:
    build_dir = os.path.join(tmpdir, "build")
    os.makedirs(build_dir, exist_ok=True)
    
    # Copy build_r6.py and r5-base.md
    shutil.copyfile(BUILD_SCRIPT, os.path.join(build_dir, "build_r6.py"))
    shutil.copyfile(os.path.join(REPO_ROOT, "reports/V9-ARCH-R6/build/r5-base.md"), os.path.join(build_dir, "r5-base.md"))
    
    # Run build_r6.py from the build dir
    cmd = [sys.executable, os.path.join(build_dir, "build_r6.py")]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=build_dir)
    print("  Build stdout:", res.stdout.strip())
    if res.returncode != 0:
        print("  Build stderr:", res.stderr.strip())
        raise RuntimeError("Build script failed in isolated environment!")
    
    out_candidate = os.path.join(tmpdir, "ARCHITECTURE_V9.r6-candidate.md")
    rebuilt_sha = sha256_file(out_candidate)
    print(f"  Rebuilt sha256: {rebuilt_sha}")
    print(f"  Target  sha256: {EXPECTED_V2_SHA}")
    assert rebuilt_sha == EXPECTED_V2_SHA, f"Rebuilt file hash {rebuilt_sha} does not match {EXPECTED_V2_SHA}"
    print("  [OK] Rebuilt candidate matches target candidate v2 byte-for-byte!")

print("\nAll Item 2 checks for v2 passed successfully!")
