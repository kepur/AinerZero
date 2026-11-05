"""r15 evidence (ainerzero.V9.P53): (1) the r14 eval code fails the sliced few-shot case
and the r15 code passes it; (2) memory writes are bitwise unchanged: real-MLX window
probe losses of arm2/3/4 seed 0 are identical between the r14 (before/) and r15 sources.
Builds two source trees in a temporary directory; writes only ../logs/equivalence.json.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
BEFORE = Path(__file__).resolve().parents[1] / "before" / "src"
OUT = Path(__file__).resolve().parents[1] / "logs" / "equivalence.json"
PY = str(REPO / ".venv/bin/python")

CHILD = r'''
import json, sys
import numpy as np
from ainerzero.v9.experiments.s1 import evaluation, data, runtime, spec
sys.path.insert(0, sys.argv[2])
from test_s1_r5_metrics import _episode
out = {"source": evaluation.__file__}
class Sliced:
    def step_sequence(self, model, sequence, *, stop=None, memory=None, pose=None):
        frames = len(sequence["obs"]) if stop is None else int(stop)
        nodes = np.asarray(sequence["obs"][:frames], dtype=np.float64)[:, :2]
        return {"steps": [], "memory": {"nodes": nodes, "positions": np.zeros((frames, 2)),
                "edges": {(i, i + 1) for i in range(frames - 1)}, "threshold": 0.0}, "pose": np.zeros((1, 4))}
    def probe_graph(self, model, memory, pose=None): return memory
    def encode(self, model, obs_row): return np.asarray(obs_row, dtype=np.float64)
    def probe_query(self, model, obs_row): return self.encode(model, obs_row)[:2]
ep = _episode("S", "scene-S", "navigation", [(float(i), 0, 0, 0) for i in range(6)])
seq = {"episode_id": "S", "obs": np.random.default_rng(0).normal(size=(6, 5)).astype(np.float32)}
try:
    evaluation.few_shot_report(Sliced(), object(), [seq], [ep], k_values=(2,), query_limit=8)
    out["sliced_few_shot"] = "completed"
except Exception as exc:
    out["sliced_few_shot"] = f"{type(exc).__name__}: {exc}"[:200]
root = spec.PHASE1_ROOT
dev = data.load_development_windows(data.resolve_dataset_dir(root))
doc = json.loads((root / "r14/pre_registration.json").read_text())
backend = runtime.MlxBackend()
losses = {}
for arm in ("arm2", "arm3", "arm4"):
    model = backend.build_model(arm, seed=0)
    probe = backend.window_probe(model, dev, doc["training_protocol"], max_batches=2)
    losses[arm] = [float(r["loss"]).hex() for r in probe["rows"]]
out["window_probe_losses_hex"] = losses
print(json.dumps(out))
'''


def tree(dst: Path, s1_override: Path | None) -> Path:
    shutil.copytree(REPO / "src", dst, ignore=shutil.ignore_patterns("__pycache__"))
    if s1_override is not None:
        for f in s1_override.glob("*.py"):
            shutil.copy2(f, dst / "ainerzero/v9/experiments/s1" / f.name)
    return dst


def run(src: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(src)
    p = subprocess.run([PY, "-c", CHILD, str(src), str(REPO / "tests/v9/experiments")],
                       env=env, capture_output=True, text=True, cwd=str(REPO), timeout=600)
    if p.returncode != 0:
        return {"error": p.stderr[-1500:]}
    return json.loads(p.stdout.strip().splitlines()[-1])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="s1-r15-eq-") as td:
        before = run(tree(Path(td) / "before", BEFORE))
        after = run(tree(Path(td) / "after", None))
    payload = {
        "r14_before": before,
        "r15_after": after,
        "r14_fails_sliced_few_shot": before.get("sliced_few_shot", "").startswith("ValueError"),
        "r15_passes_sliced_few_shot": after.get("sliced_few_shot") == "completed",
        "window_probe_losses_bitwise_equal": before.get("window_probe_losses_hex") == after.get("window_probe_losses_hex")
        and bool(after.get("window_probe_losses_hex")),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if not isinstance(v, dict)}, indent=1))
    print("before few-shot:", before.get("sliced_few_shot"))
    return 0 if payload["r14_fails_sliced_few_shot"] and payload["r15_passes_sliced_few_shot"] and payload["window_probe_losses_bitwise_equal"] else 9


if __name__ == "__main__":
    raise SystemExit(main())
