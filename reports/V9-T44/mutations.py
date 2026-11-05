#!/usr/bin/env python3
"""T44 自证：注入 T43 的 M-A / M-B / M-C 三个变异，确认对应新测试变红。

做法与 B12 的拆守卫坏控一致：把 `src/` 逐字节复制两份，先校验与仓内一致；控制组在未变异
副本上跑对应测试（必须绿）；然后按唯一锚点注入变异、跑测试（必须红）、按原字节还原并校验 SHA。

用法：`env -u PYTHONPATH .venv/bin/python reports/V9-T44/mutations.py`
输出写到 `reports/V9-T44/evidence/03-mutations.txt`。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
PYTEST = REPO / ".venv/bin/pytest"
OUT = REPO / "reports/V9-T44/evidence/03-mutations.txt"

MUTANTS = [
    dict(
        mid="M-A",
        origin="T43 F-1（门只在显式传 worker_action 时生效）",
        file="ainerzero/v9/teachers/da3_controlled.py",
        anchor='    if action == "real_pipeline" and spec.views != REGISTERED_CALIBRATION_VIEWS:\n',
        replacement='    if worker_action == "real_pipeline" and spec.views != REGISTERED_CALIBRATION_VIEWS:\n',
        node="tests/test_teacher_da3_controlled.py::test_derived_real_pipeline_path_also_hits_the_calibration_views_gate",
    ),
    dict(
        mid="M-B",
        origin="T43 F-3（CLI real 分支加 or allow_model_execution）",
        file="ainerzero/v9/teachers/benchmark_commands.py",
        anchor='                "real_pipeline" if explicit_coordinator_release else "mock_run"\n',
        replacement='                "real_pipeline" if (explicit_coordinator_release or allow_model_execution) else "mock_run"\n',
        node="tests/test_teacher_da3_controlled.py::test_cli_real_branch_honours_only_the_explicit_coordinator_release",
    ),
    dict(
        mid="M-C",
        origin="T43 F-2（临时文件写到系统 /tmp）",
        file="ainerzero/v9/teachers/da3_calibration_runner.py",
        anchor="    tmp = path.with_name(path.name + unique_suffix)\n",
        replacement='    tmp = Path("/tmp") / (path.name + unique_suffix)\n',
        node="tests/test_da3_calibration_runner.py::test_write_atomic_keeps_the_temp_file_in_the_target_directory",
    ),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_pytest(node: str, src_root: Path) -> tuple[int, str]:
    env = dict(os.environ)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(key, None)
    env["NO_PROXY"] = "127.0.0.1,localhost,::1"
    env["PYTHONPATH"] = str(src_root)
    completed = subprocess.run(
        [str(PYTEST), node, "-q", "-p", "no:cacheprovider", "--no-header"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return completed.returncode, completed.stdout + completed.stderr


def tail(text: str, lines: int = 3) -> str:
    rows = [row for row in text.strip().splitlines() if row.strip()]
    return " | ".join(rows[-lines:])


def main() -> int:
    log: list[str] = []
    log.append("# T44 变异自证（M-A / M-B / M-C，来源：reports/V9-T43/报告.md §0）")
    log.append(f"# 仓库：{REPO}")
    log.append("")

    with tempfile.TemporaryDirectory(prefix="t44-mut-") as tmp:
        tmp_root = Path(tmp)
        pristine = tmp_root / "pristine"
        work = tmp_root / "work"
        shutil.copytree(SRC, pristine)
        shutil.copytree(SRC, work)

        for path in sorted(SRC.rglob("*.py")):
            relative = path.relative_to(SRC)
            assert sha256(path) == sha256(pristine / relative), f"copy drift: {relative}"
        log.append("## 0. 副本基线")
        log.append(f"src/*.py 与仓内逐字节一致（{len(list(SRC.rglob('*.py')))} 个文件）")

        env = dict(os.environ)
        env["PYTHONPATH"] = str(work)
        probe = subprocess.run(
            [os.sys.executable, "-c", "import ainerzero.v9.teachers.da3_controlled as m; print(m.__file__)"],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
        )
        resolved = probe.stdout.strip()
        assert resolved.startswith(str(work)), f"import did not resolve to the copy: {resolved}"
        log.append(f"副本优先于 venv 安装：{resolved}")
        log.append("")

        log.append("## 1. 控制组（未变异 -> 新测试必须绿）")
        controls = {}
        for mutant in MUTANTS:
            code, output = run_pytest(mutant["node"], work)
            controls[mutant["mid"]] = code
            log.append(f"- {'PASS' if code == 0 else 'FAIL'}  {mutant['mid']}  {mutant['node'].split('::')[-1]}")
        log.append("")
        assert all(code == 0 for code in controls.values()), "control run is not green"

        log.append("## 2. 注入变异（必须变红）")
        failures: list[str] = []
        for mutant in MUTANTS:
            target = work / mutant["file"]
            original = target.read_bytes()
            before = sha256(target)
            text = original.decode("utf-8")
            occurrences = text.count(mutant["anchor"])
            if occurrences != 1:
                failures.append(f"{mutant['mid']}: anchor found {occurrences} times")
                log.append(f"- ERROR {mutant['mid']} anchor x{occurrences}")
                continue
            target.write_text(text.replace(mutant["anchor"], mutant["replacement"]), encoding="utf-8")
            mutated_sha = sha256(target)
            code, output = run_pytest(mutant["node"], work)
            target.write_bytes(original)
            restored = sha256(target)
            assert restored == before, f"{mutant['mid']}: restore failed"
            verdict = "RED (expected)" if code != 0 else "STILL GREEN (mutation not caught!)"
            if code == 0:
                failures.append(f"{mutant['mid']}: test stayed green")
            log.append(
                f"- {mutant['mid']}  {mutant['origin']}\n"
                f"    文件 {mutant['file']}  SHA {before[:12]} -> {mutated_sha[:12]} -> {restored[:12]}\n"
                f"    靶子 {mutant['node'].split('::')[-1]}\n"
                f"    结果 {verdict}  ({tail(output, 2)})"
            )

        log.append("")
        log.append("## 3. 还原校验")
        for path in sorted(SRC.rglob("*.py")):
            relative = path.relative_to(SRC)
            assert sha256(path) == sha256(work / relative) == sha256(pristine / relative), f"drift: {relative}"
        log.append("仓内源码、副本、还原后副本三方 SHA 全部一致（未污染工作树）")
        log.append("")
        log.append(f"## 结论：{len(MUTANTS) - len(failures)}/{len(MUTANTS)} 个变异被抓（3/3 才合格）")
        if failures:
            log.append("失败项：")
            log.extend(f"- {item}" for item in failures)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
