"""P213: E-P and E-B differ not only at logged disk contacts. Two overlapping disks that move apart
(no velocity reversal, so no logged contact) are pushed apart by E-P (world.py: push on every overlapping
pair) but not by E-B. Pure CPU, no world generated. Usage: python -I -B <this>"""
import numpy as np
from ainerzero.v9.experiments.s4 import world as W, models as Mo
P = np.array([[[5.0, 5.0], [5.5, 5.0]]])            # distance 0.5 < 2R = 0.6: overlapping
V = np.array([[[-0.05, 0.0], [0.05, 0.0]]])        # separating slowly
pe, ve, cont = W.physics(P, V, [], log=True)
pb, vb = Mo.bounce(P, V, [])
print("logged contacts:", cont)
print("E-P positions:", pe[0].round(6).tolist(), "velocities:", ve[0].round(6).tolist())
print("E-B positions:", pb[0].round(6).tolist(), "velocities:", vb[0].round(6).tolist())
print("positions identical:", bool(np.array_equal(pe, pb)), " velocities identical:", bool(np.array_equal(ve, vb)))
