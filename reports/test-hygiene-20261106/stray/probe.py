
import sys; sys.path.insert(0, str(Path("/Users/mac/AinerWorkFlow/AinerZero/src")))
from ainerzero.v9.experiments.s1 import spec, identity as identity_module
# 1. tamper document arms.arm1 identity (should not matter)
orig_id = dict(spec.ARM_SPECS["arm1"]["identity"])
try:
    identity_module.verify_d_candidate_identity(repo_root=spec.REPO_ROOT)
    doc_ok = "ok"
except Exception as e:
    doc_ok = f"{type(e).__name__}: {e}"
# 2. tamper spec.ARM_SPECS arm1 identity (should fail)
spec.ARM_SPECS["arm1"]["identity"]["frozen_manifest_file_sha256"] = "0" * 64
try:
    identity_module.verify_d_candidate_identity(repo_root=spec.REPO_ROOT)
    spec_ok = "ok"
except Exception as e:
    spec_ok = f"{type(e).__name__}: {e}"
finally:
    spec.ARM_SPECS["arm1"]["identity"] = orig_id
print(json.dumps({"doc_tamper": doc_ok, "spec_tamper": spec_ok}))
