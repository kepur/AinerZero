import sys, time, json
from pathlib import Path
sys.path.insert(0, "src")
import numpy as np
from ainerzero.v9.experiments.s5.data import ClipIndex
from ainerzero.v9.experiments.s5.train import TrainConfig, distill
from ainerzero.v9.experiments.s5.student import Student
tau = None if sys.argv[1] == "none" else float(sys.argv[1])
pool = ClipIndex(Path("artifacts/v9/s5/data/s5p1-pool"))
teachers = {"vjepa": "artifacts/v9/s5/teachers/vjepa/s5p1-pool", "da2": "artifacts/v9/s5/teachers/da2/s5p1-pool"}
cfg = TrainConfig(lr=3e-4, batch_size=8, epochs=1, seed=0, tau=tau)
t0 = time.perf_counter()
student, heads, log = distill("A1", pool, teachers, cfg, student=Student())
w = time.perf_counter() - t0
L = log["step_logs"]
def med(xs): return round(float(np.median(xs)), 4)
q = len(L) // 4
print(json.dumps({"tau": tau, "steps": len(L), "wall_s": round(w, 1),
  "step_s_by_quarter": [med([r["step_s"] for r in L[i*q:(i+1)*q]]) for i in range(4)],
  "data_s_by_quarter": [med([r["data_s"] for r in L[i*q:(i+1)*q]]) for i in range(4)]}), flush=True)
