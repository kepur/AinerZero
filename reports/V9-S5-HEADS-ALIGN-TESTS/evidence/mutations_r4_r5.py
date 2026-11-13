"""P247 坏对照 R4、R5。只在 git archive HEAD 的副本里改 train.py。

先断言副本不是实盘仓库。基线是叠加上工作区新测试后的
``test_s5_train_mlx.py``，必须 0 失败。然后分别注入：

- R4：``bi = np.asarray(b_indices[::-1], ...)``，对齐测试必须失败
- R5：``r3_mx = mx.array(all_r2[bi])``，R3 槽位测试必须失败

本脚本不抢锁。由 hold_lock.py 包一层再跑。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

LIVE_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PY = LIVE_REPO / ".venv/bin/python"
TEST_REL = "tests/v9/experiments/test_s5_train_mlx.py"
TRAIN_REL = "src/ainerzero/v9/experiments/s5/train.py"

ALIGN_TEST = (
    "tests/v9/experiments/test_s5_train_mlx.py"
    "::test_train_heads_batch_alignment_beats_shuffled_labels"
)
SLOT_TEST = (
    "tests/v9/experiments/test_s5_train_mlx.py"
    "::test_train_heads_r3_slot_learns_r3_not_r2"
)

MUTATIONS = (
    {
        "id": "R4_train_heads_batch_index_reversed",
        "old": "            bi = np.asarray(b_indices, dtype=np.int64)",
        "new": "            bi = np.asarray(b_indices[::-1], dtype=np.int64)",
        "node": ALIGN_TEST,
        "expect_failed": "test_train_heads_batch_alignment_beats_shuffled_labels",
    },
    {
        "id": "R5_train_heads_swap_r3_with_r2",
        "old": "            r3_mx = mx.array(all_r3[bi])",
        "new": "            r3_mx = mx.array(all_r2[bi])",
        "node": SLOT_TEST,
        "expect_failed": "test_train_heads_r3_slot_learns_r3_not_r2",
    },
)


def _assert_outside_live(path: Path) -> Path:
    resolved = path.resolve()
    assert resolved != LIVE_REPO, f"Refusing to use live repo: {resolved}"
    assert LIVE_REPO not in resolved.parents, (
        f"Target copy must be outside live repo: {resolved}"
    )
    return resolved


def export_git_archive_head(dst: Path) -> None:
    _assert_outside_live(dst)
    dst.mkdir(parents=True, exist_ok=True)
    archive = subprocess.Popen(
        ["git", "archive", "HEAD"],
        cwd=str(LIVE_REPO),
        stdout=subprocess.PIPE,
    )
    subprocess.run(["tar", "-x", "-C", str(dst)], stdin=archive.stdout, check=True)
    assert archive.wait() == 0


def run_pytest(copy_root: Path, nodes: list[str]) -> tuple[int, str]:
    _assert_outside_live(copy_root)
    env = dict(os.environ, PYTHONPATH=str(copy_root / "src"))
    env.pop("PYTEST_ADDOPTS", None)
    cmd = [
        str(PY),
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--native-mlx",
        "--tb=line",
        "-rf",
        *nodes,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(copy_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    text = proc.stdout + "\n" + proc.stderr
    return proc.returncode, text


def failed_names(text: str) -> list[str]:
    names = []
    for line in text.splitlines():
        if line.startswith("FAILED "):
            names.append(line.split("::")[-1].split(" ")[0])
    return names


def main() -> int:
    evidence = LIVE_REPO / "reports/V9-S5-HEADS-ALIGN-TESTS/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    out_lines = [f"python {PY}", f"head {subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=str(LIVE_REPO), text=True).strip()}"]
    with tempfile.TemporaryDirectory(prefix="p247_align_copy_") as tmp:
        copy_root = Path(tmp) / "repo"
        export_git_archive_head(copy_root)
        _assert_outside_live(copy_root)
        live_test = LIVE_REPO / TEST_REL
        copy_test = copy_root / TEST_REL
        assert live_test.is_file() and copy_test.is_file()
        shutil.copy2(live_test, copy_test)
        overlay = copy_test.read_text(encoding="utf-8")
        assert "test_train_heads_batch_alignment_beats_shuffled_labels" in overlay
        assert "test_train_heads_r3_slot_learns_r3_not_r2" in overlay

        train_path = copy_root / TRAIN_REL
        _assert_outside_live(train_path)
        original = train_path.read_text(encoding="utf-8")
        for mut in MUTATIONS:
            assert original.count(mut["old"]) == 1, mut["id"]

        ident = subprocess.run(
            [
                str(PY),
                "-c",
                "import ainerzero.v9.experiments.s5.train as t; print(t.__file__)",
            ],
            cwd=str(copy_root),
            env=dict(os.environ, PYTHONPATH=str(copy_root / "src")),
            capture_output=True,
            text=True,
            check=True,
        )
        imported = Path(ident.stdout.strip()).resolve()
        _assert_outside_live(imported)
        assert imported == train_path.resolve(), imported
        out_lines.append(f"imported {imported}")

        rc_base, text_base = run_pytest(copy_root, [TEST_REL])
        (evidence / "baseline_pytest.txt").write_text(text_base, encoding="utf-8")
        base_failed = failed_names(text_base)
        base_line = f"BASELINE rc={rc_base} failed={base_failed}"
        print(base_line, flush=True)
        out_lines.append(base_line)
        if rc_base != 0 or base_failed:
            raise SystemExit(f"Baseline failed: {base_line}")

        records = {
            "head": out_lines[1],
            "imported_train": str(imported),
            "baseline": {"returncode": rc_base, "failed": base_failed},
            "mutations": [],
        }

        for mut in MUTATIONS:
            assert train_path.read_text(encoding="utf-8") == original
            mutated = original.replace(mut["old"], mut["new"], 1)
            assert mutated != original
            train_path.write_text(mutated, encoding="utf-8")
            try:
                _assert_outside_live(train_path)
                rc, text = run_pytest(copy_root, [mut["node"]])
                (evidence / f"{mut['id']}.txt").write_text(text, encoding="utf-8")
                names = failed_names(text)
                killed = rc != 0 and mut["expect_failed"] in names
                status = "KILLED" if killed else "SURVIVED"
                line = f"{mut['id']}: {status} rc={rc} failed={names}"
                print(line, flush=True)
                out_lines.append(line)
                records["mutations"].append(
                    {
                        "id": mut["id"],
                        "status": status,
                        "returncode": rc,
                        "failed_tests": names,
                        "expect_failed": mut["expect_failed"],
                    }
                )
                if not killed:
                    raise SystemExit(line)
            finally:
                train_path.write_text(original, encoding="utf-8")
                assert train_path.read_text(encoding="utf-8") == original

    (evidence / "mutations_r4_r5_output.txt").write_text(
        "\n".join(out_lines) + "\n", encoding="utf-8"
    )
    (evidence / "mutations_r4_r5_results.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
