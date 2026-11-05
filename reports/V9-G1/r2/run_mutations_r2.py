#!/usr/bin/env python3
"""r2 故意改坏必须变红的对照（F1/F2 源码 + F3 登记消费门）。

每个 mutation 在 /tmp 沙盒里改坏一份源码副本，用同一份 r2 测试文件跑 pytest：
- 未改坏的对照（control）必须绿（exit 0）；
- 每处修复被改坏后必须真实变红（pytest exit != 0）；
- 登记消费门被改坏（文档/代码哈希不符）必须真实 exit 1。
真实源码不被修改；沙盒是临时目录，路径写进结果 JSON 与报告。
退出码 0 = 对照绿且全部 mutation 红；1 = 有对照没绿或有 mutation 没红。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
GEOMETRY = ROOT / "src" / "ainerzero" / "v9" / "geometry"
R2_TEST = ROOT / "tests" / "v9" / "geometry" / "test_geometry_r2.py"
PYTHON = ROOT / ".venv-ainerzero" / "bin" / "python"
EVIDENCE = HERE / "evidence"
SANDBOX = Path("/tmp") / f"ainerzero-v9g5-r2-{time.strftime('%Y%m%dT%H%M%S')}"

SOURCE_FILES = ("belief.py", "gravity.py", "pose_graph.py", "lie.py", "canonical.py",
                "__init__.py", "README.md")

# name -> (相对 geometry 的文件, 原串, 改坏后的串)
SOURCE_MUTATIONS = {
    "m1_psd_guard_zero_tolerance": (
        "belief.py",
        "        if smallest < -psd_tolerance(p):",
        "        if smallest < 0:"),
    "m2_psd_guard_absolute_tolerance": (
        "belief.py",
        "        if smallest < -psd_tolerance(p):",
        "        if smallest < -1e-12:"),
    "m3_psd_guard_loose_relative_tolerance": (
        "belief.py",
        "PSD_RELATIVE_TOL = 1e-12",
        "PSD_RELATIVE_TOL = 1e-3"),
    "m4_pose_graph_no_eigenvalue_clamp": (
        "pose_graph.py",
        "            eig = np.where(negative, 0.0, eig)",
        "            eig = eig  # mutated: no clamp"),
    "m5_gravity_absolute_norm_guard": (
        "gravity.py",
        "        if sin_theta < HORIZONTAL_SIN_TOL:",
        "        if np.linalg.norm(x) < 1e-12:"),
    "m6_gravity_unnormalized_guard": (
        "gravity.py",
        "        sin_theta = float(np.linalg.norm(x)) / h_norm",
        "        sin_theta = float(np.linalg.norm(x))"),
}

REGISTRATION = HERE / "input_registration_r2.json"
VERIFY = HERE / "verify_registration_r2.py"


def clean_sandbox() -> Path:
    root = SANDBOX / "src"
    if root.exists():
        shutil.rmtree(root)
    target = root / "ainerzero" / "v9" / "geometry"
    target.mkdir(parents=True)
    shutil.copy2(ROOT / "src" / "ainerzero" / "__init__.py", root / "ainerzero" / "__init__.py")
    for name in SOURCE_FILES:
        shutil.copy2(GEOMETRY / name, target / name)
    return root


def run(command: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=180)


def main() -> None:
    if not SANDBOX.parent.is_dir():
        raise SystemExit("临时目录不可用")
    SANDBOX.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(SANDBOX / "src"),
               PYTHONDONTWRITEBYTECODE="1")
    results: dict = {"task": "ainerzero.V9.G5", "sandbox": str(SANDBOX),
                     "control": [], "source_mutations": [], "registration_mutations": []}
    ok = True

    # 0) 沙盒本身必须是“未改坏”的绿对照，并确认 import 解析到沙盒副本。
    clean_sandbox()
    probe = run([str(PYTHON), "-c",
                 "import ainerzero.v9.geometry.belief as b; print(b.__file__)"], env)
    imported = probe.stdout.strip().splitlines()[-1] if probe.stdout.strip() else ""
    valid = probe.returncode == 0 and imported.startswith(str(SANDBOX))
    results["control"].append({"name": "control_import_sandbox", "exit_code": probe.returncode,
                               "imported_from": imported, "passed": valid})
    print(f"[{'GREEN' if valid else 'HARNESS BROKEN'}] control_import_sandbox: {imported}")
    ok = ok and valid
    if not valid:
        print(probe.stderr[-800:], file=sys.stderr)

    def run_pytest(tag: str) -> dict:
        proc = run([str(PYTHON), "-m", "pytest", str(R2_TEST), "-q", "-p", "no:cacheprovider"], env)
        log = (proc.stdout or "") + (proc.stderr or "")
        (EVIDENCE / f"{tag}.log").write_text(f"$ pytest {R2_TEST}\n{log}", encoding="utf-8")
        broken_harness = any(token in log for token in
                             ("ModuleNotFoundError", "ImportError", "No module named", "INTERNALERROR"))
        failed_lines = [line for line in log.splitlines() if line.startswith("FAILED ")]
        entry = {"name": tag, "command": [str(PYTHON), "-m", "pytest", str(R2_TEST), "-q"],
                 "exit_code": proc.returncode, "failed_tests": len(failed_lines),
                 "broken_harness": broken_harness, "log": f"evidence/{tag}.log"}
        return entry

    control = run_pytest("control_unmutated_r2_tests")
    control["passed"] = control["exit_code"] == 0 and not control["broken_harness"]
    results["control"].append(control)
    print(f"[{'GREEN' if control['passed'] else 'RED(control broken!)'}] control_unmutated_r2_tests: "
          f"exit={control['exit_code']} failed_tests={control['failed_tests']}")
    ok = ok and control["passed"]

    # 1) 每处修复的故意改坏必须变红
    for name, (filename, old, new) in SOURCE_MUTATIONS.items():
        clean_sandbox()
        path = SANDBOX / "src" / "ainerzero" / "v9" / "geometry" / filename
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise SystemExit(f"mutation {name}: 原串在 {filename} 中出现 {text.count(old)} 次（期望 1）")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        entry = run_pytest(name)
        entry["file"] = f"src/ainerzero/v9/geometry/{filename}"
        entry["mutation"] = f"{old.strip()}  ->  {new.strip()}"
        entry["red"] = entry["exit_code"] != 0 and not entry["broken_harness"] and entry["failed_tests"] > 0
        results["source_mutations"].append(entry)
        print(f"[{'RED(expected)' if entry['red'] else 'GREEN(!! MUTATION SURVIVED)'}] {name}: "
              f"exit={entry['exit_code']} failed_tests={entry['failed_tests']}")
        ok = ok and entry["red"]

    # 2) 登记消费门：对真实登记必须绿；改坏文档/代码哈希必须红
    verify_log = EVIDENCE / "control_verify_registration.log"
    proc = run([str(PYTHON), "-B", str(VERIFY)], env)
    verify_log.write_text("$ verify_registration_r2.py\n" + (proc.stdout or "") + (proc.stderr or ""),
                          encoding="utf-8")
    verify_control = {"name": "control_verify_registration", "exit_code": proc.returncode,
                      "passed": proc.returncode == 0, "log": f"evidence/{verify_log.name}"}
    results["control"].append(verify_control)
    print(f"[{'GREEN' if verify_control['passed'] else 'RED(control broken!)'}] "
          f"control_verify_registration: exit={proc.returncode}")
    ok = ok and verify_control["passed"]

    real_registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
    tamper_targets = {
        "m7_registration_document_hash_tamper": (
            lambda reg: reg["documents"][0].__setitem__("new_sha256", "f" * 64),
            "文档输入哈希被改却仍通过消费门"),
        "m8_registration_code_hash_tamper": (
            lambda reg: reg["code_inputs"]["inputs"][
                "src/ainerzero/environments/gridlab2d.py"].__setitem__("sha256", "0" * 64),
            "代码输入哈希被改却仍通过消费门"),
    }
    for name, (tamper, description) in tamper_targets.items():
        tampered = json.loads(json.dumps(real_registration))
        tamper(tampered)
        tampered_path = SANDBOX / f"{name}.json"
        tampered_path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
        proc = run([str(PYTHON), "-B", str(VERIFY), "--registration", str(tampered_path)], env)
        log = (proc.stdout or "") + (proc.stderr or "")
        (EVIDENCE / f"{name}.log").write_text(
            f"$ verify_registration_r2.py --registration {tampered_path}\n{log}", encoding="utf-8")
        entry = {"name": name, "description": description, "exit_code": proc.returncode,
                 "contains_fail": "FAIL" in log,
                 "red": proc.returncode != 0 and "FAIL" in log, "log": f"evidence/{name}.log"}
        results["registration_mutations"].append(entry)
        print(f"[{'RED(expected)' if entry['red'] else 'GREEN(!! GATE LEAK)'}] {name}: exit={proc.returncode}")
        ok = ok and entry["red"]

    results["all_controls_green"] = all(item["passed"] for item in results["control"])
    results["all_source_mutations_red"] = all(item["red"] for item in results["source_mutations"])
    results["all_registration_mutations_red"] = all(item["red"] for item in results["registration_mutations"])
    results["ok"] = ok
    (EVIDENCE / "mutation-results-r2.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("---")
    print(json.dumps({k: results[k] for k in ("all_controls_green", "all_source_mutations_red",
                                              "all_registration_mutations_red", "ok", "sandbox")},
                     ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
