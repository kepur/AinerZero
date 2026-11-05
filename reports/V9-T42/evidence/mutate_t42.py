"""T42 反向变异自证脚本（针对 T42 的 4 项要求逐一注入反向变异，确认测试变红，然后还原）。
用法：仓库根目录 .venv/bin/python reports/V9-T42/evidence/mutate_t42.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "src/ainerzero/v9/teachers"
PY = str(REPO / ".venv/bin/python")

CTRL = "da3_controlled.py"
RUN = "da3_calibration_runner.py"
WORK = "da3_worker.py"
CMD = "benchmark_commands.py"

M = [
    (
        "T42-1 consume 前预检：移除 execute_guarded 中对 views 的预检拦截",
        CTRL,
        """    # V9.T42 (1): consume 前预检：
    # 对 worker_action=real_pipeline（即真实管线请求），在进入 RunStore 与 store.consume 之前校验视图数
    # 是否等于当前登记的标定视图口径（REGISTERED_CALIBRATION_VIEWS = 18）；不符直接拒绝、零扣账、零 worker 启动。
    if action == "real_pipeline" and spec.views != REGISTERED_CALIBRATION_VIEWS:
        raise BenchmarkRefusalError(
            f"Real DA3 pipeline execution requires views == {REGISTERED_CALIBRATION_VIEWS} "
            f"(current registered calibration views specification), but got views={spec.views}. "
            "Refused before reservation and consumption.",
            details={
                "requested_views": spec.views,
                "required_views": REGISTERED_CALIBRATION_VIEWS,
                "action": action,
            },
        )
""",
        "    # mutant: removed pre-consume views check\n",
        ["tests/test_teacher_da3_controlled.py", "-k", "test_pre_consume_calibration_views_check"],
    ),
    (
        "T42-2 补测 in_progress 覆盖拒绝：注入 T41-4 放行 status=in_progress 证据文件",
        RUN,
        """        if Path(out_json).exists():
            raise PreflightError(f"evidence file already exists: {out_json}; never overwrite delivered evidence")
""",
        """        if Path(out_json).exists():
            try:
                st = json.loads(Path(out_json).read_text()).get("status")
            except Exception:
                st = None
            if st != "in_progress":
                raise PreflightError(f"evidence file already exists: {out_json}; never overwrite delivered evidence")
""",
        ["tests/test_da3_calibration_runner.py", "-k", "test_preflight_rejects_existing_in_progress_evidence"],
    ),
    (
        "T42-3 substitute+release 直接选 mock：还原 CLI 在 test_substitute+coordinator_release 下选 real_pipeline",
        CMD,
        """            # V9.T42: CLI 在 test_substitute 下恒选 mock_run，即使带有 coordinator_release 亦同。
            worker_action = "mock_run" if test_substitute else ("real_pipeline" if coordinator_release else "mock_run")
""",
        """            worker_action = "mock_run" if test_substitute and not coordinator_release else "real_pipeline"
""",
        ["tests/test_teacher_da3_controlled.py", "-k", "test_cli_substitute_with_release_selects_mock_run"],
    ),
    (
        "T42-4 临时文件名唯一：还原 _write_atomic 为固定 .tmp 文件名",
        RUN,
        """    unique_suffix = f".tmp.{os.getpid()}.{uuid.uuid4().hex}"
    tmp = path.with_name(path.name + unique_suffix)
""",
        """    tmp = path.with_name(path.name + ".tmp")
""",
        ["tests/test_da3_calibration_runner.py", "-k", "test_write_atomic_uses_unique_tmp"],
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
    backup = live.read_text(encoding="utf-8")
    if backup.count(old) != 1:
        return name, f"!!! 变异未能应用 (匹配到 {backup.count(old)} 处目标文本) !!!"
    live.write_text(backup.replace(old, new, 1), encoding="utf-8")
    try:
        r = run_pytest(pytest_args)
        failed = re.findall(r"FAILED\s+\S+::(\S+)", r.stdout)
        if failed:
            return name, f"成功抓出变异 ({len(failed)} 条变红): " + ", ".join(x.split("::")[-1][:50] for x in failed[:4])
        if r.returncode != 0:
            return name, f"成功抓出变异 (非零退出 rc={r.returncode})"
        return name, f"!!! 未被测试抓出 (漏网) !!! rc=0 stdout={r.stdout[-200:]!r}"
    finally:
        live.write_text(backup, encoding="utf-8")


def main() -> int:
    lines = []
    print("=== T42 反向变异自证开始 ===")
    all_caught = True
    for item in M:
        name, msg = apply_and_test(*item)
        lines.append(f"{name}\n    -> {msg}")
        print(f"{name}\n    -> {msg}")
        if "成功抓出变异" not in msg:
            all_caught = False

    text = "\n".join(lines) + "\n"
    out_file = REPO / "reports/V9-T42/evidence/mutation-results.txt"
    out_file.write_text(text, encoding="utf-8")
    print(f"=== 自证完成，结果已写入 {out_file} (全部捕获: {all_caught}) ===")
    return 0 if all_caught else 1


if __name__ == "__main__":
    raise SystemExit(main())
