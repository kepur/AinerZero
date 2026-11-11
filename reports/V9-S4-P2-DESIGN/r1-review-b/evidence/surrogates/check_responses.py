"""P215: sanity check of the crude responses on hand-made member states (two disks head-on, one oblique pair),
against the generator's own disk collision (world.physics). Imports MLX via the module -> run under the lock."""
import importlib.util, sys
import numpy as np
spec = importlib.util.spec_from_file_location("th", sys.argv[1]); th = importlib.util.module_from_spec(spec); spec.loader.exec_module(th)
from ainerzero.v9.experiments.s4 import world as W, models as Mo
P = np.array([[[5.0, 5.0], [5.55, 5.0], [8.0, 8.0]], [[5.0, 5.0], [5.4, 5.4], [2.0, 2.0]]])
V = np.array([[[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0]], [[1.0, 0.2], [0.0, -1.0], [1.0, 0.0]]])
pb, vb = Mo.bounce(P, V, [])
pe, ve, _ = W.physics(P, V, [])
for k in th.ARMS:
    print(k, np.round(th.response(k, P, vb)[:, :2], 3).tolist())
print("E-P velocities after one step (generator):", np.round(ve[:, :2], 3).tolist())
