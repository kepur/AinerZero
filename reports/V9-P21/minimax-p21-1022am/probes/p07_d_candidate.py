"""P21 probe 07: the D / arm1 candidate identity (A2 manifest, 9 entries).

* the real A2-pinned candidate is verified on this host and every returned
  field is compared with the registered identity in the frozen spec;
* ``checkpoint_id`` and ``tensors_sha256`` are two different fields and are
  not confused;
* the A2 manifest is the trust root: its own identity (the registered
  ``frozen_manifest_digest``) is *reported* by the product but never compared
  with anything, and the manifest file is not frozen by the preregistration;
* tampered / missing / wrong-registered-digest controls must be refused (run
  against a synthetic candidate in an isolated directory; the real pilot files
  are only read).
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import shutil
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402

stub = lib.install_mlx_stub()

from ainerzero.v9.experiments.s1 import arms, spec  # noqa: E402

A2_MANIFEST = lib.REPO / "reports/V9-baseline/r3/baseline_manifest.json"


def synthetic_candidate(root: Path) -> dict:
    """An A2-shaped manifest with pinned files, in an isolated directory."""
    pilot = "pilot-p21"
    checkpoint = "ck-p21"
    prefix = f"{pilot}/checkpoints/{checkpoint}/"
    files = {}
    for name in ("tensors.safetensors", "manifest.json", "metadata.json"):
        path = root / pilot / "checkpoints" / checkpoint / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"payload:{name}".encode())
        files[prefix + name] = path
    files[f"{pilot}/fixed-batch.npz"] = root / pilot / "fixed-batch.npz"
    files[f"{pilot}/fixed-batch.npz"].write_bytes(b"batch")
    manifest = {
        "schema": "ainerzero.baseline_manifest.v1",
        "role": "read-only baseline freeze",
        "counts": {"files": len(files)},
        "files": [
            {"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for rel, path in files.items()
        ],
    }
    manifest_path = root / "baseline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    identity = {
        "frozen_manifest": str(manifest_path),
        "frozen_manifest_digest": "0" * 64,
        "pilot_dir": pilot,
        "checkpoint_id": checkpoint,
        "experiment_id": "p21-synthetic",
        "tensors_sha256": hashlib.sha256(
            files[prefix + "tensors.safetensors"].read_bytes()
        ).hexdigest(),
        "manifest_sha256": hashlib.sha256(files[prefix + "manifest.json"].read_bytes()).hexdigest(),
        "metadata_sha256": hashlib.sha256(files[prefix + "metadata.json"].read_bytes()).hexdigest(),
    }
    return {"identity": identity, "files": files, "prefix": prefix, "root": root}


def main() -> int:
    scratch = lib.scratch_dir("p21-d")
    registered = dict(spec.ARM_SPECS["arm1"]["identity"])

    # --- 1) the real candidate on this host --------------------------------
    real = arms.verify_d_candidate_identity(repo_root=spec.REPO_ROOT)
    a2_manifest = json.loads(A2_MANIFEST.read_text(encoding="utf-8"))
    pilot_entries = [
        row
        for row in a2_manifest.get("files", [])
        if str(row.get("path", "")).startswith(registered["pilot_dir"] + "/")
    ]
    real_checks = {
        "entries_verified": real["entries_verified"],
        "a2_manifest_pilot_entries": len(pilot_entries),
        "checkpoint_id": real["checkpoint_id"],
        "registered_checkpoint_id": registered["checkpoint_id"],
        "tensors_sha256": real["tensors_sha256"],
        "registered_tensors_sha256": registered["tensors_sha256"],
        "manifest_sha256": real["manifest_sha256"],
        "registered_manifest_sha256": registered["manifest_sha256"],
        "metadata_sha256": real["metadata_sha256"],
        "registered_metadata_sha256": registered["metadata_sha256"],
        "manifest_digest_hint": real["manifest_digest_hint"],
        "registered_frozen_manifest_digest": registered["frozen_manifest_digest"],
        "a2_manifest_self_declared_digest": a2_manifest.get("manifest_digest"),
        "a2_manifest_file_sha256": lib.sha256_file(A2_MANIFEST),
        "checkpoint_id_is_not_a_digest": (
            len(str(real["checkpoint_id"])) == 36
            and len(str(real["tensors_sha256"])) == 64
            and real["checkpoint_id"] != real["tensors_sha256"]
        ),
    }
    real_checks["all_digests_match_the_registered_identity"] = (
        real["tensors_sha256"] == registered["tensors_sha256"]
        and real["manifest_sha256"] == registered["manifest_sha256"]
        and real["metadata_sha256"] == registered["metadata_sha256"]
        and real["checkpoint_id"] == registered["checkpoint_id"]
    )
    real_checks["nine_entries_verified"] = real["entries_verified"] == 9 == len(pilot_entries)
    real_checks["a2_manifest_self_digest_matches_the_registered_one"] = (
        a2_manifest.get("manifest_digest") == registered["frozen_manifest_digest"]
    )

    # --- 2) is the A2 manifest's own identity checked by the product? ------
    source = inspect.getsource(arms.verify_d_candidate_identity)
    tree = ast.parse(textwrap.dedent(source))
    assigned = {
        node.targets[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
    }
    loaded = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    frozen_doc = json.loads(
        (lib.REPO / "artifacts/v9/s1/phase1/r7/pre_registration.json").read_text(encoding="utf-8")
    )
    bound_files = frozen_doc["source_identity"]["package_files"]
    trust_root = {
        "frozen_manifest_path_is_absolute": Path(registered["frozen_manifest"]).is_absolute(),
        "locals_assigned_but_never_read": sorted(
            name for name in assigned - loaded if name in {"digest"}
        ),
        "registered_frozen_manifest_digest_is_only_reported": "manifest_digest_hint" in source,
        "a2_manifest_is_bound_by_the_frozen_preregistration": (
            "reports/V9-baseline/r3/baseline_manifest.json" in bound_files
        ),
        "lifecycle_is_bound_by_the_frozen_preregistration": (
            "src/ainerzero/runtime/lifecycle.py" in bound_files
        ),
        "pilot_model_is_bound_by_the_frozen_preregistration": (
            "src/ainerzero/learning/pilot_model.py" in bound_files
        ),
        "checkpoints_module_is_bound_by_the_frozen_preregistration": (
            "src/ainerzero/runtime/checkpoints.py" in bound_files
        ),
        "bound_source_files": sorted(bound_files),
    }

    # --- 3) tamper / missing / wrong-digest controls (synthetic candidate) --
    saved_identity = spec.ARM_SPECS["arm1"]["identity"]
    controls = {}
    try:
        candidate = synthetic_candidate(scratch / "synthetic")
        spec.ARM_SPECS["arm1"]["identity"] = dict(candidate["identity"])
        ok = arms.verify_d_candidate_identity(candidate["root"])
        controls["clean_candidate_accepted"] = {
            "accepted": True,
            "entries_verified": ok["entries_verified"],
        }
        target = candidate["files"][candidate["prefix"] + "tensors.safetensors"]
        target.write_bytes(b"tampered")
        try:
            arms.verify_d_candidate_identity(candidate["root"])
        except Exception as exc:  # noqa: BLE001
            controls["tampered_file_refused"] = {
                "refused": True,
                "error": f"{type(exc).__name__}: {exc}",
            }
        else:
            controls["tampered_file_refused"] = {"refused": False}
        target.write_bytes(f"payload:tensors.safetensors".encode())
        missing = candidate["files"][candidate["prefix"] + "metadata.json"]
        missing.unlink()
        try:
            arms.verify_d_candidate_identity(candidate["root"])
        except Exception as exc:  # noqa: BLE001
            controls["missing_file_refused"] = {
                "refused": True,
                "error": f"{type(exc).__name__}: {exc}",
            }
        else:
            controls["missing_file_refused"] = {"refused": False}
        identity = dict(candidate["identity"])
        identity["tensors_sha256"] = "f" * 64
        spec.ARM_SPECS["arm1"]["identity"] = identity
        try:
            arms.verify_d_candidate_identity(candidate["root"])
        except Exception as exc:  # noqa: BLE001
            controls["wrong_registered_tensors_digest_refused"] = {
                "refused": True,
                "error": f"{type(exc).__name__}: {exc}",
            }
        else:
            controls["wrong_registered_tensors_digest_refused"] = {"refused": False}
        # a manifest that no longer pins the checkpoint at all
        identity = dict(candidate["identity"])
        identity["checkpoint_id"] = "ck-other"
        spec.ARM_SPECS["arm1"]["identity"] = identity
        try:
            arms.verify_d_candidate_identity(candidate["root"])
        except Exception as exc:  # noqa: BLE001
            controls["checkpoint_not_pinned_refused"] = {
                "refused": True,
                "error": f"{type(exc).__name__}: {exc}",
            }
        else:
            controls["checkpoint_not_pinned_refused"] = {"refused": False}
    finally:
        spec.ARM_SPECS["arm1"]["identity"] = saved_identity

    payload = {
        "schema": "ainerzero.v9.p21.probe07_d_candidate_identity.v1",
        "mlx_stub": stub,
        "real_mlx_loaded": lib.real_mlx_loaded(),
        "real_candidate": real_checks,
        "trust_root": trust_root,
        "controls": controls,
        "mlx_imported": lib.mlx_imported(),
    }
    payload["verdict"] = {
        "nine_entries_verified": real_checks["nine_entries_verified"],
        "all_digests_match_the_registered_identity": real_checks[
            "all_digests_match_the_registered_identity"
        ],
        "checkpoint_id_and_tensors_digest_are_distinct_fields": real_checks[
            "checkpoint_id_is_not_a_digest"
        ],
        "tamper_refused": controls["tampered_file_refused"].get("refused", False),
        "missing_refused": controls["missing_file_refused"].get("refused", False),
        "wrong_registered_digest_refused": controls[
            "wrong_registered_tensors_digest_refused"
        ].get("refused", False),
        "unpinned_checkpoint_refused": controls["checkpoint_not_pinned_refused"].get(
            "refused", False
        ),
        "no_real_mlx_loaded": not lib.real_mlx_loaded(),
    }
    out = lib.write_json("07-d-candidate-identity.json", payload)
    print(json.dumps(payload["verdict"], indent=1))
    print(json.dumps(trust_root, indent=1))
    print("wrote", out)
    return 0 if all(payload["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
