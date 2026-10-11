"""Engineering checks and declaration inspection; no Brain-0 training command."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from ainerzero import __version__
from ainerzero.core.config import config_hash, load_config
from ainerzero.core.pilot import load_pilot_config, pilot_config_hash
from ainerzero.runtime.checkpoints import atomic_write_json
from ainerzero.runtime.hardware import collect_hardware
from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore


@contextmanager
def worker_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("A worker is already running in this project") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def project_root(config_path: Path) -> Path:
    for path in config_path.resolve().parents:
        if (path / "pyproject.toml").is_file():
            return path
    return Path.cwd()


def pilot_manifest(config_path: Path) -> dict:
    """Resolve a declaration with source identity, without registering a run.

    This digest identifies the current local implementation, including its
    unimplemented parts. It does not assert that declared algorithms exist.
    """
    config = load_pilot_config(config_path)
    root = project_root(config_path)
    paths = sorted((root / "src" / "ainerzero").rglob("*.py"))
    paths.extend(root / name for name in ("pyproject.toml", "uv.lock"))
    if not paths or not (root / "src" / "ainerzero" / "cli.py").is_file():
        raise ValueError("pilot manifest requires the project source tree")
    files = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    source_hash = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = config.model_dump(mode="json")
    manifest["source"] = {"sha256": source_hash, "files": files}
    return {
        "status": "valid",
        "execution_status": "not_started",
        "config_hash": pilot_config_hash(config),
        "manifest": manifest,
    }


def train_pilot_command(args) -> dict:
    """Exclusive, bounded worker with visible cleanup on native failure/timeout."""
    from ainerzero.runtime.pilot_worker import fit_manifest

    config = load_pilot_config(args.config)
    diagnostic = getattr(args, "source_report", None)
    recall = getattr(args, "recall_diagnostic", False)
    residual = getattr(args, "residual_diagnostic", False)
    memory = getattr(args, "memory_training", False)
    micro_memory = getattr(args, "micro_memory_training", False)
    diverse_memory = getattr(args, "diverse_memory_training", False)
    relabel_memory = getattr(args, "relabel_memory_training", False)
    interference = getattr(args, "interference_diagnostic", False)
    paired_memory = getattr(args, "paired_memory_diagnostic", False)
    coverage = getattr(args, "coverage_diagnostic", False)
    history = getattr(args, "history_diagnostic", False)
    if paired_memory or coverage:
        module = (
            "ainerzero.runtime.coverage_worker"
            if coverage
            else "ainerzero.runtime.paired_memory_worker"
        )
        extra = [
            "--dataset",
            str(args.dataset.resolve()),
            "--checkpoint",
            str(args.checkpoint.resolve()),
            "--candidate-checkpoint",
            str(args.candidate_checkpoint.resolve()),
            "--source-report",
            str(args.source_report.resolve()),
        ]
    elif interference:
        module = "ainerzero.runtime.interference_worker"
        extra = [
            "--dataset",
            str(args.dataset.resolve()),
            "--checkpoint",
            str(args.checkpoint.resolve()),
            "--candidate-checkpoint",
            str(args.candidate_checkpoint.resolve()),
        ]
    elif memory or micro_memory or diverse_memory or relabel_memory:
        module = "ainerzero.runtime.memory_worker"
        extra = [
            "--dataset",
            str(args.dataset.resolve()),
            "--checkpoint",
            str(args.checkpoint.resolve()),
        ]
        if micro_memory:
            extra.append("--local-fit")
        if diverse_memory:
            extra.extend(
                ["--diverse-fit", "--comparison-report", str(args.comparison_report.resolve())]
            )
        if relabel_memory:
            extra.extend(
                [
                    "--relabel-fit",
                    "--comparison-report",
                    str(args.comparison_report.resolve()),
                    "--m2l-report",
                    str(args.m2l_report.resolve()),
                    "--m2l-checkpoint",
                    str(args.m2l_checkpoint.resolve()),
                ]
            )
    elif history or recall or residual:
        module = "ainerzero.runtime.history_worker"
        extra = [
            "--dataset",
            str(args.dataset.resolve()),
            "--checkpoint",
            str(args.checkpoint.resolve()),
        ]
        if residual:
            extra.append("--residual")
        elif recall:
            extra.append("--recall")
    elif getattr(args, "observation_first", False):
        module = "ainerzero.runtime.observation_worker"
        extra = [
            "--dataset",
            str(args.dataset.resolve()),
            "--structure",
            getattr(args, "structure", "paired"),
        ]
        if getattr(args, "initial_checkpoint", None):
            extra.extend(["--initial-checkpoint", str(args.initial_checkpoint.resolve())])
        if getattr(args, "action_comparison", False):
            extra.extend(
                ["--action-comparison", "--comparison-arm", getattr(args, "comparison_arm", "all")]
            )
    elif diagnostic:
        module = "ainerzero.runtime.pilot_diagnostics"
        extra = ["--source-report", str(diagnostic.resolve())]
    else:
        config.snapshot_for_run(args.seed)
        augmentation = getattr(args, "symbol_augmentation", "none")
        fit_manifest(
            config.model_dump(mode="json"),
            updates=args.updates,
            train_episodes=args.train_episodes,
            development_episodes=args.development_episodes,
            symbol_augmentation=augmentation,
        )
        module = "ainerzero.runtime.pilot_worker"
        extra = [
            "--seed",
            str(args.seed),
            "--updates",
            str(args.updates),
            "--train-episodes",
            str(args.train_episodes),
            "--development-episodes",
            str(args.development_episodes),
            "--symbol-augmentation",
            augmentation,
        ]
        if getattr(args, "dataset", None):
            extra.extend(["--dataset", str(args.dataset.resolve())])
    data_dir = project_root(args.config) / config.storage.data_dir
    control_db = (data_dir / "control.sqlite3").resolve()
    with worker_lock(data_dir / "locks" / "m0-worker.lock"):
        with RunStore(control_db) as store:
            prior_runs = {r.run_id for r in store.list_runs()}
        prior_reports = set(args.output_dir.glob("pilot-*/report.json"))
        report = None
        exit_code = 1
        error = "pilot worker exited without a valid report"
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    module,
                    "--config",
                    str(args.config.resolve()),
                    "--output-dir",
                    str(args.output_dir.resolve()),
                    "--control-db",
                    str(control_db),
                    "--experiment-id",
                    args.experiment_id,
                    *extra,
                ],
                capture_output=True,
                text=True,
                timeout=min(
                    750
                    if coverage
                    else 1770
                    if relabel_memory
                    else 1550
                    if memory or micro_memory or diverse_memory
                    else 650
                    if recall or residual or interference or paired_memory
                    else 450
                    if history
                    else 180
                    if diagnostic
                    else 1200,
                    config.budget.max_wall_seconds,
                ),
            )
            exit_code = result.returncode
            lines = result.stdout.strip().splitlines()
            if lines:
                try:
                    report = json.loads(lines[-1])
                except json.JSONDecodeError:
                    pass
            if not isinstance(report, dict):
                report = None
                if result.stderr:
                    error += "; " + result.stderr[-1500:]
        except subprocess.TimeoutExpired:
            error = "pilot supervisor timeout; worker terminated"
        finally:
            interrupted = []
            with RunStore(control_db) as store:
                for run in store.list_runs():
                    if run.run_id not in prior_runs and run.state not in TERMINAL_STATES:
                        store.transition(run.run_id, "failed", reason="pilot_supervisor_cleanup")
                        interrupted.append(run.run_id)
            if report is None or interrupted or exit_code != 0:
                report = report or {"status": "failed", "error": error}
                if report.get("status") == "completed":
                    report["status"] = "failed"
                    report["error"] = error
                report["worker_exit_code"] = exit_code
                report["interrupted_run_ids"] = interrupted
                for path in set(args.output_dir.glob("pilot-*/report.json")) - prior_reports:
                    saved = json.loads(path.read_text())
                    saved.update(report)
                    atomic_write_json(path, saved)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ainerzero", description="AinerZero 工程自检与实验声明")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    config_parser = commands.add_parser("check-config", help="校验配置并输出稳定哈希")
    config_parser.add_argument("--config", type=Path, default=Path("configs/brain0.yaml"))
    pilot = commands.add_parser(
        "check-pilot", help="校验首轮实验声明和源码摘要，不启动实验计时或训练"
    )
    pilot.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    pilot.add_argument("--output", type=Path)
    train = commands.add_parser("train-pilot", help="短预算 C0 预测训练、基线比较和保存验证")
    train.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    train.add_argument("--experiment-id", required=True)
    train.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    train.add_argument("--output", type=Path)
    train.add_argument("--dataset", type=Path, help="复用已校验的公开轨迹清单，进行同数据对照")
    train.add_argument(
        "--symbol-augmentation", choices=("none", "per_window_permutation"), default="none"
    )
    diagnostic = commands.add_parser(
        "diagnose-pilot", help="冻结候选检查字节记忆、输入利用与换名敏感性"
    )
    diagnostic.add_argument("--source-report", type=Path, required=True)
    diagnostic.add_argument("--experiment-id", required=True)
    diagnostic.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    diagnostic.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    diagnostic.add_argument("--output", type=Path)
    observation = commands.add_parser(
        "train-observation", help="同参数观察重建对照，通过后才训练动作预测"
    )
    observation.set_defaults(observation_first=True)
    observation.add_argument("--dataset", type=Path, required=True)
    observation.add_argument("--experiment-id", required=True)
    observation.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    observation.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    observation.add_argument("--output", type=Path)
    observation.add_argument("--structure", choices=("paired", "shared_slots"), default="paired")
    observation.add_argument(
        "--initial-checkpoint", type=Path, help="从共享符号重建权重继续巩固，重置优化器但保留随机流"
    )
    comparison = commands.add_parser(
        "train-dynamics", help="同一小模型的变化样本与四步预测三组对照"
    )
    comparison.set_defaults(
        observation_first=True, action_comparison=True, structure="shared_slots"
    )
    comparison.add_argument("--dataset", type=Path, required=True)
    comparison.add_argument("--initial-checkpoint", type=Path, required=True)
    comparison.add_argument("--experiment-id", required=True)
    comparison.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    comparison.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    comparison.add_argument("--output", type=Path)
    comparison.add_argument(
        "--arm",
        dest="comparison_arm",
        default="all",
        choices=("all", "one_step_control", "changed_weighted", "changed_four_step"),
        help="显式重跑一个已声明条件；不自动重试、不沿用失败中间权重",
    )
    history = commands.add_parser("diagnose-history", help="冻结小模型，比较完整、清空和打乱历史")
    history.set_defaults(history_diagnostic=True)
    history.add_argument("--dataset", type=Path, required=True)
    history.add_argument("--checkpoint", type=Path, required=True)
    history.add_argument("--experiment-id", required=True)
    history.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    history.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    history.add_argument("--output", type=Path)
    recall = commands.add_parser(
        "diagnose-recall", help="冻结学生，训练外部读出器诊断短延迟符号记忆"
    )
    recall.set_defaults(recall_diagnostic=True)
    recall.add_argument("--dataset", type=Path, required=True)
    recall.add_argument("--checkpoint", type=Path, required=True)
    recall.add_argument("--experiment-id", required=True)
    recall.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    recall.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    recall.add_argument("--output", type=Path)
    residual = commands.add_parser(
        "diagnose-residual-recall", help="固定当前符号通路，诊断零延迟与残差读出"
    )
    residual.set_defaults(residual_diagnostic=True)
    residual.add_argument("--dataset", type=Path, required=True)
    residual.add_argument("--checkpoint", type=Path, required=True)
    residual.add_argument("--experiment-id", required=True)
    residual.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    residual.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    residual.add_argument("--output", type=Path)
    memory = commands.add_parser("train-memory", help="固定100次更新，仅训练现有GRU保留上一观察")
    memory.set_defaults(memory_training=True)
    memory.add_argument("--dataset", type=Path, required=True)
    memory.add_argument("--checkpoint", type=Path, required=True)
    memory.add_argument("--experiment-id", required=True)
    memory.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    memory.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    memory.add_argument("--output", type=Path)
    micro_memory = commands.add_parser(
        "train-micro-memory", help="固定200次尾部更新，检查单条反馈边的小批次记忆拟合"
    )
    micro_memory.set_defaults(micro_memory_training=True)
    micro_memory.add_argument("--dataset", type=Path, required=True)
    micro_memory.add_argument("--checkpoint", type=Path, required=True)
    micro_memory.add_argument("--experiment-id", required=True)
    micro_memory.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    micro_memory.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    micro_memory.add_argument("--output", type=Path)
    diverse_memory = commands.add_parser(
        "train-diverse-memory", help="固定200次尾部更新，增加一步保留任务的公开训练输入多样性"
    )
    diverse_memory.set_defaults(diverse_memory_training=True)
    for name in ("dataset", "checkpoint", "comparison-report"):
        diverse_memory.add_argument(f"--{name}", type=Path, required=True)
    diverse_memory.add_argument("--experiment-id", required=True)
    diverse_memory.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    diverse_memory.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    diverse_memory.add_argument("--output", type=Path)
    relabel_memory = commands.add_parser(
        "train-relabel-memory",
        help="M2m：在 M2l 设置上仅加入每样本一致换名，固定200次尾部更新并与 M2l 同查询对照",
    )
    relabel_memory.set_defaults(relabel_memory_training=True)
    for name in ("dataset", "checkpoint", "comparison-report", "m2l-report", "m2l-checkpoint"):
        relabel_memory.add_argument(f"--{name}", type=Path, required=True)
    relabel_memory.add_argument("--experiment-id", required=True)
    relabel_memory.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    relabel_memory.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    relabel_memory.add_argument("--output", type=Path)
    interference = commands.add_parser(
        "diagnose-interference", help="冻结三组模型，定位记忆训练对动作预测的干扰"
    )
    interference.set_defaults(interference_diagnostic=True)
    interference.add_argument("--dataset", type=Path, required=True)
    interference.add_argument("--checkpoint", type=Path, required=True)
    interference.add_argument("--candidate-checkpoint", type=Path, required=True)
    interference.add_argument("--experiment-id", required=True)
    interference.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    interference.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    interference.add_argument("--output", type=Path)
    paired_memory = commands.add_parser(
        "diagnose-paired-memory", help="冻结 M2j 模型，配对比较相同经历的零状态与连续历史"
    )
    paired_memory.set_defaults(paired_memory_diagnostic=True)
    for name in ("dataset", "checkpoint", "candidate-checkpoint", "source-report"):
        paired_memory.add_argument(f"--{name}", type=Path, required=True)
    paired_memory.add_argument("--experiment-id", required=True)
    paired_memory.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    paired_memory.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    paired_memory.add_argument("--output", type=Path)
    coverage = commands.add_parser(
        "diagnose-memory-coverage",
        help="冻结 M2l 模型，零更新诊断符号覆盖与单格替换的跨槽干扰",
    )
    coverage.set_defaults(coverage_diagnostic=True)
    for name in ("dataset", "checkpoint", "candidate-checkpoint", "source-report"):
        coverage.add_argument(f"--{name}", type=Path, required=True)
    coverage.add_argument("--experiment-id", required=True)
    coverage.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    coverage.add_argument("--output-dir", type=Path, default=Path("artifacts/pilot"))
    coverage.add_argument("--output", type=Path)
    train.add_argument("--seed", type=int, choices=[0, 1, 2], default=0)
    train.add_argument("--updates", type=int, choices=range(1, 101), default=100, metavar="1..100")
    train.add_argument(
        "--train-episodes", type=int, choices=range(1, 33), default=16, metavar="1..32"
    )
    train.add_argument(
        "--development-episodes", type=int, choices=range(1, 9), default=4, metavar="1..8"
    )
    collect = commands.add_parser("collect-c0", help="有限步数采集 C0 随机交互，不训练")
    collect.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    collect.add_argument("--experiment-id", required=True)
    collect.add_argument("--output-dir", type=Path, default=Path("artifacts/c0"))
    collect.add_argument("--seed", type=int, default=0)
    collect.add_argument("--steps", type=int, choices=range(1, 129), default=64, metavar="1..128")
    collect.add_argument("--partition", choices=["train", "development"], default="train")
    replay = commands.add_parser("replay-c0", help="重放 C0 轨迹并计入原实验预算")
    replay.add_argument("trajectory", type=Path)
    replay.add_argument("--config", type=Path, default=Path("configs/pilot.yaml"))
    replay.add_argument("--output", type=Path)
    doctor = commands.add_parser("doctor", help="读取硬件和 MLX 就绪状态，不训练")
    doctor.add_argument("--output", type=Path)
    doctor.add_argument("--no-mlx", action="store_true", help="跳过原生后端探测")
    doctor.add_argument("--require-gpu", action="store_true", help="GPU 未就绪时返回失败")
    smoke = commands.add_parser("smoke", help="有限步数的微型网络训练与保存恢复检查")
    smoke.add_argument("--config", type=Path, default=Path("configs/brain0.yaml"))
    smoke.add_argument("--output-dir", type=Path, default=Path("artifacts/m0"))
    smoke.add_argument("--device", choices=["cpu", "gpu"], default="gpu")
    smoke.add_argument("--steps", type=int, choices=range(8, 129), default=64, metavar="8..128")
    args = parser.parse_args(argv)
    try:
        if args.command in {
            "train-pilot",
            "diagnose-pilot",
            "train-observation",
            "train-dynamics",
            "diagnose-history",
            "diagnose-recall",
            "diagnose-residual-recall",
            "train-memory",
            "train-micro-memory",
            "train-diverse-memory",
            "train-relabel-memory",
            "diagnose-interference",
            "diagnose-paired-memory",
            "diagnose-memory-coverage",
        }:
            report = train_pilot_command(args)
            if args.output:
                atomic_write_json(args.output, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report.get("status") == "completed" else 1
        if args.command in {"collect-c0", "replay-c0"}:
            from ainerzero.runtime.c0_collection import (
                collect_c0,
                collection_manifest,
                replay_c0,
            )

            config = load_pilot_config(args.config)
            data_dir = project_root(args.config) / config.storage.data_dir
            if args.command == "collect-c0" and not 0 <= args.seed < 2**64:
                raise ValueError("seed must be in [0, 2**64)")
            with worker_lock(data_dir / "locks" / "m0-worker.lock"):
                with RunStore(data_dir / "control.sqlite3") as store:
                    if args.command == "collect-c0":
                        declaration = collection_manifest(pilot_manifest(args.config)["manifest"])
                        experiment = store.create_experiment(
                            declaration,
                            f"c0:{args.experiment_id}",
                            experiment_id=args.experiment_id,
                        )
                        report = collect_c0(
                            store,
                            experiment.experiment_id,
                            seed=args.seed,
                            partition=args.partition,
                            steps=args.steps,
                            output_root=args.output_dir,
                        )
                    else:
                        report = replay_c0(store, args.trajectory)
                        if args.output:
                            atomic_write_json(args.output, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.command == "check-pilot":
            report = pilot_manifest(args.config)
            if args.output:
                atomic_write_json(args.output, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.command == "check-config":
            config = load_config(args.config)
            print(
                json.dumps(
                    {
                        "status": "valid",
                        "config_hash": config_hash(config),
                        "config": config.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "doctor":
            if args.no_mlx and args.require_gpu:
                raise ValueError("--require-gpu cannot be combined with --no-mlx")
            report = collect_hardware(include_mlx=not args.no_mlx)
            if args.output:
                atomic_write_json(args.output, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1 if args.require_gpu and not report["backend"]["available"] else 0
        config = load_config(args.config)
        data_dir = project_root(args.config) / config.storage.data_dir
        control_db = (data_dir / "control.sqlite3").resolve()
        with worker_lock(data_dir / "locks" / "m0-worker.lock"):
            # Only the exclusive supervisor may recover interrupted lifecycle
            # state. Recovery pauses prior work; it never dispatches it again.
            with RunStore(control_db) as store:
                store.recover_interrupted_runs()
                prior_runs = {run.run_id for run in store.list_runs()}
            unfinished_runs = []
            exit_reason = "worker_exited_without_terminal_state"
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "ainerzero.runtime.smoke_worker",
                        "--config",
                        str(args.config.resolve()),
                        "--output-dir",
                        str(args.output_dir.resolve()),
                        "--device",
                        args.device,
                        "--steps",
                        str(args.steps),
                        "--control-db",
                        str(control_db),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=min(120.0, config.budget.max_wall_seconds),
                )
            except subprocess.TimeoutExpired:
                exit_reason = "worker_timeout"
                raise
            except BaseException:
                exit_reason = "worker_interrupted"
                raise
            finally:
                # subprocess.run has reaped the worker before this cleanup.
                # Keep the exclusive lock until newly orphaned state is durable;
                # leave earlier paused runs and completed work untouched.
                with RunStore(control_db) as store:
                    for run in store.list_runs():
                        if run.run_id not in prior_runs and run.state not in TERMINAL_STATES:
                            store.transition(run.run_id, "failed", reason=exit_reason)
                            unfinished_runs.append(run.run_id)
        lines = result.stdout.strip().splitlines()
        try:
            report = json.loads(lines[-1]) if lines else None
        except json.JSONDecodeError:
            report = None
        if not isinstance(report, dict):
            report = {
                "status": "failed",
                "error": "Native worker ended without a valid report",
                "worker_exit_code": result.returncode,
            }
        if unfinished_runs:
            report.update(
                status="failed",
                error="Worker exited with unfinished runs; supervisor marked them failed",
                interrupted_run_ids=unfinished_runs,
            )
        if result.returncode != 0:
            report["status"] = "failed"
            report["worker_exit_code"] = result.returncode
            report.setdefault("error", "Native worker exited unsuccessfully")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if result.returncode == 0 and report.get("status") == "passed" else 1
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        sqlite3.Error,
        subprocess.SubprocessError,
    ) as exc:
        print(
            json.dumps(
                {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
