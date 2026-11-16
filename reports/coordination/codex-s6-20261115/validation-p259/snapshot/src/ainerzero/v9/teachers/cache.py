"""Teacher Cache v2 / v2.1 library (CPU, no model loading).

Content-addressable blobs + source-bound entries.
Aligned with docs/v9/TEACHERS_AND_CACHE.md r3 + F11/F12 admission bindings.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None

REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = REPO_ROOT / "contracts/v9/teacher_cache.v2.schema.json"
SCHEMA_V21_PATH = REPO_ROOT / "contracts/v9/teacher_cache.v2_1.schema.json"
DEFAULT_CACHE_ROOT = REPO_ROOT / "artifacts/teachers/cache"

REGISTRY = "adr-0005-current-approved-empty-20261016"
SCHEMA_VERSION = "az.v9.teacher_cache.v2"


def canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(obj: Any) -> str:
    return hashlib.sha256(canon(obj)).hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def near(a: float, b: float) -> bool:
    return math.isclose(a, b, abs_tol=1e-9, rel_tol=0)


class TeacherCacheError(Exception):
    pass


class SchemaValidationError(TeacherCacheError):
    pass


class HashMismatchError(TeacherCacheError):
    pass


class CrossPartitionError(TeacherCacheError):
    pass


class MetadataIncompleteError(TeacherCacheError):
    pass


class ImmutableConflictError(TeacherCacheError):
    """Same identity, different content — refuse overwrite."""


def compute_entry_id(entry: Dict) -> str:
    return sha(
        {
            "cache_key": entry["cache_key"],
            "world_key": entry["source"]["world_key"],
            "partition": entry["source"]["partition"],
            "input_sha256": entry["provenance"]["upstream"]["input_ref"]["sha256"],
            "use": entry["provenance"]["derivation"]["use"],
        }
    )


def _schema_load(path: Path = SCHEMA_PATH) -> Dict:
    return json.loads(path.read_text())


def _subvalidator(schema: Dict, name: str):
    if Draft202012Validator is None:
        return None
    s = dict(schema)
    s.pop("oneOf", None)
    s["$ref"] = f"#/$defs/{name}"
    return Draft202012Validator(s)


def validate_schema(record: Dict, record_type: str, schema: Optional[Dict] = None) -> List[str]:
    if Draft202012Validator is None:
        return ["jsonschema_not_available"]
    schema = schema or _schema_load()
    validator = _subvalidator(schema, record_type)
    if validator is None:
        return ["jsonschema_not_available"]
    return [f"{e.json_path}: {e.message}" for e in validator.iter_errors(record)]


def default_generation(mode: str = "teacher") -> Dict[str, Any]:
    return {
        "mode": mode,
        "argv": ["teacher-cache-write"],
        "started_at": "2026-10-20T00:00:00+03:00",
        "wall_s": 0.0,
        "peak_memory_bytes": {"mlx": None, "rss": 0},
        "host": "cpu-local",
        "lease": {
            "lock": "artifacts/locks/m0-worker.lock",
            "held_from_start_to_end": True,
        },
    }


def build_blob_record(
    cache_key: str,
    key_material: Dict,
    output_data: bytes,
    teacher_license: Dict,
    reproducibility: str = "unverified",
    confidence_data: Optional[bytes] = None,
    generation_info: Optional[Dict] = None,
    output_meta: Optional[Dict] = None,
    confidence_meta: Optional[Dict] = None,
    tolerance: Any = None,
) -> Dict[str, Any]:
    """Build a schema-v2 teacher_blob record (does not touch disk)."""
    out_sha = sha_bytes(bytes(output_data))
    files = [
        {
            "name": "output.bin",
            "bytes": len(output_data),
            "sha256": out_sha,
            "media_type": "application/octet-stream",
        }
    ]
    output = {
        "kind": "dense_feature",
        "files": files,
        "shape": [max(1, len(output_data) // 4), 1],
        "dtype": "float32",
        "scale": "not_applicable",
        "coordinate_frame": {"camera_convention": "none", "to_world": None},
        "time_stride_s": 0.083333,
        "token_stats": None,
    }
    if output_meta:
        output.update(output_meta)
        output["files"] = files  # always bind to written bytes

    if confidence_meta is not None:
        confidence = confidence_meta
    elif confidence_data is not None:
        confidence = {
            "kind": "scalar",
            "file": "confidence.bin",
        }
    else:
        confidence = {"kind": "none", "file": None}

    if reproducibility == "numeric" and tolerance is None:
        tolerance = {"metric": "cosine_min", "value": 0.999}

    record: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "teacher_blob",
        "cache_key": cache_key,
        "key_material": key_material,
        "output": output,
        "confidence": confidence,
        "reproducibility": reproducibility,
        "tolerance": tolerance,
        "teacher_license": teacher_license,
        "generation": generation_info or default_generation(),
    }
    return record


class TeacherCache:
    """Filesystem-backed teacher cache with injectable root (tests use tmp)."""

    REQUIRED_BLOB_META = ("cache_key", "key_material", "teacher_license", "reproducibility")
    REQUIRED_ENTRY_META = (
        "entry_id",
        "cache_key",
        "source",
        "provenance",
        "license",
        "as_of_t_ticks",
        "as_of_t_s",
    )

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else DEFAULT_CACHE_ROOT
        self.blobs_dir = self.root / "blobs"
        self.entries_dir = self.root / "entries"
        self.lock_path = self.root / ".write.lock"

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)

    def write_blob(
        self,
        cache_key: str,
        key_material: Dict,
        output_data: bytes,
        teacher_license: Dict,
        reproducibility: str = "unverified",
        confidence_data: Optional[bytes] = None,
        generation_info: Optional[Dict] = None,
        output_meta: Optional[Dict] = None,
        confidence_meta: Optional[Dict] = None,
        tolerance: Any = None,
        extra: Optional[Dict] = None,
    ) -> Dict:
        for name, val in (
            ("cache_key", cache_key),
            ("key_material", key_material),
            ("teacher_license", teacher_license),
            ("reproducibility", reproducibility),
            ("output_data", output_data),
        ):
            if val is None or val == "" or val == {}:
                raise MetadataIncompleteError(f"missing required blob metadata: {name}")
        if not isinstance(output_data, (bytes, bytearray)):
            raise MetadataIncompleteError("output_data must be bytes")
        if sha(key_material) != cache_key:
            raise HashMismatchError(f"cache_key mismatch for {cache_key[:16]}...")

        record = build_blob_record(
            cache_key=cache_key,
            key_material=key_material,
            output_data=bytes(output_data),
            teacher_license=teacher_license,
            reproducibility=reproducibility,
            confidence_data=confidence_data,
            generation_info=generation_info,
            output_meta=output_meta,
            confidence_meta=confidence_meta,
            tolerance=tolerance,
        )
        if extra:
            # reject unknown top-level extras that would break schema
            raise SchemaValidationError("extra top-level blob fields are not allowed")

        errs = validate_schema(record, "teacher_blob")
        if errs:
            raise SchemaValidationError("blob schema invalid: " + "; ".join(errs[:5]))

        out_sha = record["output"]["files"][0]["sha256"]

        with self._write_lock():
            blob_dir = self.blobs_dir / cache_key[:2] / cache_key
            blob_dir.mkdir(parents=True, exist_ok=True)
            blob_json_path = blob_dir / "blob.json"
            output_path = blob_dir / "output.bin"
            confidence_path = blob_dir / "confidence.bin"

            if blob_json_path.exists():
                existing = json.loads(blob_json_path.read_text())
                existing_sha = _blob_output_sha(existing)
                if existing_sha != out_sha:
                    raise TeacherCacheError(
                        f"nondeterministic_output: existing blob {cache_key[:16]}... differs"
                    )
                # identical content → skip
                if canon(existing) == canon(record) or existing_sha == out_sha:
                    return existing
                raise ImmutableConflictError(
                    f"blob {cache_key[:16]}... exists with different metadata"
                )

            # O_EXCL create marker to close check-then-act race
            marker = blob_dir / ".creating"
            try:
                fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.close(fd)
            except FileExistsError:
                # another writer won; re-read
                if blob_json_path.exists():
                    existing = json.loads(blob_json_path.read_text())
                    if _blob_output_sha(existing) != out_sha:
                        raise TeacherCacheError(
                            f"nondeterministic_output: existing blob {cache_key[:16]}... differs"
                        )
                    return existing
                raise TeacherCacheError("concurrent blob create in progress")

            try:
                tmp_out = self._atomic_write_bytes(blob_dir, bytes(output_data))
                tmp_conf = None
                if confidence_data is not None:
                    tmp_conf = self._atomic_write_bytes(blob_dir, bytes(confidence_data))
                tmp_json = self._atomic_write_text(
                    blob_dir,
                    json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                )
                os.replace(tmp_out, output_path)
                if tmp_conf is not None:
                    os.replace(tmp_conf, confidence_path)
                os.replace(tmp_json, blob_json_path)
            finally:
                try:
                    marker.unlink()
                except FileNotFoundError:
                    pass
            return record

    def read_blob(self, cache_key: str) -> Dict:
        blob_dir = self.blobs_dir / cache_key[:2] / cache_key
        blob_json_path = blob_dir / "blob.json"
        output_path = blob_dir / "output.bin"
        if not blob_json_path.exists():
            raise TeacherCacheError(f"Blob not found: {cache_key[:16]}...")
        record = json.loads(blob_json_path.read_text())

        # F9: recompute cache_key from key_material
        km = record.get("key_material")
        if km is None or sha(km) != cache_key or record.get("cache_key") != cache_key:
            record["broken"] = True
            record["broken_reason"] = "cache_key_mismatch"
            self._rewrite_json(blob_json_path, record)
            raise HashMismatchError(
                f"Blob {cache_key[:16]}... cache_key mismatch (marked broken)"
            )

        expected = _blob_output_sha(record)
        if output_path.exists() and expected is not None:
            actual = sha_bytes(output_path.read_bytes())
            if actual != expected:
                record["broken"] = True
                record["broken_reason"] = "output_hash_mismatch"
                self._rewrite_json(blob_json_path, record)
                raise HashMismatchError(
                    f"Blob {cache_key[:16]}... output hash mismatch (marked broken)"
                )
        return record

    def write_entry(self, entry: Dict) -> Dict:
        for key in self.REQUIRED_ENTRY_META:
            if key not in entry or entry[key] is None:
                raise MetadataIncompleteError(f"missing required entry metadata: {key}")

        payload = dict(entry)
        payload.setdefault("schema_version", SCHEMA_VERSION)
        payload.setdefault("record_type", "teacher_entry")
        payload.setdefault("store", "shared")
        payload.setdefault("noise_model_ref", None)
        if "source_type" not in payload.get("provenance", {}):
            payload["provenance"] = dict(payload["provenance"])
            payload["provenance"]["source_type"] = "teacher_feature"

        entry_id = payload["entry_id"]
        cache_key = payload["cache_key"]
        computed = compute_entry_id(payload)
        if entry_id != computed:
            raise HashMismatchError(f"entry_id mismatch: {entry_id[:16]}... != {computed[:16]}...")

        errs = validate_schema(payload, "teacher_entry")
        if errs:
            raise SchemaValidationError("entry schema invalid: " + "; ".join(errs[:5]))

        with self._write_lock():
            blob = self.read_blob(cache_key)
            self._check_derivation(payload, blob)

            part = payload.get("source", {}).get("partition")
            for existing_file in self.entries_dir.rglob("*.json"):
                try:
                    existing = json.loads(existing_file.read_text())
                except json.JSONDecodeError:
                    continue
                if existing.get("record_type") != "teacher_entry":
                    continue
                if existing.get("entry_id") == entry_id:
                    if canon(existing) == canon(payload):
                        return existing
                    raise ImmutableConflictError(
                        f"entry {entry_id[:16]}... exists with different content"
                    )
                if existing.get("cache_key") != cache_key:
                    continue
                existing_part = existing.get("source", {}).get("partition")
                if (
                    part in ("train", "development", "final")
                    and existing_part in ("train", "development", "final")
                    and existing_part != part
                ):
                    raise CrossPartitionError(
                        f"cross_partition_blob: cache_key {cache_key[:16]}... "
                        f"partition {existing_part} and {part}"
                    )

            entry_dir = self.entries_dir / entry_id[:2] / entry_id
            entry_dir.mkdir(parents=True, exist_ok=True)
            entry_path = entry_dir / f"{entry_id}.json"

            if entry_path.exists():
                existing = json.loads(entry_path.read_text())
                if canon(existing) == canon(payload):
                    return existing
                raise ImmutableConflictError(
                    f"entry {entry_id[:16]}... exists with different content"
                )

            # O_EXCL then replace
            tmp = self._atomic_write_text(
                entry_dir, json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
            )
            try:
                fd = os.open(str(entry_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.close(fd)
                os.replace(tmp, entry_path)
            except FileExistsError:
                try:
                    Path(tmp).unlink()
                except FileNotFoundError:
                    pass
                existing = json.loads(entry_path.read_text())
                if canon(existing) == canon(payload):
                    return existing
                raise ImmutableConflictError(
                    f"entry {entry_id[:16]}... exists with different content"
                )
            return payload

    def read_entry(self, entry_id: str) -> Dict:
        entry_path = self.entries_dir / entry_id[:2] / entry_id / f"{entry_id}.json"
        if not entry_path.exists():
            raise TeacherCacheError(f"Entry not found: {entry_id[:16]}...")
        entry = json.loads(entry_path.read_text())
        if compute_entry_id(entry) != entry_id:
            entry["broken"] = True
            entry["broken_reason"] = "entry_id_mismatch"
            self._rewrite_json(entry_path, entry)
            raise HashMismatchError(f"Entry {entry_id[:16]}... entry_id mismatch (marked broken)")
        try:
            blob = self.read_blob(entry["cache_key"])
            self._check_derivation(entry, blob)
        except (HashMismatchError, TeacherCacheError) as exc:
            if isinstance(exc, HashMismatchError) and "derivation" in str(exc):
                entry["broken"] = True
                entry["broken_reason"] = "derivation_mismatch"
                self._rewrite_json(entry_path, entry)
                raise
            if "output hash" in str(exc) or "cache_key" in str(exc):
                entry["broken"] = True
                entry["broken_reason"] = "referenced_blob_broken"
                self._rewrite_json(entry_path, entry)
            raise
        return entry

    @staticmethod
    def _check_derivation(entry: Dict, blob: Dict) -> None:
        dv = entry["provenance"]["derivation"]
        k = blob["key_material"]
        if dv.get("teacher_id") != k["teacher"]["teacher_id"]:
            raise HashMismatchError("derivation_teacher_mismatch")
        weights = [w["sha256"] for w in k["teacher"]["weights"]]
        if dv.get("weights_sha256") != weights:
            raise HashMismatchError("derivation_weights_mismatch")
        if dv.get("preprocess_spec_sha256") != k["preprocess"]["spec_sha256"]:
            raise HashMismatchError("derivation_preprocess_mismatch")

    @staticmethod
    def _atomic_write_bytes(directory: Path, data: bytes) -> Path:
        fd, name = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        return Path(name)

    @staticmethod
    def _atomic_write_text(directory: Path, text: str) -> Path:
        fd, name = tempfile.mkstemp(dir=str(directory), suffix=".tmp", text=True)
        try:
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return Path(name)

    @staticmethod
    def _rewrite_json(path: Path, obj: Dict) -> None:
        tmp = TeacherCache._atomic_write_text(
            path.parent, json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        )
        os.replace(tmp, path)


def _blob_output_sha(record: Dict) -> Optional[str]:
    """Extract output content hash from schema-v2 or legacy record."""
    output = record.get("output")
    if isinstance(output, dict):
        files = output.get("files") or []
        if files and isinstance(files[0], dict) and files[0].get("sha256"):
            return files[0]["sha256"]
    legacy = record.get("output_sha256")
    return legacy if isinstance(legacy, str) else None


_default_cache: Optional[TeacherCache] = None


def get_cache(root: Optional[Path] = None) -> TeacherCache:
    global _default_cache
    if root is not None:
        return TeacherCache(root)
    if _default_cache is None:
        _default_cache = TeacherCache()
    return _default_cache


def set_cache_root(root: Path) -> TeacherCache:
    global _default_cache
    _default_cache = TeacherCache(root)
    return _default_cache


def write_blob(*args, **kwargs) -> Dict:
    return get_cache().write_blob(*args, **kwargs)


def read_blob(cache_key: str) -> Dict:
    return get_cache().read_blob(cache_key)


def write_entry(entry: Dict) -> Dict:
    return get_cache().write_entry(entry)


def read_entry(entry_id: str) -> Dict:
    return get_cache().read_entry(entry_id)


def _lookup_admission(context: Dict, entry: Dict) -> Optional[Dict]:
    bindings = context.get("admission_bindings")
    if not isinstance(bindings, list):
        return None
    eid = entry.get("entry_id")
    ck = entry.get("cache_key")
    for b in bindings:
        if b.get("entry_id") == eid and b.get("cache_key") == ck:
            return b
    for b in bindings:
        if b.get("entry_id") == eid:
            return b
    return None


def store_problems(
    records: List[Dict],
    context: Optional[Dict],
    expected_context_sha256: str,
    schema: Optional[Dict] = None,
    disabled: Tuple[str, ...] = (),
) -> List[str]:
    """Library-level store validation (r3 rules + F11/F12 admission bindings)."""
    if Draft202012Validator is None:
        return ["jsonschema_not_available"]

    schema = schema or _schema_load()
    problems: List[str] = []
    validator = Draft202012Validator(schema)

    if not isinstance(records, list) or not records:
        return ["records_structure"]
    if "schema" not in disabled and any(not validator.is_valid(r) for r in records):
        return ["schema"]
    if context is None:
        return ["trusted_context_missing"]
    if not expected_context_sha256 or (
        "context_identity" not in disabled and sha(context) != expected_context_sha256
    ):
        return ["trusted_context_identity"]

    # Context schema: prefer v2.1 when admission_bindings present
    ctx_schema = schema
    if "admission_bindings" in context and SCHEMA_V21_PATH.exists():
        try:
            ctx_schema = _schema_load(SCHEMA_V21_PATH)
        except OSError:
            ctx_schema = schema
    ctx_v = _subvalidator(ctx_schema, "trusted_context")
    if "context_schema" not in disabled and ctx_v is not None and not ctx_v.is_valid(context):
        return ["trusted_context_schema"]

    registry = context.get("approval_registry", {})
    if "approval_registry" not in disabled and (
        registry.get("registry_id") != REGISTRY or registry.get("entries")
    ):
        return ["approval_registry_not_current_empty"]

    manifest = context.get("source_manifest", {})
    srcs = manifest.get("sources", [])
    if len({x["source_id"] for x in srcs}) != len(srcs):
        return ["duplicate_source_identity"]
    source_by_id = {x["source_id"]: x for x in srcs}
    obs = context.get("observation", {})
    if not near(obs.get("t_s", 0), obs.get("t_ticks", 0) / 120):
        return ["trusted_observation_clock"]

    blobs = {r["cache_key"]: r for r in records if r.get("record_type") == "teacher_blob"}
    if len(blobs) != sum(1 for r in records if r.get("record_type") == "teacher_blob"):
        return ["duplicate_blob_key"]

    parts: Dict[str, set] = {}
    for b in blobs.values():
        k = b["key_material"]
        inp = k["input"]
        if "key" not in disabled and sha(k) != b["cache_key"]:
            problems.append("cache_key_mismatch")
        ticks = inp.get("timestamps_ticks")
        seconds = inp.get("timestamps_s")
        if "tick_seconds" not in disabled:
            if ticks is None or seconds is None or len(ticks) != len(seconds):
                problems.append("blob_tick_seconds_mismatch")
            elif any(not near(t / 120, s) for t, s in zip(ticks, seconds)):
                problems.append("blob_tick_seconds_mismatch")

    bindings = context.get("admission_bindings")
    enforce_admission = "admission" not in disabled and bindings is not None

    for e in (r for r in records if r.get("record_type") == "teacher_entry"):
        b = blobs.get(e["cache_key"])
        if b is None:
            problems.append("orphan_entry")
            continue
        k = b["key_material"]
        inp = k["input"]
        source = e["source"]
        up = e["provenance"]["upstream"]
        dv = e["provenance"]["derivation"]

        if "eid" not in disabled and compute_entry_id(e) != e["entry_id"]:
            problems.append("entry_id_mismatch")
        if "input" not in disabled and up["input_ref"]["sha256"] != inp["sha256"]:
            problems.append("input_mismatch")
        if "derived" not in disabled and dv["teacher_id"] != k["teacher"]["teacher_id"]:
            problems.append("derivation_teacher_mismatch")
        if "weights" not in disabled and dv["weights_sha256"] != [w["sha256"] for w in k["teacher"]["weights"]]:
            problems.append("derivation_weights_mismatch")
        if "preprocess" not in disabled and dv["preprocess_spec_sha256"] != k["preprocess"]["spec_sha256"]:
            problems.append("derivation_preprocess_mismatch")
        if "noise" not in disabled and k["teacher"]["teacher_kind"] == "feature" and e.get("noise_model_ref") is not None:
            problems.append("feature_with_noise_model")

        ref = source.get("manifest_ref", {})
        original = (
            source_by_id.get(ref.get("source_id"))
            if ref.get("manifest_id") == manifest.get("manifest_id")
            else None
        )
        if "source_binding" not in disabled and (
            original is None
            or original["world_key"] != source["world_key"]
            or original["partition"] != source["partition"]
            or original["upstream"] != up
        ):
            problems.append("original_source_binding_mismatch")

        if "domain" not in disabled and (
            source.get("time_domain") != inp.get("time_domain")
            or inp.get("time_domain") != obs.get("time_domain")
            or original is None
            or original.get("time_domain") != inp.get("time_domain")
        ):
            problems.append("observation_time_domain_mismatch")

        if "source_times" not in disabled and (
            source.get("timestamps_ticks") != inp.get("timestamps_ticks")
            or source.get("timestamps_s") != inp.get("timestamps_s")
        ):
            problems.append("source_blob_timestamps_mismatch")

        if "cutoff" not in disabled and (
            e.get("as_of_t_ticks") != obs.get("t_ticks")
            or not near(e.get("as_of_t_s", 0), obs.get("t_ticks", 0) / 120)
        ):
            problems.append("current_observation_cutoff_mismatch")

        if "asof" not in disabled and dv.get("use") == "input":
            if max(inp["timestamps_ticks"]) > obs["t_ticks"] or max(inp["timestamps_s"]) > obs["t_s"] + 1e-9:
                problems.append("input_after_trusted_observation")

        elig = up.get("eligibility", {})
        if "approval" not in disabled and elig.get("basis") == "adr_0005_revision":
            problems.append("unapproved_adr_revision")

        if enforce_admission:
            binding = _lookup_admission(context, e)
            if binding is None:
                problems.append("admission_binding_missing")
            else:
                if binding.get("reproducibility") != b.get("reproducibility"):
                    problems.append("admission_reproducibility_mismatch")
                bl = binding.get("teacher_license") or {}
                el = binding.get("entry_license") or {}
                if bl.get("scope") != (b.get("teacher_license") or {}).get("scope"):
                    problems.append("admission_teacher_license_mismatch")
                if el.get("scope") != (e.get("license") or {}).get("scope"):
                    problems.append("admission_entry_license_mismatch")

        if source.get("partition") in ("train", "development", "final"):
            parts.setdefault(e["cache_key"], set()).add(source["partition"])

    if "cross" not in disabled and any(len(p) > 1 for p in parts.values()):
        problems.append("cross_partition_blob")
    return sorted(set(problems))


def train_eligible(
    entry: Dict,
    records: List[Dict],
    context: Dict,
    expected_context_sha256: str,
    schema: Optional[Dict] = None,
    disabled: Tuple[str, ...] = (),
) -> bool:
    """Training admission: disk licenses/repro are untrusted hints (F11/F12)."""
    if "admission_validation" not in disabled and store_problems(
        records, context, expected_context_sha256, schema, disabled
    ):
        return False
    try:
        b = next(
            r
            for r in records
            if r.get("record_type") == "teacher_blob" and r["cache_key"] == entry["cache_key"]
        )
        if "intersection" in disabled:
            return bool(b["teacher_license"]["scope"]["train"])

        binding = _lookup_admission(context, entry)
        # Disk values are hints only — admission comes from trusted binding.
        if binding is not None:
            teacher_train = bool((binding.get("teacher_license") or {}).get("scope", {}).get("train"))
            entry_train = bool((binding.get("entry_license") or {}).get("scope", {}).get("train"))
            repro = binding.get("reproducibility", "unverified")
        else:
            # Fail-closed: no trusted binding → not eligible (ignore disk).
            teacher_train = False
            entry_train = False
            repro = "unverified"

        return bool(
            entry["provenance"]["upstream"]["eligibility"]["train"]
            and teacher_train
            and entry_train
            and repro != "unverified"
            and entry["source"]["partition"] == "train"
        )
    except (KeyError, TypeError, StopIteration):
        return False
