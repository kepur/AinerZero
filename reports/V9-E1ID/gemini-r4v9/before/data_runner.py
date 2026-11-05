"""Data generation runner for E1 benchmark (ainerzero.V9.P75).

Orchestrates AnimeWorld Zero (AWZ) E0 physical simulation data generation via subprocess,
and manages dataset export and dual-family (P and S) final partition sealing.

Key principles:
1. Subprocess orchestration: executes AWZ generator using AWZ's `.venv/bin/python` with
   working directory set to AWZ root and PYTHONPATH configured to include its python modules.
2. Dual-family generation: generates raw E0 sequence JSONs for both P (classical physics)
   and S (systematic mechanism modifications, e.g. quadratic aerodynamic drag) across
   train, development, and final partitions.
3. Clean export: decouples raw sequences into student views (strictly sanitized, passing
   leakage guards) and evaluator truth views (recording true physical parameters, mechanisms,
   and S <-> P pairings).
4. Dual-family final sealing: both P and S final partitions are sealed under
   `sealed_final/<family>/<digest>/` via `export.seal_final_dataset`. Unsealed final files
   are strictly forbidden and removed immediately after sealing.
5. Fail-closed budget and deadline enforcement: immediately terminates and returns
   `status='stopped'` without spawning subprocesses if budget <= 0 or current time past deadline.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence

from ainerzero.v9.experiments.e1.export import (
    assert_no_leakage,
    export_sequence,
    seal_final_dataset,
)
from ainerzero.v9.experiments.e1.spec import FAMILIES as DEFAULT_FAMILIES

# =========================================================================
# Module Constants (待一级冻结)
# =========================================================================

DEFAULT_AWZ_ROOT: Path = Path("/Users/mac/AinerWorkFlow/AnimeWorldZero")  # 待一级冻结
DEFAULT_AWZ_PYTHON: Path = DEFAULT_AWZ_ROOT / ".venv" / "bin" / "python"  # 待一级冻结
DEFAULT_PARTITIONS: tuple[str, ...] = ("train", "development", "final")  # 待一级冻结


# Driver script executed by AWZ Python subprocess
AWZ_DRIVER_CODE: str = """
import argparse
import json
import os
from pathlib import Path
import sys

def main():
    parser = argparse.ArgumentParser(description="AWZ E0 Data Generator Driver")
    parser.add_argument("--raw-dir", required=True, help="Directory to save raw E0 sequence JSONs")
    parser.add_argument("--counts-json", required=True, help="JSON dictionary of counts per family and partition")
    parser.add_argument("--awz-root", default=None, help="Root directory of AWZ")
    args = parser.parse_args()

    awz_root = Path(args.awz_root) if args.awz_root else Path(os.getcwd())
    py_dir = awz_root / "python"
    if str(py_dir) not in sys.path:
        sys.path.insert(0, str(py_dir))

    from animeworld.e0.dataset import E0DatasetGenerator

    raw_dir = Path(args.raw_dir)
    counts = json.loads(args.counts_json)

    gen = E0DatasetGenerator()
    scenario_types = gen.builder.SCENARIO_TYPES

    manifest = {"files": {}, "counts": {}}

    for fam in ("P", "S"):
        fam_counts = counts.get(fam, {})
        manifest["files"][fam] = {}
        for part in ("train", "development", "final"):
            n_seq = int(fam_counts.get(part, 0))
            manifest["counts"][f"{fam}_{part}"] = n_seq
            manifest["files"][fam][part] = []
            if n_seq <= 0:
                continue

            part_dir = raw_dir / fam / part
            part_dir.mkdir(parents=True, exist_ok=True)

            for i in range(n_seq):
                stype = scenario_types[i % len(scenario_types)]
                seq = gen.generate_sequence(part, stype, i, family=fam)
                out_path = part_dir / f"{seq['sequence_id']}.json"
                out_path.write_text(json.dumps(seq, indent=2, sort_keys=True), encoding="utf-8")
                manifest["files"][fam][part].append(str(out_path))

    manifest_file = raw_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[AWZ_DRIVER] Successfully generated sequences. Manifest written to {manifest_file}")

