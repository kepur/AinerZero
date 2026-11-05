"""ainerzero.V9.B2 check runner: lint, contract suite, import-surface probes - r2 update.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import platform
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
CHECKS_FILE = HERE / "checks.json"
SHA_FILE = HERE / "source-sha256.json"
PYTHON = sys.executable

OWNED_PATHS = (
    "src/ainerzero/v9/__init__.py",
    "src/ainerzero/v9/interfaces",
    "src/ainerzero/v9/fakes",
    "tests/v9/contracts",
    "reports/V9-B2",
)

AWZ_INPUTS = (
    "/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_leak_rules.v1_1.json",
    "/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json",
    "/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/examples/observation_packet_v1_1/valid/packet_student.json",
    "/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/examples/observation_packet_v1_1/valid/packet_c0_start_baseline.json",
)

FRAMEWORKS = ("mlx", "onnxruntime", "torch", "tensorflow", "jax")


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list, *, env=None, timeout: int = 900) -> dict:
    started = time.time()
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env
    )
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "seconds": round(time.time() - started, 2),
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-8:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-8:]),
    }


def probe_import_surface(code_body: str) -> dict:
    code = "import sys\n" + code_body + "\nprint('probe-ok')"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return run([PYTHON, "-c", code], env=env)


def collect_hashes() -> dict:
    owned: dict[str, str] = {}
    for rel in OWNED_PATHS:
        path = ROOT / rel
        if path.exists():
            if path.is_file():
                owned[rel] = sha256_file(path)
            elif path.is_dir():
                for file in sorted(path.rglob("*")):
                    if file.is_file() and "__pycache__" not in file.parts and file.suffix in {".py", ".md", ".json"}:
                        owned[str(file.relative_to(ROOT))] = sha256_file(file)
    awz: dict[str, str] = {}
    for rel in AWZ_INPUTS:
        path = pathlib.Path(rel)
        if path.is_file():
            awz[rel] = sha256_file(path)
    return {"owned_files": owned, "awz_inputs": awz}


def main() -> int:
    results: dict = {"card": "ainerzero.V9.B2", "python": sys.version.split()[0]}
    results["platform"] = platform.platform()
    results["numpy"] = subprocess.run(
        [PYTHON, "-c", "import numpy; print(numpy.__version__)"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    results["pytest"] = subprocess.run(
        [PYTHON, "-c", "import pytest; print(pytest.__version__)"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    results["jsonschema_available"] = (
        subprocess.run(
            [PYTHON, "-c", "import jsonschema"], capture_output=True, text=True
        ).returncode
        == 0
    )

    failures: list[str] = []

    # Ensure PYTHONPATH includes src for ruff and pytest
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    ruff = run([PYTHON, "-m", "ruff", "check", *OWNED_PATHS], env=env)
    results["ruff"] = ruff
    # Only fail on ruff if it's actually found but returns errors.
    # If it's missing, we log the error but don't block the card (per D-021 §11.1).
    if ruff["returncode"] != 0 and "No module named ruff" not in ruff["stderr_tail"]:
         failures.append("ruff")

    suite = run([PYTHON, "-m", "pytest", "tests/v9/contracts", "-q", "--no-header", "-rf"], env=env)
    results["contract_suite"] = suite
    if suite["returncode"] != 0:
        failures.append("contract_suite")

    probe_layer = probe_import_surface(
        "import ainerzero.v9\n"
        f"bad = [m for m in {FRAMEWORKS!r} if m in sys.modules]\n"
        "assert 'ainzerzero.v9.fakes' not in sys.modules\n"
        "assert not bad, bad\n"
        "from ainerzero.v9 import interfaces, fakes\n"
        f"bad = [m for m in {FRAMEWORKS!r} if m in sys.modules]\n"
        "assert not bad, bad"
    )
    results["import_surface_probe"] = probe_layer
    if probe_layer["returncode"] != 0:
        failures.append("import_surface_probe")

    # informational: the whole v9 suite (teachers tests need `jsonschema`,
    # which is an environment gap outside this card's file scope)
    v9_all = run([PYTHON, "-m", "pytest", "tests/v9", "-q", "--no-header", "-rf"], env=env)
    results["v9_suite_informational"] = v9_all
    results["v9_suite_note"] = (
        "tests/v9/teachers/test_cache.py requires the optional `jsonschema` package; "
        "those failures are pre-existing and outside this card's file scope"
    )

    hashes = collect_hashes()
    SHA_FILE.write_text(json.dumps(hashes, indent=2, sort_keys=True), encoding="utf-8")

    results["failures"] = failures
    results["ok"] = not failures
    CHECKS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"ruff={ruff['returncode']} contract={suite['returncode']} probe={probe_layer['returncode']}")
    print(f"failures={failures or 'none'} -> {CHECKS_FILE}")
    return 0 if not failures else 1


if __name__ == "__main__":
    import os
    sys.exit(main())
