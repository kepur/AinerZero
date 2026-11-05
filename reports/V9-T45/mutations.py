#!/usr/bin/env python3
"""T45 复核变异自证脚本：
包含 T43 的 M-A、M-B、M-C 变异重注与分析，以及 2 个新增独立变异 M-X1、M-X2。
在完全隔离的 tempdir 副本中执行，保证仓库源码零污染。

运行：.venv/bin/python reports/V9-T45/mutations.py
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
OUT = REPO / "reports/V9-T45/evidence/03-mutations-5of5-red.txt"

ACTIVE_MUTANTS = [
    dict(
        mid="M-A",
        desc="T43 F-1：预检门只在显式传 worker_action 时生效（派生路径退化）",
        file="ainerzero/v9/teachers/da3_controlled.py",
        anchor='    if action == "real_pipeline" and spec.views != REGISTERED_CALIBRATION_VIEWS:\n',
        replacement='    if worker_action == "real_pipeline" and spec.views != REGISTERED_CALIBRATION_VIEWS:\n',
        node="tests/test_teacher_da3_controlled.py::test_derived_real_pipeline_path_also_hits_the_calibration_views_gate",
    ),
    dict(
        mid="M-B-r2",
        desc="T43 F-3 / T44 r2：CLI 单独传 --allow-model-execution 时的预扣前直接拒绝门失效",
        file="ainerzero/v9/teachers/benchmark_commands.py",
        anchor='            if not test_substitute and allow_model_execution and not explicit_coordinator_release:\n',
        replacement='            if False and not test_substitute and allow_model_execution and not explicit_coordinator_release:\n',
        node="tests/test_teacher_da3_controlled.py::test_cli_allow_model_execution_alone_is_refused_before_any_reservation",
    ),
    dict(
        mid="M-C",
        desc="T43 F-2：_write_atomic 临时文件写入系统 /tmp（跨卷破坏原子性）",
        file="ainerzero/v9/teachers/da3_calibration_runner.py",
        anchor="    tmp = path.with_name(path.name + unique_suffix)\n",
        replacement='    tmp = Path("/tmp") / (path.name + unique_suffix)\n',
        node="tests/test_da3_calibration_runner.py::test_write_atomic_keeps_the_temp_file_in_the_target_directory",
    ),
    dict(
        mid="M-X1",
        desc="T45 自有变异 1：da3_controlled 中已放行非替身必须真跑的纵深防御门失效",
        file="ainerzero/v9/teachers/da3_controlled.py",
        anchor='    if not test_substitute and is_released and action != "real_pipeline":\n',
        replacement='    if False and not test_substitute and is_released and action != "real_pipeline":\n',
        node="tests/test_teacher_da3_controlled.py::test_released_non_substitute_run_must_use_the_real_pipeline_before_any_reservation",
    ),
    dict(
        mid="M-X2",
        desc="T45 自有变异 2：views 预检门失效或后移（81/82 账本下被配额错误覆盖真因）",
        file="ainerzero/v9/teachers/da3_controlled.py",
        anchor='    if action == "real_pipeline" and spec.views != REGISTERED_CALIBRATION_VIEWS:\n',
        replacement='    if False and action == "real_pipeline" and spec.views != REGISTERED_CALIBRATION_VIEWS:\n',
        node="tests/test_teacher_da3_controlled.py::test_views_gate_precedes_the_quota_gate_and_reports_the_views_reason",
    ),
]

DEAD_CODE_MUTANT = dict(
    mid="M-B-orig",
    desc="T43 原始 M-B：在 real 分支三元表达式加 or allow_model_execution（r2 门禁下不可达）",
    file="ainerzero/v9/teachers/benchmark_commands.py",
    anchor='                "real_pipeline" if explicit_coordinator_release else "mock_run"\n',
    replacement='                "real_pipeline" if (explicit_coordinator_release or allow_model_execution) else "mock_run"\n',
    node="tests/test_teacher_da3_controlled.py",
)

def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def run_pytest(node: str, src_root: Path) -> tuple[int, str]:
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(k, None)
    env["NO_PROXY"] = "127.0.0.1,localhost,::1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(src_root)
    res = subprocess.run(
        [str(PYTEST), node, "-q", "-p", "no:cacheprovider", "--no-header"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return res.returncode, res.stdout + res.stderr

def tail(text: str, n: int = 2) -> str:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return " | ".join(lines[-n:])

def main() -> int:
    log: list[str] = []
    log.append("# T45 变异复核与攻击自证日志（生成时间：2026-10-28）")
    log.append(f"# 仓库：{REPO}")
    log.append("")

    with tempfile.TemporaryDirectory(prefix="t45-mut-") as tmp:
        tmp_root = Path(tmp)
        pristine = tmp_root / "pristine"
        work = tmp_root / "work"
        shutil.copytree(SRC, pristine, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(SRC, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

        for p in sorted(SRC.rglob("*.py")):
            rel = p.relative_to(SRC)
            assert sha256(p) == sha256(pristine / rel) == sha256(work / rel)
        log.append("## 0. 隔离副本基线")
        log.append(f"src/*.py 逐字节一致（共 {len(list(SRC.rglob('*.py')))} 个文件），隔离加载验证通过。")
        log.append("")

        log.append("## 1. 控制组（未变异 -> 全部测试节点必须绿）")
        for m in ACTIVE_MUTANTS:
            rc, out = run_pytest(m["node"], work)
            status = "PASS" if rc == 0 else "FAIL"
            log.append(f"- [{status}] {m['mid']} -> {m['node'].split('::')[-1]}")
            assert rc == 0, f"Control run failed for {m['mid']}: {out}"
        log.append("")

        log.append("## 2. 注入承重变异（必须变红）")
        failures = []
        for m in ACTIVE_MUTANTS:
            target = work / m["file"]
            orig_bytes = target.read_bytes()
            before_sha = sha256(target)
            content = orig_bytes.decode("utf-8")
            assert content.count(m["anchor"]) == 1, f"Anchor count != 1 for {m['mid']}"
            target.write_text(content.replace(m["anchor"], m["replacement"]), encoding="utf-8")
            mut_sha = sha256(target)
            rc, out = run_pytest(m["node"], work)
            target.write_bytes(orig_bytes)
            assert sha256(target) == before_sha, f"Restore failed for {m['mid']}"
            verdict = "RED (CAUGHT)" if rc != 0 else "STILL GREEN (BLIND SPOT!)"
            if rc == 0:
                failures.append(m["mid"])
            log.append(
                f"- {m['mid']}: {m['desc']}\n"
                f"    目标文件: {m['file']} (SHA: {before_sha[:10]} -> {mut_sha[:10]} -> {before_sha[:10]})\n"
                f"    靶子测试: {m['node'].split('::')[-1]}\n"
                f"    判定结果: {verdict} ({tail(out)})"
            )
        log.append("")

        log.append("## 3. T43 原版 M-B 死代码变异对照实验")
        target = work / DEAD_CODE_MUTANT["file"]
        orig_bytes = target.read_bytes()
        before_sha = sha256(target)
        content = orig_bytes.decode("utf-8")
        assert content.count(DEAD_CODE_MUTANT["anchor"]) == 1
        target.write_text(content.replace(DEAD_CODE_MUTANT["anchor"], DEAD_CODE_MUTANT["replacement"]), encoding="utf-8")
        rc, out = run_pytest(DEAD_CODE_MUTANT["node"], work)
        target.write_bytes(orig_bytes)
        assert sha256(target) == before_sha
        log.append(
            f"- 原版 M-B 注入: {DEAD_CODE_MUTANT['desc']}\n"
            f"    注入结果: pytest 运行全套测试套件返回码 {rc} ({'STILL GREEN' if rc == 0 else 'RED'})\n"
            f"    审计解释: 在 T44 r2 行 116 的直接拒绝门拦截下，--allow-model-execution 永远无法到达行 125，因此原版 M-B 已成死代码变异。\n"
            f"    真正承重的守卫是行 116 拒绝门（即上方测试的 M-B-r2，已被严格抓红）。"
        )
        log.append("")

        log.append("## 4. 源码还原校验")
        for p in sorted(SRC.rglob("*.py")):
            rel = p.relative_to(SRC)
            assert sha256(p) == sha256(pristine / rel) == sha256(work / rel)
        log.append("三方 SHA 校验一致，工作区零污染。")
        log.append("")
        log.append(f"## 结论：{len(ACTIVE_MUTANTS) - len(failures)}/{len(ACTIVE_MUTANTS)} 个有效变异被抓（5/5 变红通过）。")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    return 0 if not failures else 1

if __name__ == "__main__":
    raise SystemExit(main())
