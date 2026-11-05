"""Independent (non-author) checks for ainerzero.V9.P18 -- task ainerzero.V9.P19.

Read-only with respect to every reviewed artefact:
  * the frozen r5 source snapshot is never modified (it is byte-copied into two
    throw-away trees under a private temp root; one of them carries a 1-line
    repair to ``evaluation.py`` so that the "repaired" call counts can be
    MEASURED instead of extrapolated);
  * the P18 report/scripts are never modified; the P18 scripts are only re-run
    from copies (see ``scaffold_diff.txt``);
  * no MLX import, no model, no training, no evaluation of a real checkpoint,
    no writes outside reports/V9-P19/.

Sections
  A  real-runtime-method checks (the frozen ``runtime.MlxBackend.step_sequence``
     itself, with only the MLX-touching ``eval`` overridden by a stub)
  B  as-coded call accounting on the pristine tree (must match P18 exactly)
  C  repaired call accounting on the repaired tree (measured, not extrapolated)
  D  reconstruction of the 1503 / 1703 / 1903 / 2103 "frames" numbers
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np

SNAP = Path(
    "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot"
)
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
DATASET = (
    REPO
    / "artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
)
BASE = Path(
    "/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/v9p19"
)
TREE_PRISTINE = BASE / "iso_check_pristine"
TREE_REPAIRED = BASE / "iso_check_repaired"
OUT = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-P19")

K_VALUES = (0, 1, 2, 4, 8)
REPAIR_OLD = "run = backend.step_sequence(model, sequence, stop=support[-1] + 1)"
REPAIR_NEW = "run = backend.step_sequence(model, sequence, stop=support[-1] + 2)"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_tree(target: Path, repair: bool) -> dict:
    """Byte-copy the frozen s1 package into a throw-away tree (optionally with
    the one-line evaluation.py repair).  The frozen snapshot is never touched."""
    if target.exists():
        shutil.rmtree(target)
    pkg = target / "ainerzero"
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
    info = {"tree": str(target), "repaired": repair, "patched_file": None}
    if repair:
        target_file = pkg / "v9" / "experiments" / "s1" / "evaluation.py"
        text = target_file.read_text()
        assert text.count(REPAIR_OLD) == 1, "repair anchor is not unique"
        target_file.write_text(text.replace(REPAIR_OLD, REPAIR_NEW))
        info["patched_file"] = str(target_file)
        info["patched_sha256"] = sha256_file(target_file)
        info["pristine_sha256"] = sha256_file(SNAP / "src/ainerzero/v9/experiments/s1" / "evaluation.py")
    return info


# --------------------------------------------------------------------------- #
# counting substitute: same public surface as runtime.MlxBackend, numpy only
# --------------------------------------------------------------------------- #
class Counters(dict):
    def bump(self, name: str, n: int = 1) -> None:
        self[name] = int(self.get(name, 0)) + int(n)


class _Out:
    def __init__(self, loss, pose, predictions, metrics):
        self.loss = loss
        self.pose_belief = pose
        self.predictions = predictions
        self.metrics = metrics


class FakeModel:
    def __init__(self, counters: Counters):
        self.c = counters
        self.dim = 8

    def forward_loss(self, batch):
        obs = batch["obs"]
        b = obs.shape[0]
        self.c.bump("forward_loss_calls")
        self.c.bump("forward_loss_frames", int(b * obs.shape[1]))
        pose = obs[:, -1, :4].astype("float64") if obs.shape[-1] >= 4 else obs[:, -1, :1].repeat(4, 1)
        return _Out(float(1.0), pose, None, {"presence": 0.5, "class": 0.5, "position": 0.25})

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
        # REVIEWER INSTRUMENT FIX (documented in the report).  Two deviations
        # of the P18 substitute are repaired here, because both make the
        # production ``evaluation.few_shot_report`` unrunnable as soon as a
        # non-empty memory graph exists:
        #   (1) width: the P18 substitute returns a vector as long as the
        #       observation row; the production MlxBackend.encode returns a
        #       fixed-width model embedding -> pad to a fixed width;
        #   (2) rank: the P18 substitute returns shape (1, dim); the production
        #       ``runtime.MlxBackend.encode`` returns ``np.asarray(...)[0]``,
        #       i.e. shape (dim,) -> return 1-D so that
        #       ``evaluation._cosine_match`` (nodes @ query) is legal.
        # Neither fix changes any call count.
        self.c.bump("encode_calls")
        flat = arr.reshape(-1).astype("float64")
        vec = np.zeros(self.dim, dtype="float64")
        take = min(self.dim, flat.size)
        vec[:take] = flat[:take]
        norm = float((vec * vec).sum() ** 0.5) or 1.0
        return vec / norm


class CountingBackend:
    """Numeric substitute.  Counts every call the production suite makes."""

    name = "cpu-counting-substitute"

    def __init__(self):
        self.c = Counters()
        self.model = FakeModel(self.c)

    def build_model(self, arm_id, seed=0):
        self.c.bump("build_model_calls")
        return self.model

    def load_params(self, model, path):
        self.c.bump("load_params_calls")

    def parameter_sha256(self, model):
        return "0" * 64

    def eval(self, *values):
        self.c.bump("eval_calls")

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

    def step_sequence(self, model, sequence, *, stop=None, memory=None, pose=None):
        from ainerzero.v9.experiments.s1 import data

        self.c.bump("step_sequence_calls")
        frames = len(sequence["obs"]) if stop is None else int(stop)
        if frames < 2:
            raise RuntimeError("a sequence probe needs at least two frames")
        self.c.bump("step_sequence_frames", frames)
        self.c.bump("step_sequence_transitions", frames - 1)
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


# --------------------------------------------------------------------------- #
# A. checks against the REAL frozen runtime method
# --------------------------------------------------------------------------- #
def real_runtime_checks(tree: Path) -> dict:
    """Use the frozen ``runtime.MlxBackend.step_sequence`` itself.

    Only the MLX-touching ``eval`` is overridden (a stub that records the
    call); the guard, the frame arithmetic and the loop bound are the
    production code, byte-for-byte.
    """
    sys.path.insert(0, str(tree))
    for name in [n for n in list(sys.modules) if n.startswith("ainerzero")]:
        del sys.modules[name]
    from ainerzero.v9.experiments.s1 import data, evaluation, metrics, runtime

    assert "mlx" not in sys.modules, "MLX must not be imported"

    class RealBackendNoEval(runtime.MlxBackend):
        """Inherits the production step_sequence; replaces only eval (MLX)."""

        def __init__(self):
            self.eval_calls = 0
            self.transitions = 0

        def eval(self, *values):
            self.eval_calls += 1

    truth_view = data.load_truth_view(DATASET, "development")
    episodes = data.load_training_episodes(DATASET, "development")
    sequences = [data.build_episode_sequence(ep) for ep in episodes]
    by_id = {ep.episode_id: ep for ep in truth_view}

    out = {
        "method": "runtime.MlxBackend.step_sequence (frozen r5 source, unmodified)",
        "mlx_imported": "mlx" in sys.modules,
        "per_k": {},
    }
    for k in (0, 1, 2, 4, 8):
        rec = {"worlds_with_query": 0, "crash": None, "support_written": [], "stop_values": []}
        for sequence in sequences:
            episode = by_id[sequence["episode_id"]]
            transitions = max(len(episode.steps) - 1, 0)
            support, query = metrics.split_support_query(transitions, int(k))
            if not query:
                continue
            rec["worlds_with_query"] += 1
            if not support:
                continue
            backend = RealBackendNoEval()
            model = FakeModel(Counters())
            stop = support[-1] + 1
            try:
                backend.step_sequence(model, sequence, stop=stop)
            except Exception as exc:  # the real guard
                rec["crash"] = {
                    "type": type(exc).__name__,
                    "mro": [c.__name__ for c in type(exc).__mro__[:4]],
                    "message": str(exc),
                    "stop": int(stop),
                    "at_world": rec["worlds_with_query"],
                }
                break
            written = int(model.c.get("single_step_forward_calls", 0))
            rec["support_written"].append(written)
            rec["stop_values"].append(int(stop))
        if rec["support_written"]:
            uniq = sorted(set(rec["support_written"]))
            rec["support_transitions_executed_per_world"] = uniq
            rec["support_transitions_requested"] = int(k)
            rec["off_by_one"] = (uniq != [int(k)]) if k else None
        out["per_k"][str(k)] = rec
    out["guard_source"] = {
        "file": "s1-r5-input-snapshot/src/ainerzero/v9/experiments/s1/runtime.py",
        "sha256": sha256_file(SNAP / "src/ainerzero/v9/experiments/s1" / "runtime.py"),
        "lines": "128-130: frames = len(sequence['obs']) if stop is None else int(stop); "
        "if frames < 2: raise BackendError('a sequence probe needs at least two frames')",
    }
    return out


# --------------------------------------------------------------------------- #
# B/C. call accounting on the pristine and the repaired tree
# --------------------------------------------------------------------------- #
def accounting(tree: Path) -> dict:
    sys.path.insert(0, str(tree))
    for name in [n for n in list(sys.modules) if n.startswith("ainerzero")]:
        del sys.modules[name]
    from ainerzero.v9.experiments.s1 import data, evaluation, metrics, spec

    assert "mlx" not in sys.modules, "MLX must not be imported"
    document = json.loads((SNAP / "artifacts/v9/s1/phase1/r5/pre_registration.json").read_text())
    protocol = document["training_protocol"]

    truth_view = data.load_truth_view(DATASET, "development")
    episodes = data.load_training_episodes(DATASET, "development")
    windows = data.load_development_windows(DATASET)
    sequences = [data.build_episode_sequence(ep) for ep in episodes]

    backend = CountingBackend()
    model = backend.build_model("arm4", seed=0)

    final_probe = backend.window_probe(model, windows, protocol)
    final_rows = evaluation.development_rows(final_probe, truth_view)
    evaluation.localization_report(final_rows)
    for update in sorted(protocol["checkpoint_updates"]):
        if update == int(protocol["updates"]):
            probe, rows = final_probe, final_rows
        else:
            probe = backend.window_probe(model, windows, protocol)
            rows = evaluation.development_rows(probe, truth_view)
        metrics.strict_unseen_map(rows)

    topology = evaluation.topology_report(backend, model, sequences, truth_view)

    few_shot_error = None
    try:
        few_shot = evaluation.few_shot_report(backend, model, sequences, truth_view)
    except Exception as exc:
        few_shot = None
        few_shot_error = {"type": type(exc).__name__, "message": str(exc)}

    per_k = {}
    for k in K_VALUES:
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
        per_k[str(k)] = {
            "worlds_reached": worlds,
            "queries_reached": queries,
            "crashed_at_world": worlds + 1 if crashed else None,
            "error": crashed,
            "calls": dict(sub),
        }

    interference = evaluation.m2_interference(
        backend, model, sequences[:3], truth_view, sequences[3], sequences[4]
    )

    total = dict(backend.c)
    # the m2 probe is the last consumer of `backend`; split it off by re-running
    # the identical three components with a fresh counter set
    split = component_split(backend, model, sequences, truth_view, windows, protocol, final_probe, final_rows)

    return {
        "tree": str(tree),
        "mlx_imported": "mlx" in sys.modules,
        "per_run_total": total,
        "component_split": split,
        "few_shot_error": few_shot_error,
        "per_k_calls": per_k,
        "topology_episodes": topology.get("episodes"),
        "interference_status": interference.get("status"),
    }


def component_split(backend, model, sequences, truth_view, windows, protocol, final_probe, final_rows) -> dict:
    """Attribute the per-run counters to topology / few-shot / m2.

    Each component is re-executed against a *fresh* counter set with the same
    production functions, so the attribution is measured, not assumed.
    """
    from ainerzero.v9.experiments.s1 import evaluation

    def fresh():
        b = CountingBackend()
        m = b.build_model("arm4", seed=0)
        return b, m

    # window probes (5 checkpoints, final reused)
    b, m = fresh()
    b.window_probe(m, windows, protocol)
    for update in sorted(protocol["checkpoint_updates"]):
        if update == int(protocol["updates"]):
            continue
        b.window_probe(m, windows, protocol)
    window_part = dict(b.c)

    # topology
    b, m = fresh()
    evaluation.topology_report(b, m, sequences, truth_view)
    topology_part = dict(b.c)

    # m2 interference (same argument order as worker._evaluate_arm)
    b, m = fresh()
    evaluation.m2_interference(b, m, sequences[:3], truth_view, sequences[3], sequences[4])
    m2_part = dict(b.c)

    return {"window_probes": window_part, "topology": topology_part, "m2_interference": m2_part}


# --------------------------------------------------------------------------- #
# D. reconstruction of the published "frames" numbers
# --------------------------------------------------------------------------- #
def frames_reconstruction() -> dict:
    return {
        "definitions": {
            "calls": "number of step_sequence invocations",
            "stop_frames": "sum of the `frames` value the method receives (len(obs) when stop is None, else stop)",
            "transitions": "sum of (frames - 1) == number of model.forward_terms calls (single-step forwards)",
        },
        "published_numbers": {
            "P15/P16 '611 calls / 1703 frames'": 1703,
            "P18 'crashed 1503'": 1503,
            "P18 'repaired 1903'": 1903,
            "P18 'single-step forwards 1492'": 1492,
        },
        "candidate_decompositions": {
            "1703": "950 (topology stop_frames) + 700 (few-shot TRANSITIONS, k=1/2/4) + 53 (m2 stop_frames)",
            "1503": "750 (topology TRANSITIONS) + 700 (few-shot TRANSITIONS) + 53 (m2 stop_frames)",
            "1903": "1100 (few-shot stop_frames under the repaired stop=k+1) + 750 (topology TRANSITIONS) + 53 (m2 stop_frames)",
            "2103 (coherent repaired stop_frames)": "950 + 1100 + 53",
            "1003 (coherent as-coded stop_frames)": "950 + 0 (few-shot k=0) + 0 (k=1 crashed before any frame) + 53",
        },
        "note": "1503 / 1703 / 1903 each mix 'stop_frames' and 'transitions' for different components; "
        "none of them is a single coherent metric of a real or hypothetical run.",
    }


def main() -> int:
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    info_pristine = build_tree(TREE_PRISTINE, repair=False)
    info_repaired = build_tree(TREE_REPAIRED, repair=True)

    real = real_runtime_checks(TREE_PRISTINE)
    as_coded = accounting(TREE_PRISTINE)
    repaired = accounting(TREE_REPAIRED)

    payload = {
        "schema": "ainerzero.v9.p19.independent-checks.v1",
        "task": "ainerzero.V9.P19",
        "reviewer": "minimax-s1p19-1022",
        "reviewed_task": "ainerzero.V9.P18",
        "identity": {
            "snapshot_root": str(SNAP),
            "pristine_tree": info_pristine,
            "repaired_tree": info_repaired,
            "pristine_evaluation_sha256": sha256_file(SNAP / "src/ainerzero/v9/experiments/s1" / "evaluation.py"),
            "runtime_sha256": sha256_file(SNAP / "src/ainerzero/v9/experiments/s1" / "runtime.py"),
            "metrics_sha256": sha256_file(SNAP / "src/ainerzero/v9/experiments/s1" / "metrics.py"),
            "mlx_imported_anywhere": "mlx" in sys.modules,
        },
        "A_real_runtime_method_checks": real,
        "B_as_coded_accounting_measured": as_coded,
        "C_repaired_accounting_measured": repaired,
        "D_frames_reconstruction": frames_reconstruction(),
        "note": "Every number in B and C is measured by executing the frozen production functions "
        "against a numeric substitute backend. No MLX, no model, no training, no real evaluation. "
        "Section C is a measurement of a 1-line repaired copy of the frozen evaluation.py, NOT a "
        "measurement of the frozen source and NOT a capability result.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "analysis" / "independent_checks.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False)
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
