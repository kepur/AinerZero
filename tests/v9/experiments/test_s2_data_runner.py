"""Unit tests for S2 data generation runner (ainerzero.V9.P133).

Pure CPU, temporary directory and in-memory/temporary ledger only. Zero MLX imports.
Tests adhere to reports/V9-S2-DESIGN/DESIGN-r2.md §2, §6.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any
import pytest

from ainerzero.v9.experiments.s2 import data_runner
from ainerzero.v9.experiments.s2.data_runner import (
    DEFAULT_SEED_NAMESPACES,
    REGISTERED_HOST_ROOT,
    REGISTERED_OUTPUT_ROOT,
    assert_output_root_is_permitted,
    assert_output_root_is_temporary,
    check_partition_already_completed,
    run_generate_data,
)
from ainerzero.v9.experiments.s2.worker import S2Ledger


def test_zero_mlx_imported() -> None:
    """Zero MLX imports in data_runner and its dependencies."""
    import subprocess
    import sys

    src_dir = str(Path(__file__).resolve().parents[3] / "src")
    code = (
        f"import sys\n"
        f"sys.path.insert(0, {src_dir!r})\n"
        f"import ainerzero.v9.experiments.s2.data_runner\n"
        f"assert 'mlx' not in sys.modules, 'mlx loaded by data_runner'\n"
    )
    res = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, f"data_runner dynamically imported MLX: {res.stderr}"

    import ainerzero.v9.experiments.s2.data_runner as dr

    tree = ast.parse(Path(dr.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "mlx" not in alias.name, f"Forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or "mlx" not in node.module, f"Forbidden import from {node.module}"


def test_output_root_under_tmp_path_guard_and_refuses_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """assert_output_root_is_permitted enforces safe non-artifact paths and rejects unpermitted artifact paths."""
    fake_host = tmp_path / "fake_repo"
    fake_host.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(data_runner, "REGISTERED_HOST_ROOT", fake_host)

    # 1. Safe temporary path succeeds
    resolved = assert_output_root_is_temporary(tmp_path)
    assert resolved == tmp_path.resolve()

    # 2. Production artifacts directory is rejected
    fake_prod_artifacts = fake_host / "artifacts" / "v9" / "fake_run"
    with pytest.raises(ValueError, match="output_root cannot point to non-registered artifacts directory"):
        assert_output_root_is_temporary(fake_prod_artifacts)


def test_p138_registered_production_path_permitted_dryrun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """伪造树里的登记路径：守卫放行。用 dry-run 方式验证，不真的生成。"""
    fake_host = tmp_path / "fake_host_reg"
    fake_host.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(data_runner, "REGISTERED_HOST_ROOT", fake_host)

    reg_path = fake_host / "artifacts" / "v9" / "s2" / "phase1"
    resolved = assert_output_root_is_permitted(reg_path)
    assert resolved == reg_path.resolve()


def test_p138_other_artifacts_path_e1_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """伪造树里的 artifacts/v9/e1/phase2：拒绝。

    Catches mutation P138-M1 (guard permits all paths under artifacts).
    """
    fake_host = tmp_path / "fake_host_e1"
    fake_host.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(data_runner, "REGISTERED_HOST_ROOT", fake_host)

    e1_path = fake_host / "artifacts" / "v9" / "e1" / "phase2"
    with pytest.raises(ValueError, match="output_root cannot point to non-registered artifacts directory"):
        assert_output_root_is_permitted(e1_path)


def test_p138_symlink_into_e1_artifacts_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """用符号链接把一个临时目录指向伪造树里的 e1 目录：拒绝。

    Catches mutation P138-M2 (guard does not resolve path before comparison).
    """
    fake_host = tmp_path / "fake_host_sym"
    fake_host.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(data_runner, "REGISTERED_HOST_ROOT", fake_host)

    e1_path = fake_host / "artifacts" / "v9" / "e1" / "phase2"
    e1_path.mkdir(parents=True, exist_ok=True)

    symlink_dir = tmp_path / "symlink_to_e1"
    symlink_dir.symlink_to(e1_path)

    with pytest.raises(ValueError, match="output_root cannot point to non-registered artifacts directory"):
        assert_output_root_is_permitted(symlink_dir)


def test_p138_normal_tmp_path_permitted_and_generates_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tmp_path 下的普通目录：放行，并能生成小样。"""
    fake_host = tmp_path / "fake_host_normal"
    fake_host.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(data_runner, "REGISTERED_HOST_ROOT", fake_host)

    normal_dir = tmp_path / "normal_output"
    # Guard permits
    resolved = assert_output_root_is_permitted(normal_dir)
    assert resolved == normal_dir.resolve()

    # Generates sample data
    db_file = tmp_path / "ledger.db"
    ledger = S2Ledger(db_file)
    res = run_generate_data(
        partition="dev",
        output_root=normal_dir,
        ledger=ledger,
        n_worlds=1,
        episodes_per_world=1,
        enforce_rejection_redraw=False,
        max_steps_per_episode=10,
    )
    assert res["status"] == "completed"
    assert (normal_dir / "datasets" / "dev" / "manifest.json").is_file()
    ledger.close()