if __name__ == "__main__":
    main()
"""


# =========================================================================
# Helper Functions
# =========================================================================

def normalize_counts(counts: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """Normalize caller counts input into {family: {partition: int}}."""
    normalized: dict[str, dict[str, int]] = {"P": {}, "S": {}}
    if "P" in counts or "S" in counts:
        for fam in DEFAULT_FAMILIES:
            fam_c = counts.get(fam, {})
            normalized[fam] = {
                part: int(fam_c.get(part, 0))
                for part in DEFAULT_PARTITIONS
            }
    else:
        for fam in DEFAULT_FAMILIES:
            normalized[fam] = {
                part: int(counts.get(part, 0))
                for part in DEFAULT_PARTITIONS
            }
    return normalized


def run_awz_generator_subprocess(
    raw_dir: Path | str,
    counts: Mapping[str, Mapping[str, int]],
    *,
    awz_root: Path | str = DEFAULT_AWZ_ROOT,
    awz_python: Path | str = DEFAULT_AWZ_PYTHON,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """Execute AWZ generator subprocess using AWZ python."""
    raw_path = Path(raw_dir)
    raw_path.mkdir(parents=True, exist_ok=True)
    awz_root_path = Path(awz_root)
    awz_python_path = Path(awz_python)

    if not awz_python_path.is_file():
        raise FileNotFoundError(f"AWZ Python executable not found at: {awz_python_path}")

    env = dict(os.environ)
    py_dir = awz_root_path / "python"
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{py_dir}:{existing_pp}" if existing_pp else str(py_dir)

    cmd = [
        str(awz_python_path),
        "-c",
        AWZ_DRIVER_CODE,
        "--raw-dir",
        str(raw_path),
        "--counts-json",
        json.dumps(counts),
        "--awz-root",
        str(awz_root_path),
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(awz_root_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )

    if proc.returncode != 0:
        raise RuntimeError(
            f"AWZ generator subprocess failed with exit code {proc.returncode}.\n"
            f"STDOUT:\n{proc.stdout}\n"
            f"STDERR:\n{proc.stderr}"
        )

    manifest_file = raw_path / "manifest.json"
    if manifest_file.is_file():
        return json.loads(manifest_file.read_text(encoding="utf-8"))
    return {"status": "ok", "raw_dir": str(raw_path)}


# =========================================================================
# Core Data Generation and Export Runner
# =========================================================================

def generate_and_export(
    counts: Mapping[str, Any],
    raw_dir: Path | str,
    data_dir: Path | str,
    *,
    wall_budget_s: float = 120.0,
    deadline: float | None = None,
    clock: Callable[[], float] = time.time,
    runner_fn: Callable[..., Any] | None = None,
    awz_root: Path | str = DEFAULT_AWZ_ROOT,
    awz_python: Path | str = DEFAULT_AWZ_PYTHON,
) -> dict[str, Any]:
    """Generate raw simulation data from AWZ and export to student/evaluator structures.

    Parameters:
        counts: sequence counts specification, e.g. {'train': 1, 'development': 1, 'final': 1}.
        raw_dir: destination for raw un-sanitized E0 JSON sequences.
        data_dir: destination for sanitized student views, evaluator truth views, and sealed final datasets.
        wall_budget_s: maximum allowable wall-clock budget in seconds.
        deadline: optional absolute clock deadline.
        clock: timing provider function (default time.time).
        runner_fn: optional runner injection for unit testing / mocking subprocess.
        awz_root: root path of AnimeWorldZero repository.
        awz_python: python interpreter path of AnimeWorldZero venv.

    Returns:
        Summary dict containing status, counts, and sealed final digests.
    """
    t_start = clock()
    norm_counts = normalize_counts(counts)

    # 1. Fail-closed budget and deadline check
    if wall_budget_s <= 0 or (deadline is not None and clock() >= deadline):
        return {
            "status": "stopped",
            "reason": "budget_exhausted_or_past_deadline",
            "completed_counts": {"P": {}, "S": {}},
            "elapsed_s": clock() - t_start,
        }

    raw_path = Path(raw_dir)
    data_path = Path(data_dir)
    raw_path.mkdir(parents=True, exist_ok=True)
    data_path.mkdir(parents=True, exist_ok=True)

    # 2. Invoke generator (either injected runner or real subprocess)
    remaining_budget = wall_budget_s - (clock() - t_start)
    if deadline is not None:
        remaining_budget = min(remaining_budget, deadline - clock())

    if remaining_budget <= 0:
        return {
            "status": "stopped",
            "reason": "budget_exhausted_or_past_deadline",
            "completed_counts": {"P": {}, "S": {}},
            "elapsed_s": clock() - t_start,
        }

    if runner_fn is not None:
        runner_fn(raw_path, norm_counts)
    else:
        run_awz_generator_subprocess(
            raw_path,
            norm_counts,
            awz_root=awz_root,
            awz_python=awz_python,
            timeout_s=remaining_budget,
        )

    # 3. Read raw sequences and index them
    raw_sequences: dict[str, dict[str, list[dict[str, Any]]]] = {
        "P": {part: [] for part in DEFAULT_PARTITIONS},
        "S": {part: [] for part in DEFAULT_PARTITIONS},
    }

    for fam in DEFAULT_FAMILIES:
        for part in DEFAULT_PARTITIONS:
            part_dir = raw_path / fam / part
            if not part_dir.is_dir():
                # Also check flat structure raw_path / part
                alt_dir = raw_path / part
                if alt_dir.is_dir():
                    part_dir = alt_dir

            if part_dir.is_dir():
                for f in sorted(part_dir.glob("*.json")):
                    if f.name == "manifest.json":
                        continue
                    try:
                        seq_data = json.loads(f.read_text(encoding="utf-8"))
                        seq_fam = str(seq_data.get("family", fam)).upper()
                        seq_part = str(seq_data.get("partition", part)).lower()
                        if seq_fam == fam and seq_part == part:
                            raw_sequences[fam][part].append(seq_data)
                    except Exception:
                        continue

    # Build P index by (partition, index) for exact S <-> P pairing
    p_by_part_and_idx: dict[tuple[str, int], dict[str, Any]] = {}
    p_by_world_key: dict[str, dict[str, Any]] = {}
    for part in DEFAULT_PARTITIONS:
        for p_seq in raw_sequences["P"][part]:
            wk = p_seq.get("world_key", "")
            p_by_world_key[wk] = p_seq
            # Sequence ID format: seq_{part}_{stype}_{idx:03d}
            parts = p_seq.get("sequence_id", "").split("_")
            if parts and parts[-1].isdigit():
                idx = int(parts[-1])
                p_by_part_and_idx[(part, idx)] = p_seq

    student_dir = data_path / "student"
    evaluator_dir = data_path / "evaluator"
    sealed_final_root = data_path / "sealed_final"

    exported_counts: dict[str, int] = {}

    # 4. Export train and development partitions
    for part in ("train", "development"):
        # Export P sequences
        p_seqs = raw_sequences["P"][part]
        p_out_s = student_dir / "P" / part
        p_out_e = evaluator_dir / "P" / part
        p_out_s.mkdir(parents=True, exist_ok=True)
        p_out_e.mkdir(parents=True, exist_ok=True)

        for p_seq in p_seqs:
            s_view, e_view = export_sequence(p_seq)
            assert_no_leakage(s_view)
            (p_out_s / f"{s_view['sequence_id']}.json").write_text(
                json.dumps(s_view, indent=2, sort_keys=True), encoding="utf-8"
            )
            (p_out_e / f"{e_view['sequence_id']}.json").write_text(
                json.dumps(e_view, indent=2, sort_keys=True), encoding="utf-8"
            )

        exported_counts[f"P_{part}"] = len(p_seqs)

        # Export S sequences paired with P
        s_seqs = raw_sequences["S"][part]
        s_out_s = student_dir / "S" / part
        s_out_e = evaluator_dir / "S" / part
        s_out_s.mkdir(parents=True, exist_ok=True)
        s_out_e.mkdir(parents=True, exist_ok=True)

        for idx, s_seq in enumerate(s_seqs):
            # Find matching P sequence
            paired_p = None
            pwk = s_seq.get("metadata", {}).get("paired_p_world_key") or s_seq.get("metadata", {}).get("hidden_parameters", {}).get("paired_p_world_key")
            if pwk and pwk in p_by_world_key:
                paired_p = p_by_world_key[pwk]
            elif (part, idx) in p_by_part_and_idx:
                paired_p = p_by_part_and_idx[(part, idx)]

            s_view, e_view = export_sequence(s_seq, paired_p_e0_data=paired_p)
            assert_no_leakage(s_view)
            (s_out_s / f"{s_view['sequence_id']}.json").write_text(
                json.dumps(s_view, indent=2, sort_keys=True), encoding="utf-8"
            )
            (s_out_e / f"{e_view['sequence_id']}.json").write_text(
                json.dumps(e_view, indent=2, sort_keys=True), encoding="utf-8"
            )

        exported_counts[f"S_{part}"] = len(s_seqs)

    # 5. Export and seal final partition for both P and S
    sealed_info: dict[str, Any] = {}

    for fam in DEFAULT_FAMILIES:
        final_seqs = raw_sequences[fam]["final"]
        if not final_seqs:
            continue

        staging_dir = raw_path / f"_staging_final_{fam}"
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)

        s_lines: list[str] = []
        t_lines: list[str] = []

        for idx, seq in enumerate(final_seqs):
            if fam == "S":
                paired_p = None
                meta = seq.get("metadata", {})
                pwk = meta.get("paired_p_world_key") or meta.get("hidden_parameters", {}).get("paired_p_world_key")
                if pwk and pwk in p_by_world_key:
                    paired_p = p_by_world_key[pwk]
                elif ("final", idx) in p_by_part_and_idx:
                    paired_p = p_by_part_and_idx[("final", idx)]
                s_view, e_view = export_sequence(seq, paired_p_e0_data=paired_p)
            else:
                s_view, e_view = export_sequence(seq)

            assert_no_leakage(s_view)
            s_lines.append(json.dumps(s_view, sort_keys=True))
            t_lines.append(json.dumps(e_view, sort_keys=True))

        (staging_dir / "student_final.jsonl").write_text("\n".join(s_lines) + "\n", encoding="utf-8")
        (staging_dir / "truth_final.jsonl").write_text("\n".join(t_lines) + "\n", encoding="utf-8")
        meta = {
            "family": fam,
            "partition": "final",
            "count": len(final_seqs),
            "created_at_unix": clock(),
        }
        (staging_dir / "export_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

        # Seal final dataset
        fam_sealed_root = sealed_final_root / fam
        seal_record = seal_final_dataset(
            staging_dir,
            sealed_root=fam_sealed_root,
            sealed_by="data_runner",
        )
        digest = seal_record["dataset_digest"]
        sealed_info[fam] = {
            "dataset_digest": digest,
            "sealed_dir": str(fam_sealed_root / digest),
            "count": len(final_seqs),
        }
        exported_counts[f"{fam}_final"] = len(final_seqs)

        # Strictly clean up unsealed final staging files
        shutil.rmtree(staging_dir)

    # Strict assertion: neither student nor evaluator directories must contain unsealed final folders
    for s_fam in DEFAULT_FAMILIES:
        unsealed_s = student_dir / s_fam / "final"
        unsealed_e = evaluator_dir / s_fam / "final"
        if unsealed_s.exists():
            shutil.rmtree(unsealed_s)
        if unsealed_e.exists():
            shutil.rmtree(unsealed_e)

    elapsed_s = clock() - t_start

    return {
        "status": "completed",
        "raw_dir": str(raw_path),
        "data_dir": str(data_path),
        "exported_counts": exported_counts,
        "sealed_final": sealed_info,
        "elapsed_s": elapsed_s,
    }
