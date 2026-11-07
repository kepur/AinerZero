import json
import tempfile
from pathlib import Path
from ainerzero.v9.experiments.s2 import prereg, freeze, identity

REPORT_DIR = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S2-P158")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

draft = prereg.build_draft()

# Save draft.json
draft_path = REPORT_DIR / "draft.json"
with open(draft_path, "w", encoding="utf-8") as f:
    json.dump(draft, f, indent=2, ensure_ascii=False)
print(f"Draft saved to {draft_path}")

# Determinism test in two temporary directories
with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
    sha1 = freeze.freeze(draft, out_dir=tmp1)
    verif1 = identity.verify_frozen_identity(Path(tmp1) / "prereg.json")

    sha2 = freeze.freeze(draft, out_dir=tmp2)
    verif2 = identity.verify_frozen_identity(Path(tmp2) / "prereg.json")

    assert sha1 == sha2, f"Determinism failure: {sha1} != {sha2}"

    # Read the frozen prereg.json from tmp1 to extract frozen metadata
    frozen_doc = json.loads((Path(tmp1) / "prereg.json").read_text(encoding="utf-8"))

evidence = {
    "status": "passed",
    "document_sha256": sha1,
    "determinism_verified": sha1 == sha2,
    "trial_directory_1_sha256": sha1,
    "trial_directory_2_sha256": sha2,
    "identity_verification": verif1["status"],
    "source_digests": frozen_doc["source_digests"],
    "source_file_count": len(frozen_doc["source_digests"]),
    "approval_line_candidate": freeze.approval_line(sha1),
}

evidence_path = REPORT_DIR / "freeze_evidence.json"
with open(evidence_path, "w", encoding="utf-8") as f:
    json.dump(evidence, f, indent=2, ensure_ascii=False)
print(f"Freeze evidence saved to {evidence_path}")
print(f"Trial freeze document_sha256: {sha1}")
