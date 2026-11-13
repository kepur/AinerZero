import sys, time, json
from pathlib import Path
sys.path.insert(0, "src"); sys.path.insert(0, "reports/V9-S5-PHASE1")
import numpy as np
import run_s5p1 as pre
from ainerzero.v9.experiments.s5.train import TrainConfig, train_supervised
from ainerzero.v9.experiments.s5.student import Student
lab = pre._index_for(Path("artifacts/v9/s5/data/s5p1-lab"), None, label_n=512)
cfg = TrainConfig(lr=1e-3, batch_size=8, epochs=6, seed=0, tau=0.02)
t0 = time.perf_counter()
student, heads, log = train_supervised(lab, cfg, student=Student())
L = log["step_logs"]; q = len(L) // 4
med = lambda xs: round(float(np.median(xs)), 4)
print(json.dumps({"A0-R steps": len(L), "wall_s": round(time.perf_counter() - t0, 1),
  "step_s_by_quarter": [med([r["step_s"] for r in L[i*q:(i+1)*q]]) for i in range(4)]}))
