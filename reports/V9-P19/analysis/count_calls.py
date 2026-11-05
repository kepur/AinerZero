"""Isolated CPU harness for ainerzero.V9.P18 (k-support coverage + eval call counting).

Reads the frozen r5 source snapshot and the frozen development dataset read-only.
Imports no MLX: ``runtime.MlxBackend`` only imports mlx inside methods, and every
such method is overridden here by a counting substitute.  No model, no training,
no forward pass of a real network, no final partition.

Writes nothing except the JSON/JSONL under reports/V9-P18/.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

SNAP = Path(
    "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot"
)
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
DATASET = (
    REPO
    / "artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
)
ISO = Path("/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/v9p19/iso")
OUT = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-P19")


def build_iso() -> Path:
    """Byte copy of the snapshot s1 package plus the repo non-MLX helper package.

    Copies (never symlinks) into /tmp so the isolated import tree cannot touch
    the repository and cannot be mutated by the parallel r6 work.
    """
    if ISO.exists():
        shutil.rmtree(ISO)
    pkg = ISO / "ainerzero"
    (pkg / "v9" / "experiments").mkdir(parents=True)
    for path in (pkg / "__init__.py", pkg / "v9" / "__init__.py", pkg / "v9" / "experiments" / "__init__.py"):
        path.write_text("")
    shutil.copytree(
        SNAP / "src/ainerzero/v9/experiments/s1",
        pkg / "v9" / "experiments" / "s1",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(
        REPO / "src/ainerzero/v9/interfaces",
        pkg / "v9" / "interfaces",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return ISO


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Counters(dict):
    def bump(self, name: str, n: int = 1) -> None:
        self[name] = int(self.get(name, 0)) + int(n)


class _Out:
    __slots__ = ("loss", "pose_belief", "predictions", "metrics")

    def __init__(self, loss, pose, predictions, metrics):
        self.loss = loss
        self.pose_belief = pose
        self.predictions = predictions
        self.metrics = metrics


class FakeModel:
    """Deterministic placeholder network: counts work, produces no capability."""

    def __init__(self, counters: Counters):
        self.c = counters
        self.dim = 8

    def forward_loss(self, batch):
        obs = batch["obs"]
        b = obs.shape[0]
        self.c.bump("forward_loss_calls")
        self.c.bump("forward_loss_frames", int(b * obs.shape[1]))
        pose = obs[:, -1, :4].astype("float64") if obs.shape[-1] >= 4 else obs[:, -1, :1].repeat(4, 1)
        metrics = {"presence": 0.5, "class": 0.5, "position": 0.25}
        return _Out(float(1.0), pose, None, metrics)

    def forward_terms(self, batch, burn_in=0, memory=None, pose=None):
        obs = batch["obs"]
        self.c.bump("single_step_forward_calls")
        self.c.bump("single_step_forward_frames", 1)
        memory = {} if memory is None else memory
        cells = memory.setdefault("cells", [])
        key = (round(float(obs[0, -1, 0]), 3), round(float(obs[0, -1, 2]), 3)) if obs.shape[-1] > 2 else (0.0, 0.0)
        if not cells or cells[-1] != key:
            cells.append(key)
        parts = {"presence": 0.5, "class": 0.5, "position": 0.25}
        return float(1.0), parts, pose, None, memory

    def encode(self, arr):
        self.c.bump("encode_calls")
        flat = arr.reshape(-1).astype("float64")
        vec = flat[: self.dim]
        norm = float((vec * vec).sum() ** 0.5) or 1.0
        return (vec / norm).reshape(1, -1)


class CountingBackend:
    """Same public surface as runtime.MlxBackend, numeric work counted, no MLX."""

    name = "cpu-counting-substitute"

    def __init__(self):
        self.c = Counters()
        self.model = FakeModel(self.c)

    # -- model lifecycle ---------------------------------------------------
    def build_model(self, arm_id, seed=0):
        self.c.bump("build_model_calls")
        return self.model

    def load_params(self, model, path):
        self.c.bump("load_params_calls")

    def parameter_sha256(self, model):
        return "0" * 64

    def eval(self, *values):
        self.c.bump("eval_calls")

    # -- development window probe (mirrors runtime.MlxBackend.window_probe) --
    def window_probe(self, model, windows, protocol, *, max_batches=None):
        from ainerzero.v9.experiments.s1 import data, spec

        batch_size = int(protocol["batch_size"])
        count = len(windows.get("obs", []))
        if count < 1:
            raise RuntimeError("development window probe has no windows")
        batch_count = (count + batch_size - 1) // batch_size
        limit = int(protocol.get("eval_batches", spec.TIMING["eval_batches"]))
        if max_batches is not None:
            limit = min(limit, int(max_batches))
        batch_count = min(batch_count, max(limit, 1))
        rows = []
        for batch_index in range(batch_count):
            start_index = batch_index * batch_size
            indices = list(range(start_index, min(start_index + batch_size, count)))
            if not indices:
                continue
            batch = data.sample_batch(windows, indices)
            output = model.forward_loss(batch)
            self.eval(output.loss)
            pose = output.pose_belief
            for offset, window_index in enumerate(indices):
                meta = windows["windows"][int(window_index)]
                rows.append(
                    {
                        "window_index": int(window_index),
                        "episode_id": meta["episode_id"],
                        "start": int(meta["start"]),
                        "loss": 1.0,
                        "parts": dict(output.metrics),
                        "pose": pose[offset],
                    }
                )
        return {"rows": rows, "batches": batch_count, "windows": len(rows)}

    # -- bounded sequence --------------------------------------------------
    def step_sequence(self, model, sequence, *, stop=None, memory=None, pose=None):
        import numpy as np
        from ainerzero.v9.experiments.s1 import data

        self.c.bump("step_sequence_calls")
        frames = len(sequence["obs"]) if stop is None else int(stop)
        if frames < 2:
            raise RuntimeError("a sequence probe needs at least two frames")
        self.c.bump("step_sequence_frames", frames)
        steps = []
        current_memory = memory
        current_pose = np.zeros((1, 4), dtype="float32") if pose is None else np.asarray(pose, dtype="float32").reshape((1, 4))
        for t in range(frames - 1):
            batch = data.sequence_batch(sequence, t, t + 2)
            loss, parts, current_pose, predictions, current_memory = model.forward_terms(
                batch, burn_in=0, memory=current_memory, pose=current_pose
            )
            self.eval(loss)
            steps.append({"frame": t + 1, "loss": loss, "pose": np.asarray(current_pose)[0].copy(), "parts": parts})
        return {"steps": steps, "memory": current_memory, "pose": np.asarray(current_pose)}

    def probe_graph(self, model, memory, pose=None):
        import numpy as np

        self.c.bump("probe_graph_calls")
        if not memory or not memory.get("cells"):
            return {"nodes": np.zeros((0, 8)), "positions": np.zeros((0, 2)), "edges": set(), "threshold": 0.0}
        cells = list(memory["cells"])
        nodes = np.zeros((len(cells), 8))
        for i in range(len(cells)):
            nodes[i, i % 8] = 1.0
        positions = np.asarray(cells, dtype="float64")
        edges = {(i, i + 1) for i in range(len(cells) - 1)}
        return {"nodes": nodes, "positions": positions, "edges": edges, "threshold": 0.0}

    def encode(self, model, obs_row):
        return model.encode(obs_row)

    def save_params(self, model, path, *, exclusive=False):
        raise RuntimeError("the counting substitute never writes checkpoints")


def main() -> int:
    build_iso()
    sys.path.insert(0, str(ISO))
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    assert "mlx" not in sys.modules, "MLX must not be imported"

    from ainerzero.v9.experiments.s1 import data, evaluation, metrics, spec

    identity = {
        "snapshot_root": str(SNAP),
        "dataset_dir": str(DATASET),
        "source_sha256": {
            rel: sha256_file(SNAP / "src/ainerzero/v9/experiments/s1" / rel)
            for rel in (
                "data.py",
                "evaluation.py",
                "metrics.py",
                "runtime.py",
                "spec.py",
                "worker.py",
                "prereg.py",
                "commands.py",
            )
        },
        "prereg_file_sha256": sha256_file(SNAP / "artifacts/v9/s1/phase1/r5/pre_registration.json"),
        "dataset_files_sha256": {
            rel: sha256_file(DATASET / rel)
            for rel in (
                "dataset_manifest.json",
                "packets/development.jsonl",
                "truth/development.jsonl",
            )
        },
        "mlx_imported": "mlx" in sys.modules,
    }

    document = json.loads((SNAP / "artifacts/v9/s1/phase1/r5/pre_registration.json").read_text())
    protocol = document["training_protocol"]

    truth_view = data.load_truth_view(DATASET, "development")
    episodes = data.load_training_episodes(DATASET, "development")
    windows = data.load_development_windows(DATASET)
    sequences = [data.build_episode_sequence(ep) for ep in episodes]

    # ---- 1. structural statistics over the real development partition ----
    per_world = []
    for ep in truth_view:
        transitions = max(len(ep.steps) - 1, 0)
        row = {
            "episode_id": ep.episode_id,
            "family": ep.family or "unknown",
            "steps": len(ep.steps),
            "transitions": transitions,
        }
        per_world.append(row)

    k_values = (0, 1, 2, 4, 8)
    coverage = {}
    for k in k_values:
        worlds = 0
        queries = 0
        by_family = {}
        ceilings = []
        for ep in truth_view:
            transitions = max(len(ep.steps) - 1, 0)
            support, query = metrics.split_support_query(transitions, k)
            if not query:
                continue
            worlds += 1
            queries += len(query)
            fam = ep.family or "unknown"
            slot = by_family.setdefault(fam, {"worlds": 0, "queries": 0})
            slot["worlds"] += 1
            slot["queries"] += len(query)
            cells = evaluation.relative_cell_path(ep)
            support_cells = set(cells[: len(support) + 1]) if support else set()
            reachable = sum(1 for i in query if cells[i + 1] in support_cells)
            ceilings.append((reachable, len(query)))
        coverage[str(k)] = {
            "worlds": worlds,
            "queries": queries,
            "by_family": dict(sorted(by_family.items())),
            "query_transitions_reachable_in_support_memory": sum(c[0] for c in ceilings),
            "reachable_fraction": (
                round(sum(c[0] for c in ceilings) / sum(c[1] for c in ceilings), 6) if ceilings else None
            ),
        }

    family_length = {}
    for row in per_world:
        family_length.setdefault(row["family"], {}).setdefault(row["steps"], 0)
        family_length[row["family"]][row["steps"]] += 1

    # ---- 2. call accounting for one post-hoc arm x seed evaluation -------
    backend = CountingBackend()
    model = backend.build_model("arm4", seed=0)

    final_probe = backend.window_probe(model, windows, protocol)
    final_rows = evaluation.development_rows(final_probe, truth_view)
    localization = evaluation.localization_report(final_rows)

    sample_rows = []
    checkpoint_updates = list(protocol["checkpoint_updates"])
    for update in sorted(checkpoint_updates):
        if update == int(protocol["updates"]):
            probe, rows = final_probe, final_rows
        else:
            probe = backend.window_probe(model, windows, protocol)
            rows = evaluation.development_rows(probe, truth_view)
        unseen = metrics.strict_unseen_map(rows)
        sample_rows.append(
            {
                "updates": int(update),
                "development_nll": float(sum(r["prediction_nll"] for r in rows) / len(rows)),
                "localization_translation_mean_m": float(unseen["translation_mean_m"]),
                "nll_samples": len(rows),
                "localization_samples": int(unseen["episodes"]),
            }
        )

    topology = evaluation.topology_report(backend, model, sequences, truth_view)
    few_shot_error = None
    try:
        few_shot = evaluation.few_shot_report(backend, model, sequences, truth_view)
    except Exception as exc:  # the frozen k=1 point raises BackendError; record it
        few_shot = None
        few_shot_error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "point": "evaluation.few_shot_report k=1 (support=[0] -> step_sequence(stop=1) -> frames=1 < 2)",
        }
    per_k_calls = {}
    for k in k_values:
        sub = Counters()
        probe_backend = CountingBackend()
        probe_backend.c = sub
        probe_backend.model.c = sub
        pmodel = probe_backend.model
        crashed = None
        worlds = 0
        queries = 0
        for sequence in sequences:
            episode = truth_view[[ep.episode_id for ep in truth_view].index(sequence["episode_id"])]
            transitions = max(len(episode.steps) - 1, 0)
            support, query = metrics.split_support_query(transitions, int(k))
            if not query:
                continue
            try:
                memory = None
                if support:
                    run = probe_backend.step_sequence(pmodel, sequence, stop=support[-1] + 1)
                    memory = run["memory"]
                probe_backend.probe_graph(pmodel, memory)
                for index in query:
                    probe_backend.encode(pmodel, sequence["obs"][index])
                    probe_backend.encode(pmodel, sequence["obs"][index + 1])
            except Exception as exc:
                crashed = f"{type(exc).__name__}: {exc}"
                break
            worlds += 1
            queries += len(query)
        per_k_calls[str(k)] = {
            "worlds_reached": worlds,
            "queries_reached": queries,
            "crashed_at_world": worlds + 1 if crashed else None,
            "error": crashed,
            "calls": dict(sub),
        }
    interference = evaluation.m2_interference(
        backend, model, sequences[:3], truth_view, sequences[3], sequences[4]
    )
    sample_efficiency = evaluation.sample_efficiency(sample_rows)
    suite = None
    if few_shot is not None:
        suite = metrics.metric_suite_report(
            localization=localization,
            unseen=localization["unseen"],
            topology=topology,
            few_shot=few_shot,
            sample_efficiency=sample_efficiency,
            interference=interference,
            arm_id="arm4",
            seed=0,
        )

    few_shot_shape = {
        str(k): {
            "status": (
                "scored"
                if few_shot is not None and str(k) in few_shot["curve"]
                else (
                    (few_shot["unavailable"].get(str(k), {}) or {}).get("status")
                    if few_shot is not None
                    else "not_reached: the frozen k=1 point raised before this k"
                )
            ),
            "worlds": (
                (few_shot["curve"].get(str(k), {}) or few_shot["unavailable"].get(str(k), {}) or {}).get("worlds")
                if few_shot is not None
                else None
            ),
            "queries": (
                few_shot["curve"].get(str(k), {}).get("queries") if few_shot is not None else None
            ),
        }
        for k in k_values
    }

    payload = {
        "schema": "ainerzero.v9.p18.cpu-coverage.v1",
        "task": "ainerzero.V9.P18",
        "executor": "deepseek-p18a",
        "identity": identity,
        "dataset": {
            "development_worlds": len(truth_view),
            "development_episodes": len(episodes),
            "development_packets": sum(len(ep.payloads) for ep in episodes),
            "development_steps": sum(len(ep.steps) for ep in truth_view),
            "development_windows": len(windows["windows"]),
            "window_batch_size": int(protocol["batch_size"]),
            "window_batches": (len(windows["windows"]) + int(protocol["batch_size"]) - 1) // int(protocol["batch_size"]),
            "eval_batches_registered": int(protocol["eval_batches"]),
            "transitions_histogram": {},
            "family_steps": family_length,
            "rounds_per_world": sorted({row.get("round_index") for row in [{"round_index": ep.partition} for ep in []]} or [0]),
        },
        "k_coverage": coverage,
        "few_shot_report_shape_from_real_data": few_shot_shape,
        "few_shot_frozen_path_error": few_shot_error,
        "few_shot_per_k_call_counts": per_k_calls,
        "eval_calls_one_arm_seed": dict(backend.c),
        "eval_suite_status": {
            "localization": localization["status"],
            "loop_closure": localization["loop_closure"]["status"],
            "topology_rows": topology.get("episodes"),
            "interference": interference.get("status"),
        },
        "note": "accuracy/NLL values produced here come from a counting substitute backend; they are "
        "call-count instrumentation only and are NOT a capability or scientific result.",
    }
    hist = {}
    for row in per_world:
        hist[str(row["transitions"])] = hist.get(str(row["transitions"]), 0) + 1
    payload["dataset"]["transitions_histogram"] = dict(sorted(hist.items(), key=lambda kv: int(kv[0])))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "analysis" / "cpu_coverage.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    (OUT / "analysis" / "per_world.json").write_text(json.dumps(per_world, indent=1, ensure_ascii=False))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
