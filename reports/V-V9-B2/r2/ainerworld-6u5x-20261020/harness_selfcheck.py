"""Harness self-check: reproduce the r1 false positive (FakeWorldBrain ctor -> TypeError). Must be FAIL here."""
import sys, json
sys.path.insert(0, '/Users/mac/AinerWorkFlow/AinerZero/src'); sys.path.insert(0, __file__.rsplit('/', 1)[0])
import b3_strict
import ainerzero.v9.fakes.world_brain as W
def boom(self, *a, **k): raise TypeError("injected constructor crash")
W.FakeWorldBrain.__init__ = boom
rcs = {n: b3_strict.child(n, None) for n in ("truth_nested", "envelope", "time_backwards")}
print("SELFCHECK " + json.dumps(rcs))
sys.exit(0 if all(v == 3 for v in rcs.values()) else 1)