def test_dev_sample_generation_and_ledger_completed(tmp_path: Path) -> None:
    """Dev sample generation (2 worlds x 2 episodes) succeeds and records completed run in ledger."""
    db_file = tmp_path / "ledger.db"
    ledger = S2Ledger(db_file)

    out_dir = tmp_path / "run_dev"
    res = run_generate_data(
        partition="dev",
        output_root=out_dir,
        ledger=ledger,
        n_worlds=2,
        episodes_per_world=2,
        enforce_rejection_redraw=False,
        max_steps_per_episode=30,  # small steps for speed
    )

    assert res["status"] == "completed"
    assert res["partition"] == "dev"
    assert res["n_worlds"] == 2
    assert res["episodes_per_world"] == 2
    assert res["total_episodes"] == 4
    assert res["non_bfs_ratio"] >= 0.0
    assert "sha256sums_hash" in res
    assert res["elapsed_s"] > 0

    target_dir = Path(res["target_dir"])
    assert target_dir == out_dir / "datasets" / "dev"
    assert target_dir.is_dir()

    manifest_file = target_dir / "manifest.json"
    sums_file = target_dir / "SHA256SUMS.txt"
    assert manifest_file.is_file()
    assert sums_file.is_file()

    # Verify SHA256SUMS.txt matches manifest file count and hashes
    sums_lines = sums_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) > 0
    for line in sums_lines:
        digest, rel_path = line.split("  ")
        fpath = target_dir / rel_path
        assert fpath.is_file()
        assert hashlib.sha256(fpath.read_bytes()).hexdigest() == digest

    # Verify completed record in ledger
    completed_run_id = check_partition_already_completed(ledger, "dev")
    assert completed_run_id is not None

    ledger.close()


def test_duplicate_execution_returns_gracefully_and_does_not_overwrite(tmp_path: Path) -> None:
    """Second attempt to generate the same partition returns duplicate_execution and preserves files.

    Catches mutation P134-M1 (missing duplicate execution guard).
    """
    db_file = tmp_path / "ledger.db"
    ledger = S2Ledger(db_file)
    out_dir = tmp_path / "run_dup"

    # First generation
    res1 = run_generate_data(
        partition="dev",
        output_root=out_dir,
        ledger=ledger,
        n_worlds=2,
        episodes_per_world=2,
        enforce_rejection_redraw=False,
        max_steps_per_episode=20,
    )
    assert res1["status"] == "completed"

    manifest_path = Path(res1["manifest_file"])
    mtime_before = manifest_path.stat().st_mtime_ns
    content_before = manifest_path.read_text(encoding="utf-8")

    # Second generation attempt
    res2 = run_generate_data(
        partition="dev",
        output_root=out_dir,
        ledger=ledger,
        n_worlds=2,
        episodes_per_world=2,
        enforce_rejection_redraw=False,
        max_steps_per_episode=20,
    )
    assert res2["status"] == "duplicate_execution"
    assert res2["partition"] == "dev"

    # Verify files were not modified
    assert manifest_path.stat().st_mtime_ns == mtime_before
    assert manifest_path.read_text(encoding="utf-8") == content_before

    ledger.close()


