"""T41 自有变异（T40 mutate_t40.py 未覆盖）。短暂替换 live 源文件→跑针对性测试→立刻还原。
用法：仓库根 `.venv/bin/python reports/V9-T41/evidence/mutate_t41_own.py`
零模型；不碰 runs.db / m0-worker.lock。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "src/ainerzero/v9/teachers"
PY = str(REPO / ".venv/bin/python")
CTRL, RUN, WORK = "da3_controlled.py", "da3_calibration_runner.py", "da3_worker.py"

M = [
    (
        "T41-1 _write_atomic 只写 .tmp 不做 os.replace",
        RUN,
        "    os.replace(tmp, path)\n",
        "    return  # mutant: leave only .tmp\n",
        ["tests/test_da3_calibration_runner.py", "-k", "hard_abort or atomic_evidence"],
    ),
    (
        "T41-2 去掉 test_substitute 对显式 real_pipeline 的拒绝",
        CTRL,
        '    if test_substitute and worker_action == "real_pipeline":\n'
        '        raise BenchmarkRefusalError("test substitute mode must never reach the real pipeline worker")\n',
        "    # mutant: allow explicit real_pipeline under test_substitute\n",
        ["tests/test_teacher_da3_controlled.py", "-k", "test_substitute_never_selects"],
    ),
    (
        "T41-3 worker refused_no_calibration 仍 rc=0（吞掉拒绝）",
        WORK,
        '            sys.stderr.write(f"Real DA3 execution refused: no calibration was run for views={views} (runner requires views == 18).\\n")\n'
        "            return 4\n",
        '            sys.stderr.write(f"Real DA3 execution refused: no calibration was run for views={views} (runner requires views == 18).\\n")\n'
        "            return 0  # mutant\n",
        ["tests/test_da3_supervision.py", "-k", "lazy_worker_real_pipeline"],
    ),
    (
        "T41-4 preflight 放行已存在的 in_progress 证据（可覆盖崩溃残留）",
        RUN,
        '        if Path(out_json).exists():\n'
        '            raise PreflightError(f"evidence file already exists: {out_json}; never overwrite delivered evidence")\n',
        '        if Path(out_json).exists():\n'
        '            try:\n'
        '                st = __import__("json").loads(Path(out_json).read_text()).get("status")\n'
        '            except Exception:\n'
        '                st = None\n'
        '            if st != "in_progress":\n'
        '                raise PreflightError(f"evidence file already exists: {out_json}; never overwrite delivered evidence")\n',
        ["tests/test_da3_calibration_runner.py", "-k", "preflight_rejects_existing"],
    ),
]


def run_pytest(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, "-m", "pytest", *args, "-q", "--no-header", "-p", "no:cacheprovider", "--tb=line"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )


def apply_and_test(name, fname, old, new, pytest_args):
    live = SRC / fname
    backup = live.read_text()
    if backup.count(old) != 1:
        return name, f"!!! 变异未能应用(出现{backup.count(old)}次)"
    live.write_text(backup.replace(old, new, 1))
    try:
        r = run_pytest(pytest_args)
        failed = re.findall(r"FAILED\s+\S+::(\S+)", r.stdout)
        if failed:
            return name, f"{len(failed)} 条红: " + ", ".join(x.split("::")[-1][:50] for x in failed[:4])
        if r.returncode != 0:
            return name, f"非零退出未解析 FAILED: rc={r.returncode} tail={r.stdout[-300:]!r} err={r.stderr[-200:]!r}"
        return name, f"!!! 没有任何测试抓到 !!! rc=0 out={r.stdout[-300:]!r}"
    finally:
        live.write_text(backup)


def custom_probe_t41_4_gap() -> str:
    """证明：现有 suite 写 '{}' 抓不到『放行 in_progress』；自定义探针能抓到。"""
    live = SRC / RUN
    backup = live.read_text()
    old = (
        '        if Path(out_json).exists():\n'
        '            raise PreflightError(f"evidence file already exists: {out_json}; never overwrite delivered evidence")\n'
    )
    new = (
        '        if Path(out_json).exists():\n'
        '            try:\n'
        '                st = __import__("json").loads(Path(out_json).read_text()).get("status")\n'
        '            except Exception:\n'
        '                st = None\n'
        '            if st != "in_progress":\n'
        '                raise PreflightError(f"evidence file already exists: {out_json}; never overwrite delivered evidence")\n'
    )
    assert backup.count(old) == 1
    live.write_text(backup.replace(old, new, 1))
    try:
        code = f"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, {str(REPO/'src')!r})
from ainerzero.v9.teachers import da3_calibration_runner as R
REPO = Path({str(REPO)!r})
plan = R.load_plan(REPO/'reports/V9-T28/r2/proposal.json')
class F:
    conditions_on_intrinsics_only = False
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    preds = td/'preds'; preds.mkdir()
    out = td/'ev.json'
    out.write_text(json.dumps({{"status":"in_progress"}}))
    try:
        R.preflight(plan, F(), preds, out)
        print("GAP_CONFIRMED: in_progress overwrite allowed")
    except R.PreflightError as e:
        print("BLOCKED", e)
"""
        r = subprocess.run([PY, "-c", code], cwd=REPO, capture_output=True, text=True)
        return r.stdout.strip() + ((" ERR:" + r.stderr[-200:]) if r.returncode and not r.stdout.strip() else "")
    finally:
        live.write_text(backup)


def main() -> int:
    lines = []
    for item in M:
        name, msg = apply_and_test(*item)
        lines.append(f"{name}\n    -> {msg}")
        print(f"{name}\n    -> {msg}")
    gap = custom_probe_t41_4_gap()
    lines.append(f"T41-4 custom probe (in_progress file)\n    -> {gap}")
    print(f"T41-4 custom probe (in_progress file)\n    -> {gap}")
    text = "\n".join(lines) + "\n"
    (REPO / "reports/V9-T41/evidence/own-mutation-results.txt").write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
