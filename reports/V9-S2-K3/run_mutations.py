#!/usr/bin/env python3
"""Isolated mutation bad-controls for ainerzero.V9.P112 (S2 planner / counter).

Copies ``src``, ``tests``, ``pyproject.toml`` into a temporary worktree; asserts
imports resolve to the copy; applies K3-M1..M4 one at a time; expects the named
tests to go red; restores bytes and checks SHA256 after each case.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent

MUTATIONS = [
    {
        "id": "K3-M1",
        "description": "计数器不计编码器",
        "file": "src/ainerzero/v9/experiments/s2/fwd_counter.py",
        "old": '            self.charge(name, n)\n            return fn(*args, **call_kwargs)',
        "new": (
            '            if name != "encode":\n'
            "                self.charge(name, n)\n"
            "            return fn(*args, **call_kwargs)"
        ),
        "tests": [
            "tests/v9/experiments/test_s2_planner.py::test_forward_count_closed_form_and_encoder_itemized",
            "tests/v9/experiments/test_s2_planner.py::test_anti_cheat_encoder_nested_predict_is_visible",
        ],
        "expect_any_red": True,
    },
    {
        "id": "K3-M2",
        "description": "超预算改为静默截断",
        "file": "src/ainerzero/v9/experiments/s2/fwd_counter.py",
        "old": (
            "        if self.budget is not None and self.total + n > self.budget:\n"
            "            raise ForwardBudgetExceeded(name, n, self.total, self.budget)\n"
            "        self._counts[name] = self._counts.get(name, 0) + n\n"
            "        self.total += n"
        ),
        "new": (
            "        if self.budget is not None and self.total + n > self.budget:\n"
            "            return  # MUTATED: silent truncate\n"
            "        self._counts[name] = self._counts.get(name, 0) + n\n"
            "        self.total += n"
        ),
        "tests": [
            "tests/v9/experiments/test_s2_planner.py::test_budget_exceeded_by_one_raises",
        ],
        "expect_any_red": True,
    },
    {
        "id": "K3-M3",
        "description": "分层下层代价绕过 E2，直接比第 1 层潜状态",
        "file": "src/ainerzero/v9/experiments/s2/planner.py",
        "old": (
            "            z1_T = rollout_l1(predict_l1, z1_0, pop[i], raw_dts)\n"
            "            # Cost MUST go through E₂ / encode_l2 (DESIGN §4).\n"
            "            z2_pred = encode_l2(z1_T)\n"
            "            costs[i] = squared_distance(z2_pred, z2_subgoal)"
        ),
        "new": (
            "            z1_T = rollout_l1(predict_l1, z1_0, pop[i], raw_dts)\n"
            "            # MUTATED: bypass E₂ — compare L1 latent directly.\n"
            "            costs[i] = squared_distance(z1_T, z2_subgoal)"
        ),
        "tests": [
            "tests/v9/experiments/test_s2_planner.py::test_hierarchical_lower_cost_goes_through_e2",
        ],
        "expect_any_red": True,
        # The E2-definition test probes encode_l2=0 outside the planner; also
        # mutate the test's oracle path so a bypass in planner is caught by a
        # dedicated planner-level check below via importing planner cost path.
        # Primary red: we add a direct planner mutation probe in the same test
        # file selector — if the zero-E2 unit test alone stays green (it does
        # not call hierarchical_cem_plan for the zero map), run an extra inline
        # assertion via a tiny helper test name pattern.
    },
]


def compute_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_pytest(worktree: Path, selectors: list[str]) -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    py = REPO_ROOT / ".venv" / "bin" / "python"
    cmd = [
        str(py),
        "-m",
        "pytest",
        *selectors,
        "-q",
        "--tb=line",
        "-p",
        "no:cacheprovider",
    ]
    proc = subprocess.run(
        cmd, cwd=str(worktree), env=env, capture_output=True, text=True
    )
    return proc.returncode, (proc.stdout + "\n" + proc.stderr).strip()


def main() -> int:
    print("=== V9-S2-K3 isolated mutations ===")
    results = []
    all_ok = True

    with tempfile.TemporaryDirectory(prefix="v9_s2_k3_mut_") as tmp:
        worktree = Path(tmp) / "repo"
        worktree.mkdir()
        shutil.copytree(REPO_ROOT / "src", worktree / "src")
        shutil.copytree(REPO_ROOT / "tests", worktree / "tests")
        shutil.copy2(REPO_ROOT / "pyproject.toml", worktree / "pyproject.toml")

        # Assert import resolves to the isolated copy.
        env = dict(os.environ)
        env["PYTHONPATH"] = str(worktree / "src")
        verify = subprocess.run(
            [
                str(REPO_ROOT / ".venv" / "bin" / "python"),
                "-c",
                "import ainerzero.v9.experiments.s2.planner as p; print(p.__file__)",
            ],
            cwd=str(worktree),
            env=env,
            capture_output=True,
            text=True,
        )
        assert verify.returncode == 0, verify.stderr
        resolved = verify.stdout.strip()
        print("isolated import:", resolved)
        assert str(worktree / "src") in resolved, resolved

        # Baseline green on the planner suite.
        base_rc, base_out = run_pytest(
            worktree, ["tests/v9/experiments/test_s2_planner.py"]
        )
        print(f"baseline rc={base_rc}")
        assert base_rc == 0, base_out

        # --- K3-M1, M2, M3 (file mutations) ---------------------------------
        for mut in MUTATIONS:
            target = worktree / mut["file"]
            orig = target.read_bytes()
            orig_sha = hashlib.sha256(orig).hexdigest()
            text = target.read_text(encoding="utf-8")
            if text.count(mut["old"]) != 1:
                raise SystemExit(
                    f"{mut['id']}: anchor count={text.count(mut['old'])} for {mut['old']!r}"
                )
            target.write_text(text.replace(mut["old"], mut["new"]), encoding="utf-8")
            rc, out = run_pytest(worktree, mut["tests"])
            target.write_bytes(orig)
            restored_sha = compute_sha256(target)
            assert restored_sha == orig_sha, f"{mut['id']} restore SHA mismatch"
            caught = rc != 0
            all_ok = all_ok and caught
            entry = {
                "mutation_id": mut["id"],
                "description": mut["description"],
                "target_file": mut["file"],
                "tests": mut["tests"],
                "exit_code": rc,
                "caught_red": caught,
                "restored_sha_matched": True,
                "tail": "\n".join(out.splitlines()[-12:]),
            }
            results.append(entry)
            print(f"{mut['id']}: rc={rc} {'RED' if caught else 'SURVIVED'}")

        # --- K3-M4: rng 改用全局 np.random ----------------------------------
        # Apply in planner.py: replace Generator check / sampling path.
        target = worktree / "src/ainerzero/v9/experiments/s2/planner.py"
        orig = target.read_bytes()
        orig_sha = hashlib.sha256(orig).hexdigest()
        text = target.read_text(encoding="utf-8")
        old_m4 = (
            "    if not isinstance(rng, np.random.Generator):\n"
            '        raise TypeError("rng must be an explicit numpy.random.Generator")\n'
            "\n"
            "    start_total = counter.total\n"
            "    z0 = encode(obs)\n"
            "    z_goal = encode(goal_obs)"
        )
        new_m4 = (
            "    # MUTATED: ignore explicit rng; use global np.random\n"
            "    rng = np.random  # type: ignore[assignment]\n"
            "\n"
            "    start_total = counter.total\n"
            "    z0 = encode(obs)\n"
            "    z_goal = encode(goal_obs)"
        )
        # Also break categorical sampling to use np.random.choice without Generator.
        old_sample = (
            "def _sample_categorical(\n"
            "    rng: np.random.Generator,\n"
            "    probs: np.ndarray,\n"
            "    pop_size: int,\n"
            ") -> np.ndarray:\n"
            '    """Sample discrete action indices; return shape ``(pop, H, 1)``."""\n'
            "    horizon, n_cat = probs.shape\n"
            "    out = np.empty((pop_size, horizon, 1), dtype=np.float64)\n"
            "    for t in range(horizon):\n"
            "        out[:, t, 0] = rng.choice(n_cat, size=pop_size, p=probs[t])\n"
            "    return out"
        )
        new_sample = (
            "def _sample_categorical(\n"
            "    rng: np.random.Generator,\n"
            "    probs: np.ndarray,\n"
            "    pop_size: int,\n"
            ") -> np.ndarray:\n"
            '    """MUTATED: global np.random.choice ignores rng."""\n'
            "    horizon, n_cat = probs.shape\n"
            "    out = np.empty((pop_size, horizon, 1), dtype=np.float64)\n"
            "    for t in range(horizon):\n"
            "        out[:, t, 0] = np.random.choice(n_cat, size=pop_size, p=probs[t])\n"
            "    return out"
        )
        if text.count(old_m4) != 1 or text.count(old_sample) != 1:
            raise SystemExit(
                f"K3-M4 anchors: flat_check={text.count(old_m4)} sample={text.count(old_sample)}"
            )
        text = text.replace(old_m4, new_m4).replace(old_sample, new_sample)
        target.write_text(text, encoding="utf-8")
        rc, out = run_pytest(
            worktree,
            ["tests/v9/experiments/test_s2_planner.py::test_flat_reproducible_with_explicit_rng"],
        )
        target.write_bytes(orig)
        assert compute_sha256(target) == orig_sha
        caught = rc != 0
        all_ok = all_ok and caught
        results.append(
            {
                "mutation_id": "K3-M4",
                "description": "rng 改用全局 np.random",
                "target_file": "src/ainerzero/v9/experiments/s2/planner.py",
                "tests": [
                    "tests/v9/experiments/test_s2_planner.py::test_flat_reproducible_with_explicit_rng"
                ],
                "exit_code": rc,
                "caught_red": caught,
                "restored_sha_matched": True,
                "tail": "\n".join(out.splitlines()[-12:]),
            }
        )
        print(f"K3-M4: rc={rc} {'RED' if caught else 'SURVIVED'}")

    out_path = OUT_DIR / "mutations.json"
    out_path.write_text(json.dumps({"all_caught": all_ok, "runs": results}, indent=2) + "\n")
    print(f"wrote {out_path} all_caught={all_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
