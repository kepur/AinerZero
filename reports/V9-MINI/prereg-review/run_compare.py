#!/usr/bin/env python3
"""隔离副本比较脚本：验证 c92c0abd 与 114d74be 的行为不变性
分别在 /tmp/v9mini_compare/c92c 和 /tmp/v9mini_compare/114d 运行:
  --quick --world m2 --seed 0
比较两边每个 arm 的 success / steps 是否逐回合严格相同。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

VENV_PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"
BASE_DIR = Path("/tmp/v9mini_compare")
C92C_DIR = BASE_DIR / "c92c"
D114_DIR = BASE_DIR / "114d"
OUT_C92C = BASE_DIR / "out_c92c"
OUT_114D = BASE_DIR / "out_114d"

def run_isolated(work_dir: Path, out_dir: Path):
    cmd = [
        VENV_PY, "-m", "ainerzero.v9.mini.run",
        "--quick", "--world", "m2", "--seed", "0",
        "--out", str(out_dir)
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(work_dir / "src")
    
    print(f"[{work_dir.name}] Starting run in {work_dir} ...", flush=True)
    while True:
        res = subprocess.run(cmd, cwd=str(work_dir), env=env, capture_output=True, text=True)
        if res.returncode == 0:
            print(f"[{work_dir.name}] Successfully completed!", flush=True)
            break
        elif res.returncode == 75:
            print(f"[{work_dir.name}] Lock busy (75), waiting 15s ...", flush=True)
            time.sleep(15)
        else:
            print(f"[{work_dir.name}] Failed with code {res.returncode}:\n{res.stderr}", flush=True)
            sys.exit(res.returncode)

def compare_episodes():
    with open(OUT_C92C / "episodes.json", "r", encoding="utf-8") as f:
        data_c = json.load(f)
    with open(OUT_114D / "episodes.json", "r", encoding="utf-8") as f:
        data_d = json.load(f)
        
    arms = sorted(data_c.keys())
    print(f"\nComparing {len(arms)} arms across all episodes...")
    all_match = True
    report_lines = []
    
    for arm in arms:
        eps_c = data_c[arm]
        eps_d = data_d[arm]
        assert len(eps_c) == len(eps_d), f"Length mismatch for arm {arm}: {len(eps_c)} vs {len(eps_d)}"
        
        n_eps = len(eps_c)
        mismatches = []
        for i in range(n_eps):
            sc, tc = eps_c[i]["success"], eps_c[i]["steps"]
            sd, td = eps_d[i]["success"], eps_d[i]["steps"]
            if sc != sd or tc != td:
                mismatches.append((i, sc, sd, tc, td))
                
        if mismatches:
            all_match = False
            msg = f"Arm {arm}: MISMATCH in {len(mismatches)}/{n_eps} episodes!"
            print("  [FAIL] " + msg)
            report_lines.append(msg)
        else:
            msg = f"Arm {arm:16s}: MATCH ({n_eps} episodes, 100% identical success & steps)"
            print("  [OK]   " + msg)
            report_lines.append(msg)
            
    summary = {
        "all_match": all_match,
        "n_arms": len(arms),
        "arms_detail": report_lines
    }
    
    out_file = Path(__file__).resolve().parent / "invariance_comparison.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nComparison result written to {out_file}")
    return all_match

def main():
    # 1. 运行 c92c
    run_isolated(C92C_DIR, OUT_C92C)
    # 2. 运行 114d
    run_isolated(D114_DIR, OUT_114D)
    # 3. 比对
    ok = compare_episodes()
    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
