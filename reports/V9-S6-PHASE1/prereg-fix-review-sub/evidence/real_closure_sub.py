"""P262-sub: read-only closure facts for the REAL probe inside an isolated clone (no builder output path).

usage: python -B real_closure_sub.py <case_root>
Prints: numerical (42-file) code manifest size/SHA, formal prereg manifest file list (as make_prereg.main builds
it), validate_probe evidence summary (closure size, science_all_pass), an independent recomputation of the
gate decision from the raw errors.npz compared with the report, and the budget formula by hand.
"""
import hashlib
import importlib.abc
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True


class NoMLX(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mlx" or fullname.startswith("mlx."):
            raise RuntimeError("P262-sub FORBIDDEN MLX IMPORT: " + fullname)


sys.meta_path.insert(0, NoMLX())
root = Path(sys.argv[1]).resolve()
assert not root.is_relative_to(Path("/Users/mac/AinerWorkFlow/AinerZero"))
spec = importlib.util.spec_from_file_location("mp_sub", root / "reports/V9-S6-PHASE1/make_prereg.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)
PE, GD, AN = B.PE, B.GD, B.AN
probe = root / "reports/V9-S6-PHASE1/probe/EVAL-probe.json"
code = GD.build_manifest(root, [B.RUNNER], src_root=root / "src", extra=[B.VERIFY])
print("NUMERICAL_MANIFEST_FILES", len(code), "SHA", PE.manifest_sha(code))
print("NUMERICAL_MANIFEST_HAS_BUILDER_OR_HELPER", any(k.endswith(("make_prereg.py", "prereg_evidence.py")) for k in code))
design = root / "reports/V9-S6-DESIGN/DESIGN-r2.md"
formal = GD.build_manifest(root, [B.RUNNER], src_root=root / "src",
                           extra=[design, B.VERIFY, Path(B.__file__).resolve(), Path(PE.__file__).resolve()])
print("FORMAL_MANIFEST_FILES", len(formal))
print("FORMAL_MINUS_NUMERICAL", json.dumps(sorted(set(formal) - set(code))))
print("FORMAL_HELPER_SHA", formal.get("reports/V9-S6-PHASE1/prereg_evidence.py"),
      "BUILDER_SHA", formal.get("reports/V9-S6-PHASE1/make_prereg.py"))
print("NUMERICAL_ENTRIES_EQUAL_IN_FORMAL", all(formal[k] == v for k, v in code.items()))
versions = PE.cpu_versions(root)
print("CPU_VERSIONS", versions)
pr, ev = PE.validate_probe(root, probe, code, versions)
print("CLOSURE_FILES", len(ev["files_sha256"]), "SCIENCE_ALL_PASS", ev["science_all_pass"],
      "LEDGER_S", ev["training_ledger_seconds"], "HEAD", ev["current_git_head"])
kinds = {}
for k in ev["files_sha256"]:
    kinds[k.rsplit(".", 1)[-1]] = kinds.get(k.rsplit(".", 1)[-1], 0) + 1
print("CLOSURE_BY_EXT", json.dumps(kinds, sort_keys=True))
# independent recomputation (reviewer-written loop, same analysis module)
import numpy as np  # noqa: E402

with np.load(root / "artifacts/v9/s6/phase1/probe/eval-s6p1-probe/errors.npz", allow_pickle=False) as d:
    arr = {k: d[k] for k in d.files}


def inp(r):
    return {t: {"sums": {a: arr[f"{t}/sums/{a}"][:, :, r] for a in AN.ARMS}, "counts": arr[f"{t}/counts"],
                "eb": arr[f"{t}/eb"]} for t in ("main6", "extrap10")}


rep = json.loads(probe.read_text())
mine = json.loads(json.dumps(AN.decide(inp(3))))
print("GATES_RECOMPUTED_EQUAL_REPORT", mine == rep["result"])
print("GATES", {g: v["passed"] for g, v in mine["gates"].items()}, "ALL_PASS", mine["all_pass"])
print("DESCRIPTIVE_EQUAL", json.loads(json.dumps({f"round{r}": AN.describe(inp(r)) for r in range(4)})) == rep["descriptive"])
fin = rep["sets"]["final"]
tr = 1.15 * (sum(rep["train_seconds"][a + "-r0"] * k for a, k in fin["reps"].items()) + 450)
n = sum(fin["reps"].values())
ev_s = 1.30 * (rep["verify_seconds"] * n / 6 + rep["eval_seconds"] * n / 6 * sum(fin["worlds"]) / sum(rep["config"]["worlds"]))
print("HAND_BUDGET train", tr, "eval", ev_s, "n_final", n, "caps", fin["train_cap_s"], fin["eval_limit_s"])
print("REPORT_TIMES verify", rep["verify_seconds"], "eval", rep["eval_seconds"], "elapsed", rep["elapsed_s"],
      "gap", round(rep["elapsed_s"] - rep["verify_seconds"] - rep["eval_seconds"], 3))
print("REPORT_SHA256", hashlib.sha256(probe.read_bytes()).hexdigest())
print("MLX_IN_SYS_MODULES", any(k == "mlx" or k.startswith("mlx.") for k in sys.modules))
