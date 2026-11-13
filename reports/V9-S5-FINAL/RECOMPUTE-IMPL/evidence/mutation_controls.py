#!/usr/bin/env python3
"""坏对照：git archive 副本里改 recompute 源码，再跑正式测试。

正式测试失败才算拦住。本脚本不在 pytest.raises 里自写必然失败的断言。
工作副本放在 /tmp，不碰实盘仓库。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

LIVE = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PY = str(LIVE / ".venv/bin/python")
S = "reports/V9-S5-PHASE1/recompute_s5p1_final.py"
T = "tests/v9/experiments/test_s5_recompute.py"

GA_OLD = "    decision = M.ga_decision(a0_curves, a4_curves, cap=cap)\n"
GA_NEW = (
    "    _d = M.ga_decision(a0_curves, a4_curves, cap=cap)\n"
    "    decision = {**_d,"
    ' "median_a0": _d["stair"]["median_a0"],'
    ' "median_a4": _d["stair"]["median_a4"],'
    ' "a0_steps": _d["stair"]["a0_steps"],'
    ' "a4_steps": _d["stair"]["a4_steps"],'
    ' "a0_censored": _d["stair"]["a0_censored"],'
    ' "a4_censored": _d["stair"]["a4_censored"],'
    ' "ratio": _d["stair"]["ratio"],'
    ' "passed": _d["stair"]["passed"]}\n'
)

MUTS: list[tuple[str, tuple[str, str] | None]] = [
    ("baseline", None),
    (
        "M1-seed-order",
        (
            "SEED_MEAN = mean_over_readouts_then_distills\n",
            "SEED_MEAN = mean_over_distills_then_readouts\n",
        ),
    ),
    (
        "M2-gt1-drop-ci-lower",
        (
            'passed = bool(point + 1e-12 >= prereg["gt1_effect"] and boot["ci_lower"] > 0.0)',
            'passed = bool(point + 1e-12 >= prereg["gt1_effect"])',
        ),
    ),
    (
        "M3-gt3-ci-lower",
        (
            'passed = bool(boot["ci_upper"] <= margin + 1e-12)',
            'passed = bool(boot["ci_lower"] <= margin + 1e-12)',
        ),
    ),
    (
        "M4-gr-skip-keep",
        (
            'keep_ok = bool(keep_rate <= prereg["gr_keep_max"] + _eps)',
            "keep_ok = True",
        ),
    ),
    (
        "M5-gr-skip-ap",
        (
            'ap_ok = bool(boot["ci_upper"] <= prereg["gr_ap_drop_ci_max"] + _eps)',
            "ap_ok = True",
        ),
    ),
    (
        "M6-gt1-effect-zero",
        (
            'passed = bool(point + 1e-12 >= prereg["gt1_effect"] and boot["ci_lower"] > 0.0)',
            'passed = bool(point + 1e-12 >= 0.0 and boot["ci_lower"] > 0.0)',
        ),
    ),
    (
        "M7-bonferroni-95",
        (
            "GT_LEVEL = 1.0 - 0.05 / BONFERRONI_M  # ≈ 0.983333...\n",
            "GT_LEVEL = 0.95  # mutated away from Bonferroni\n",
        ),
    ),
    ("M8-ga-no-interpolation", (GA_OLD, GA_NEW)),
]


def main() -> int:
    base = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path("/tmp/p246-rc-mut")
    if base == LIVE or LIVE in base.parents:
        raise SystemExit(f"refuse to mutate inside the live repo: {base}")
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    failed = False
    for name, edit in MUTS:
        dest = base / name
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        archive = subprocess.run(
            ["git", "-C", str(LIVE), "archive", "HEAD", "src", "tests/conftest.py", "pyproject.toml"],
            check=True,
            capture_output=True,
        )
        subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True)
        (dest / "reports/V9-S5-PHASE1").mkdir(parents=True, exist_ok=True)
        (dest / "tests/v9/experiments").mkdir(parents=True, exist_ok=True)
        shutil.copy2(LIVE / S, dest / S)
        shutil.copy2(LIVE / T, dest / T)
        for init in ("tests/__init__.py", "tests/v9/__init__.py", "tests/v9/experiments/__init__.py"):
            if (LIVE / init).exists():
                shutil.copy2(LIVE / init, dest / init)
        if edit:
            target = dest / S
            text = target.read_text(encoding="utf-8")
            if text.count(edit[0]) != 1:
                print(f"{name:28s} EDIT_NOT_UNIQUE count={text.count(edit[0])}", flush=True)
                failed = True
                continue
            target.write_text(text.replace(edit[0], edit[1], 1), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        proc = subprocess.run(
            [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", T],
            cwd=dest,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        tail = ""
        if proc.stdout.strip():
            tail = proc.stdout.strip().splitlines()[-1]
        elif proc.stderr.strip():
            tail = proc.stderr.strip().splitlines()[-1]
        if name == "baseline":
            verdict = "BASELINE" if proc.returncode == 0 else "BASELINE_FAILED"
            failed = failed or proc.returncode != 0
        else:
            verdict = "KILLED" if proc.returncode else "SURVIVED"
            failed = failed or proc.returncode == 0
        print(f"{name:28s} rc={proc.returncode} {verdict} | {tail}", flush=True)
    print("RESULT " + ("FAIL" if failed else "PASS"), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
