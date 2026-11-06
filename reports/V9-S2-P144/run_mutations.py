#!/usr/bin/env python3
"""P144 (board P143) mutation tests for S2 eval_runner.

Isolated copy of src/tests/pyproject.toml; restore byte-for-byte with SHA check.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    real_root = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
    out_results = real_root / "reports/V9-S2-P144/mutation_results.json"
    tmp_dir = Path(tempfile.mkdtemp(prefix="s2_p144_mutations_"))
    print(f"[Init] Isolated workspace: {tmp_dir}")

    try:
        shutil.copytree(real_root / "src", tmp_dir / "src")
        shutil.copytree(real_root / "tests", tmp_dir / "tests")
        shutil.copy2(real_root / "pyproject.toml", tmp_dir / "pyproject.toml")

        verify = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0,'src'); "
                "from ainerzero.v9.experiments.s2 import eval_runner as m; "
                "import inspect; print(inspect.getfile(m))",
            ],
            cwd=str(tmp_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        assert str(tmp_dir) in verify.stdout, verify.stdout
        print("[Isolation]", verify.stdout.strip())

        target = tmp_dir / "src/ainerzero/v9/experiments/s2/eval_runner.py"
        orig = target.read_bytes()
        orig_sha = sha256_file(target)

        clean = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/v9/experiments/test_s2_eval_runner.py", "-q"],
            cwd=str(tmp_dir),
            env=dict(os.environ, PYTHONPATH=f"{tmp_dir}/src:{tmp_dir}"),
            capture_output=True,
            text=True,
        )
        assert clean.returncode == 0, clean.stdout + clean.stderr
        print("[Baseline] GREEN")

        results = []

        def run_mut(name: str, mutate, test: str) -> None:
            print(f"\n[Test] {name}")
            target.write_text(mutate(orig.decode("utf-8")), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", test, "-q"],
                cwd=str(tmp_dir),
                env=dict(os.environ, PYTHONPATH=f"{tmp_dir}/src:{tmp_dir}"),
                capture_output=True,
                text=True,
            )
            target.write_bytes(orig)
            assert sha256_file(target) == orig_sha
            red = proc.returncode != 0
            lines = [
                ln.strip()
                for ln in proc.stdout.splitlines()
                if ln.strip().startswith("E ") or "FAILED" in ln
            ]
            summary = " | ".join(lines[:3]) if red else "Did not fail!"
            print(f"  RED={red} rc={proc.returncode} :: {summary}")
            results.append(
                {
                    "name": name,
                    "test_target": test,
                    "exit_code": proc.returncode,
                    "turned_red": red,
                    "passed": red,
                    "failure_summary": summary,
                }
            )

        run_mut(
            "P144-M1",
            lambda s: s.replace("_assert_train_only(train_episode_specs)", "pass  # mutated"),
            "tests/v9/experiments/test_s2_eval_runner.py::test_plan_select_rejects_dev_specs",
        )
        run_mut(
            "P144-M2",
            lambda s: s.replace(
                "if count >= MAX_DEV_EVALS:",
                "if count >= 10**9:  # mutated: disable practical cap",
            ),
            "tests/v9/experiments/test_s2_eval_runner.py::test_dev_eval_third_call_refused",
        )
        run_mut(
            "P144-M3",
            lambda s: s.replace(
                "if not final_rows:\n        if prereg_rows:\n            raise FinalEvalRefused(\n                \"final-eval refused: found prereg approval only; \"\n                \"need a separate APPROVED s2-phase1 final-eval line\"\n            )\n        raise FinalEvalRefused(\"final-eval refused: no qualifying final-eval approval line\")",
                "if not final_rows:\n        if prereg_rows:\n            final_rows = prereg_rows  # mutated: accept prereg as final-eval\n        else:\n            raise FinalEvalRefused(\"final-eval refused: no qualifying final-eval approval line\")",
            ),
            "tests/v9/experiments/test_s2_eval_runner.py::test_final_requires_separate_final_eval_approval",
        )
        run_mut(
            "P144-M4",
            lambda s: s.replace(
                "except FileExistsError as exc:\n        raise FinalEvalRefused(\n            f\"sealed_final already read once ({READ_ONCE_MARKER_NAME} exists)\"\n        ) from exc",
                "except FileExistsError as exc:\n        return {\"marker_path\": str(marker), \"reused\": True}  # mutated allow second read",
            ),
            "tests/v9/experiments/test_s2_eval_runner.py::test_final_read_once_and_second_refused",
        )
        run_mut(
            "P144-M5",
            lambda s: s.replace(
                "require_ci_lower: bool = True,",
                "require_ci_lower: bool = False,  # mutated ignore lower bound",
            ),
            "tests/v9/experiments/test_s2_eval_runner.py::test_gate_requires_positive_ci_lower",
        )

        out_results.write_text(json.dumps(results, indent=2) + "\n")
        ok = all(r["passed"] for r in results)
        print(f"\n[Done] {sum(r['passed'] for r in results)}/{len(results)} turned RED → {out_results}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