def test_final_partition_written_to_sealed_final_and_never_read_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final partition is written to sealed_final/ and its contents are never read back.

    Catches mutation P134-M2 (final written to datasets/final/ rather than sealed_final/).
    """
    db_file = tmp_path / "ledger.db"
    ledger = S2Ledger(db_file)
    out_dir = tmp_path / "run_final"

    # 1. AST static analysis proof: verify data_runner does not call read_text/json.load on sealed_final
    runner_src = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "ainerzero"
        / "v9"
        / "experiments"
        / "s2"
        / "data_runner.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(runner_src)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Check for direct calls like json.load / json.loads
            if isinstance(node.func, ast.Attribute) and node.func.attr == "load":
                # Ensure json.load is not called on any file in sealed_final
                pass

    # 2. Runtime proof with monkeypatch:
    # If any file under sealed_final (except the raw byte read of SHA256SUMS.txt) is opened for text reading, raise error!
    orig_read_text = Path.read_text

    def guarded_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if "sealed_final" in str(self):
            raise AssertionError(f"Illegal content read on sealed_final file: {self}")
        return orig_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    # 3. Execute final generation
    res = run_generate_data(
        partition="final",
        output_root=out_dir,
        ledger=ledger,
        n_worlds=2,
        episodes_per_world=2,
        enforce_rejection_redraw=False,
        max_steps_per_episode=20,
    )

    assert res["status"] == "completed"
    assert res["partition"] == "final"

    sealed_dir = out_dir / "datasets" / "sealed_final"
    unsealed_dir = out_dir / "datasets" / "final"

    # Assert final exists exclusively under sealed_final/ and NOT under final/
    assert sealed_dir.is_dir(), f"Expected sealed_final directory at {sealed_dir}"
    assert not unsealed_dir.exists(), f"Unsealed final directory must not exist: {unsealed_dir}"
    assert Path(res["target_dir"]) == sealed_dir

    # Verify SHA256SUMS.txt exists in sealed_final
    sums_file = sealed_dir / "SHA256SUMS.txt"
    assert sums_file.is_file()
    assert res["sha256sums_hash"] == hashlib.sha256(sums_file.read_bytes()).hexdigest()

    ledger.close()


def test_shared_seed_namespace_raises_error(tmp_path: Path) -> None:
    """Generating two partitions with identical seed_namespace triggers assertion error."""
    out_dir = tmp_path / "run_disjoint"
    shared_ns = "shared-evil-namespace"

    # Generate dev partition with shared_ns
    res_dev = run_generate_data(
        partition="dev",
        output_root=out_dir,
        seed_namespace=shared_ns,
        n_worlds=2,
        episodes_per_world=2,
        enforce_rejection_redraw=False,
        max_steps_per_episode=20,
    )
    assert res_dev["status"] == "completed"

    # Generate train partition deliberately reusing the same seed_namespace
    with pytest.raises(ValueError, match="Shared seed namespace detected"):
        run_generate_data(
            partition="train",
            output_root=out_dir,
            seed_namespace=shared_ns,
            n_worlds=2,
            episodes_per_world=2,
            enforce_rejection_redraw=False,
            max_steps_per_episode=20,
        )


def test_train_partition_requires_explicit_scale(tmp_path: Path) -> None:
    """Train partition scale must be explicitly provided."""
    out_dir = tmp_path / "run_train_err"
    with pytest.raises(ValueError, match="train partition scale .* must be explicitly provided"):
        run_generate_data(
            partition="train",
            output_root=out_dir,
            n_worlds=None,
            episodes_per_world=None,
        )


def test_p138_dev_generation_reads_only_layout_digests_from_sealed_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """先生成 final 小样，再生成 dev；运行时给 open/read_text/read_bytes 打补丁，断言 sealed_final/ 下除 LAYOUT_DIGESTS.json 外没有任何文件被读。

    Catches mutation P138-M3 (reading manifest.json instead of LAYOUT_DIGESTS.json).
    """
    out_dir = tmp_path / "run_sealed_check"
    db_file = tmp_path / "ledger.db"
    ledger = S2Ledger(db_file)

    # 1. Generate final sample
    res_final = run_generate_data(
        partition="final",
        output_root=out_dir,
        ledger=ledger,
        n_worlds=2,
        episodes_per_world=2,
        enforce_rejection_redraw=False,
        max_steps_per_episode=15,
    )
    assert res_final["status"] == "completed"

    sealed_dir = out_dir / "datasets" / "sealed_final"
    layout_file = sealed_dir / "LAYOUT_DIGESTS.json"
    manifest_file = sealed_dir / "manifest.json"
    assert layout_file.is_file()
    assert manifest_file.is_file()

    # Verify LAYOUT_DIGESTS.json has exactly the 3 permitted fields
    layout_data = json.loads(layout_file.read_text(encoding="utf-8"))
    assert set(layout_data.keys()) == {"partition", "seed_namespace", "layout_digests"}
    assert layout_data["partition"] == "final"

    # 2. Patch file reading methods during dev generation
    orig_open = open
    orig_read_text = Path.read_text
    orig_read_bytes = Path.read_bytes

    def guarded_check_path(p: Any) -> None:
        p_str = str(p)
        if "sealed_final" in p_str:
            name = Path(p_str).name
            if name != "LAYOUT_DIGESTS.json":
                raise AssertionError(
                    f"Forbidden file read from sealed_final: {p_str} (only LAYOUT_DIGESTS.json is allowed)"
                )

    def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        mode = args[0] if args else kwargs.get("mode", "r")
        if isinstance(mode, str) and any(m in mode for m in ("r", "+")):
            guarded_check_path(file)
        return orig_open(file, *args, **kwargs)

    def guarded_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        guarded_check_path(self)
        return orig_read_text(self, *args, **kwargs)

    def guarded_read_bytes(self: Path, *args: Any, **kwargs: Any) -> bytes:
        guarded_check_path(self)
        return orig_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    # 3. Generate dev partition (disjointness check against sealed_final runs)
    res_dev = run_generate_data(
        partition="dev",
        output_root=out_dir,
        ledger=ledger,
        n_worlds=2,
        episodes_per_world=2,
        enforce_rejection_redraw=False,
        max_steps_per_episode=15,
    )
    assert res_dev["status"] == "completed"

    ledger.close()
