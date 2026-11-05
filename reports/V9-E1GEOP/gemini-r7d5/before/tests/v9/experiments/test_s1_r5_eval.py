"""r5 eval orchestration with a controlled CPU backend (no MLX).

A real RunStore run + receipt is bound to a real synthetic dataset, and the
production `_evaluate_arm` path computes all six frozen metric groups from that
binding.  The backend is a test substitute; this is engineering evidence, not a
capability result.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from ainerzero.runtime.lifecycle import RunStore
from ainerzero.v9.experiments.s1 import data, spec, worker


class _Model:
    def __init__(self, seed: int):
        self.params = {"w": np.asarray([float(seed)], dtype=np.float32)}


class _EvalBackend:
    name = "cpu-test-substitute-eval"

    def __init__(self):
        self.optimizer_steps = 0
        self.graph_calls = 0

    def build_model(self, arm_id, seed):
        return _Model(seed)

    def make_optimizer(self, protocol):
        return {}

    def init_optimizer(self, optimizer, model):
        return None

    def value_and_grad(self, model):
        def apply(m, batch):
            self.optimizer_steps += 1
            m.params["w"] = np.asarray(m.params["w"], dtype=np.float32) + 1.0
            return (np.float32(1.0), {}), {"w": np.zeros(1, dtype=np.float32)}

        return apply

    def eval(self, *values):
        return None

    def clip_grad_norm(self, grads, norm):
        return grads, 1.0

    def optimizer_update(self, optimizer, model, grads):
        return None

    def sync_parameters(self, model, optimizer):
        return None

    def loss_value(self, loss):
        return float(loss)

    def parameter_sha256(self, model):
        digest = hashlib.sha256()
        for name in sorted(model.params):
            digest.update(name.encode())
            digest.update(np.ascontiguousarray(model.params[name]).tobytes())
        return digest.hexdigest()

    def save_params(self, model, path, *, exclusive=False):
        if exclusive and path.exists():
            raise FileExistsError(path)
        with open(path, "xb" if exclusive else "wb") as handle:
            np.savez(handle, **model.params)

    def load_params(self, model, path):
        with np.load(path) as loaded:
            model.params = {name: np.asarray(loaded[name]) for name in loaded.files}

    def window_probe(self, model, windows, protocol, *, max_batches=None):
        rows = []
        for meta in windows["windows"]:
            rows.append(
                {
                    "episode_id": meta["episode_id"],
                    "start": int(meta["start"]),
                    "loss": 0.5,
                    "parts": {"presence": 0.2, "class": 0.3, "position": 0.1},
                    "pose": np.zeros(4),
                    "prediction": None,
                }
            )
        return {"rows": rows, "batches": 1, "windows": len(rows)}

    def _graph(self, sequence, memory, frames):
        self.graph_calls += 1
        if memory is None:
            nodes = []
            edges = set()
        else:
            nodes = list(memory["nodes"])
            edges = set(memory["edges"])
        start = len(nodes)
        for index in range(frames):
            nodes.append(np.asarray(sequence["obs"][index], dtype=np.float32))
            if len(nodes) > 1 and index + start > 0:
                edges.add((len(nodes) - 2, len(nodes) - 1))
        return {
            "nodes": np.stack(nodes) if nodes else np.zeros((0, 1), dtype=np.float32),
            "positions": np.zeros((len(nodes), 2)),
            "edges": edges,
            "threshold": 0.0,
        }

    def step_sequence(self, model, sequence, *, stop=None, memory=None, pose=None):
        frames = len(sequence["obs"]) if stop is None else int(stop)
        graph = self._graph(sequence, memory, frames)
        steps = []
        for index in range(frames - 1):
            steps.append(
                {
                    "frame": index + 1,
                    "loss": 0.5,
                    "pose": np.zeros(4),
                    "predictions": None,
                    "parts": {"presence": 0.2, "class": 0.3},
                }
            )
        return {"steps": steps, "memory": graph, "pose": np.zeros((1, 4))}

    def probe_graph(self, model, memory, pose=None):
        if memory is None:
            return {
                "nodes": np.zeros((0, 1)),
                "positions": np.zeros((0, 2)),
                "edges": set(),
                "threshold": 0.0,
            }
        return memory

    def encode(self, model, obs_row):
        return np.asarray(obs_row, dtype=np.float32)

    # r15 (ainerzero.V9.P53): few-shot queries through probe_query; this fake's
    # encoding already lives in its node space, so the query is the encoding.
    def probe_query(self, model, obs_row):
        return self.encode(model, obs_row)


def _document(manifest, *, updates=2):
    return {
        "training_protocol": {
            "updates": updates,
            "batch_size": 16,
            "sequence_steps": 2,
            "learning_rate": 3e-4,
            "adam_betas": [0.9, 0.999],
            "adam_epsilon": 1e-8,
            "weight_decay": 0.01,
            "gradient_clip_norm": 1.0,
            "checkpoint_updates": [0, updates],
        },
        "timing": {"deadline_seconds": 450.0},
        "resource_limits": dict(spec.RESOURCE_LIMITS),
        "data_identity": {"dataset_digest": manifest["dataset_digest"]},
        "evaluation": {
            "query_limit": int(spec.EVALUATION["query_limit"]),
            "reporting_notes": list(spec.EVALUATION["reporting_notes"]),
        },
    }


@pytest.fixture
def cuda_free_run(tmp_path, monkeypatch):
    from s1_testkit import make_plan, write_staging

    plan = make_plan(train_worlds=8, development_worlds=8, rounds=1)
    staging = tmp_path / "staging"
    write_staging(staging, plan=plan, steps_per_world=8)
    staged = tmp_path / "dataset-staged"
    manifest = data.finalize_dataset(
        staging,
        staged,
        plan=plan,
        generation_seconds=1.0,
        generation_command=["synthetic-producer"],
    )
    dataset_dir = tmp_path / manifest["dataset_digest"]
    staged.rename(dataset_dir)
    root = tmp_path / "phase1"
    root.mkdir(exist_ok=True)
    data.write_dataset_ref(root, manifest, dataset_dir)
    # r6: run binding resolves the central ledger through the canonical root.
    monkeypatch.setattr(worker, "canonical_ledger_path", lambda: root / "control.sqlite3")
    monkeypatch.setattr(
        worker.resource_gate,
        "RuntimeGuard",
        lambda *args, **kwargs: type("G", (), {"sample": lambda self, **k: {}})(),
    )
    document = _document(manifest)
    ledger = worker.PrepLedger(root / "control.sqlite3")
    run_id = worker._open_train_run(
        document,
        ledger,
        {"document_sha256": "a" * 64},
        arm_id="arm2",
        seed=0,
    )
    ledger.begin_work(run_id, work_state="training")
    details = worker._train(
        document,
        root,
        ledger,
        run_id,
        type("G", (), {"sample": lambda self, **k: {}})(),
        arm_id="arm2",
        seed=0,
        prereg_sha256="a" * 64,
        backend=_EvalBackend(),
    )
    receipt = details["receipt"]
    ledger.finish(
        run_id,
        "completed",
        worker.TRAIN_RECEIPT_PREFIX + json.dumps(receipt, sort_keys=True, separators=(",", ":")),
    )
    ledger.close()
    return root, document, run_id


def test_evaluate_arm_binds_run_and_computes_all_six_groups(cuda_free_run):
    root, document, run_id = cuda_free_run
    backend = _EvalBackend()
    result = worker._evaluate_arm(
        document,
        root,
        arm_id="arm2",
        seed=0,
        prereg_sha256="a" * 64,
        backend=backend,
    )
    assert result["status"] == "completed"
    assert result["run_binding"]["status"] == "passed"
    assert result["run_binding"]["run_id"] == run_id
    assert result["run_binding"]["final_checkpoint_sha256"] == result["checkpoint_sha256"]
    assert result["run_binding"]["run_info_used_for_binding"] is False
    assert set(
        [
            "localization_error",
            "unseen_map_generalization",
            "topology_recovery",
            "few_shot_unseen_transition",
            "sample_efficiency",
            "m2_memory_interference",
        ]
    ).issubset(result)
    # Every development world is covered; the old min-length truncation lost rows.
    truth_view = data.load_truth_view(data.resolve_dataset_dir(root), "development")
    expected_worlds = len({episode.episode_id for episode in truth_view})
    assert expected_worlds == 8
    assert result["unseen_map_generalization"]["episodes"] == expected_worlds
    assert result["unseen_map_generalization"]["worlds"] == expected_worlds
    assert [row["updates"] for row in result["sample_efficiency"]["checkpoints"]] == [0, 2]
    assert result["m2_memory_interference"]["zero_state"]
    assert result["m2_memory_interference"]["after_new_world"]
    assert backend.optimizer_steps == 0

    with RunStore(root / "control.sqlite3") as store:
        run = store.get_run(run_id)
        assert run.state == "completed"
        assert run.reserved_optimizer_steps == 2


def test_arm_eval_import_graph_does_not_import_mlx():
    """CPU-only guarantee: the arm2/3/4 eval import graph stays MLX-free.

    Run in a fresh interpreter because other test modules in the same session
    import the frozen D-candidate module, which imports MLX at module level.
    """
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    code = (
        "import sys; import ainerzero.v9.experiments.s1.worker as w; "
        "import ainerzero.v9.experiments.s1.evaluation, ainerzero.v9.experiments.s1.runtime; "
        "bad = sorted(n for n in sys.modules if n.split('.')[0] == 'mlx'); "
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], cwd=repo, check=True)
