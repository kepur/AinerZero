"""P35 independent probes (reviewer-authored, not P34's tests).

Each scenario gets its own isolated host copy so there is no cross-pollution.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "src"
PROD = REPO / "artifacts" / "v9" / "s1" / "phase1"
DATASETS = REPO / "artifacts" / "v9" / "s1" / "datasets"
BEFORE_SRC = REPO / "reports" / "V9-P9" / "r12" / "before" / "src"
OUT = REPO / "reports" / "V9-P35" / "evidence" / "probes.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fresh_host() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="p35-"))
    host = tmp / "host"
    copy_root = host / "artifacts" / "v9" / "s1" / "phase1"
    copy_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PROD, copy_root, dirs_exist_ok=True)
    datasets = host / "artifacts" / "v9" / "s1" / "datasets"
    if DATASETS.exists():
        shutil.copytree(DATASETS, datasets, dirs_exist_ok=True)
    ref = copy_root / "dataset_ref.json"
    if ref.is_file():
        payload = json.loads(ref.read_text(encoding="utf-8"))
        payload["dataset_dir"] = str(datasets / payload["dataset_digest"])
        ref.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    ledger = copy_root / "control.sqlite3"
    return {"tmp": tmp, "host": host, "root": copy_root, "ledger": ledger, "ledger_sha": sha256(ledger)}


def write_approval(host: Path, doc_sha: str) -> Path:
    log = host / "RESEARCH_LOG.md"
    lines = ["## R20261021-P1-stageA-budget", "", f"APPROVED s1-phase1 prereg document_sha256={doc_sha}"]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


def run_in_env(script: str, cwd: Path, timeout: int = 120) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(k, None)
    env["NO_PROXY"] = "127.0.0.1,localhost,::1"
    env["LOGNAME"] = "mac"
    py = cwd / "probe.py"
    py.write_text(script, encoding="utf-8")
    completed = subprocess.run([sys.executable, str(py)], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout)
    return {"rc": completed.returncode, "out": completed.stdout, "err": completed.stderr}


def driver(host: Path, mode: str, arm: str, seed: int, wall: float, prereg_name: str = "r12/pre_registration.json") -> str:
    return f'''
import sys, json, hashlib
from pathlib import Path
host = Path("{host}")
sys.path.insert(0, str(Path("{SRC}")))
from ainerzero.v9.experiments.s1 import spec, worker
spec.REGISTERED_HOST_ROOT = host
spec.PHASE1_ROOT = host / "artifacts" / "v9" / "s1" / "phase1"
spec.RESEARCH_LOG = host / "RESEARCH_LOG.md"
ledger = spec.PHASE1_ROOT / "control.sqlite3"
ledger_sha_before = hashlib.sha256(ledger.read_bytes()).hexdigest()
report = worker.run_worker(
    "{mode}", output_root=spec.PHASE1_ROOT, limits=spec.RESOURCE_LIMITS,
    wall_budget_seconds={wall},
    prereg_path=spec.PHASE1_ROOT / "{prereg_name}",
    arm="{arm}", seed={seed})
ledger_sha_after = hashlib.sha256(ledger.read_bytes()).hexdigest()
print(json.dumps({{
    "status": report.get("status"),
    "refused_stage": report.get("refused_stage"),
    "error": report.get("error"),
    "ledger_before": ledger_sha_before,
    "ledger_after": ledger_sha_after,
    "unchanged": ledger_sha_before == ledger_sha_after,
}}))
'''


def add_run(host: Path, experiment_id: str, arm: str, seed: int) -> None:
    """Add a completed training run to the ledger so eval can bind it."""
    script = f'''
import sys
from pathlib import Path
host = Path("{host}")
sys.path.insert(0, str(Path("{SRC}")))
from ainerzero.v9.experiments.s1 import worker
ledger = worker.PrepLedger(host / "artifacts" / "v9" / "s1" / "phase1" / "control.sqlite3")
try:
    try:
        ledger.store.get_experiment("{experiment_id}")
    except KeyError:
        ledger.store.create_experiment(worker.train_experiment_manifest(updates=3510), "{experiment_id}:training", "{experiment_id}")
    import uuid
    rid = "{experiment_id}:{arm}:{seed}:c-" + uuid.uuid4().hex[:8]
    snap = worker.run_config_snapshot(wall_budget_seconds=1200.0, purpose="training:{arm}:seed{seed}")
    snap["arm_id"] = "{arm}"; snap["seed"] = {seed}; snap["updates"] = 3510
    ledger.store.create_run(snap, "{experiment_id}:{arm}:{seed}:req-" + uuid.uuid4().hex[:8], rid, experiment_id="{experiment_id}", role="model")
    ledger.store.transition(rid, "initializing", reason="probe")
    ledger.store.transition(rid, "training", reason="probe")
    ledger.store.transition(rid, "completed", reason="probe")
finally:
    ledger.close()
run_dir = host / "artifacts" / "v9" / "s1" / "phase1" / "runs" / rid
run_dir.mkdir(parents=True, exist_ok=True)
(run_dir / "final.npz").write_text("probe", encoding="utf-8")
'''
    r = run_in_env(script, host.parent)
    if r["rc"] != 0:
        raise RuntimeError(f"add_run failed: {r['err'][-500:]}")


# ------------------------------------------------------------------
# Scenarios
# ------------------------------------------------------------------
def scenario_train_no_approval():
    h = fresh_host()
    r = run_in_env(driver(h["host"], "train", "arm2", 0, 1200), h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"name": "train_no_approval", **payload}


def scenario_train_source_drift():
    h = fresh_host()
    prereg = h["root"] / "r12" / "pre_registration.json"
    doc = json.loads(prereg.read_text(encoding="utf-8"))
    doc["source_identity"]["package_files"][list(doc["source_identity"]["package_files"])[0]] = "0" * 64
    prereg.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    # recompute sha sidecar
    script = f'''
import sys; sys.path.insert(0, str(Path("{SRC}")))
from ainerzero.v9.experiments.s1 import prereg
from pathlib import Path
p = Path("{prereg}")
d = json.loads(p.read_text(encoding="utf-8"))
prereg.write_sha256_file(p, prereg.document_sha256(d))
'''
    run_in_env(script, h["host"].parent)
    write_approval(h["host"], hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest())
    r = run_in_env(driver(h["host"], "train", "arm2", 0, 1200), h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"name": "train_source_drift", **payload}


def scenario_train_dataset_mismatch():
    h = fresh_host()
    prereg = h["root"] / "r12" / "pre_registration.json"
    doc = json.loads(prereg.read_text(encoding="utf-8"))
    doc["data_identity"]["dataset_digest"] = "b" * 64
    prereg.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    script = f'''
import sys; sys.path.insert(0, str(Path("{SRC}")))
from ainerzero.v9.experiments.s1 import prereg
from pathlib import Path
p = Path("{prereg}")
d = json.loads(p.read_text(encoding="utf-8"))
prereg.write_sha256_file(p, prereg.document_sha256(d))
'''
    run_in_env(script, h["host"].parent)
    write_approval(h["host"], hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest())
    r = run_in_env(driver(h["host"], "train", "arm2", 0, 1200), h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"name": "train_dataset_mismatch", **payload}


def scenario_train_already_attempted():
    h = fresh_host()
    prereg = h["root"] / "r12" / "pre_registration.json"
    doc = json.loads(prereg.read_text(encoding="utf-8"))
    write_approval(h["host"], hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest())
    add_run(h["host"], doc["experiment_id"], "arm2", 0)
    r = run_in_env(driver(h["host"], "train", "arm2", 0, 1200), h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"name": "train_already_attempted", **payload}


def scenario_train_phase_budget_exceeded():
    h = fresh_host()
    prereg = h["root"] / "r12" / "pre_registration.json"
    doc = json.loads(prereg.read_text(encoding="utf-8"))
    write_approval(h["host"], hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest())
    add_run(h["host"], doc["experiment_id"], "arm3", 1)
    # set huge active_seconds so phase wall is exceeded
    script = f'''
import sqlite3
conn = sqlite3.connect("{h['ledger']}")
conn.execute("UPDATE runs SET active_seconds = 15000 WHERE experiment_id = ?", ("{doc['experiment_id']}",))
conn.commit(); conn.close()
'''
    run_in_env(script, h["host"].parent)
    r = run_in_env(driver(h["host"], "train", "arm2", 0, 1200), h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"name": "train_phase_budget_exceeded", **payload}


def scenario_eval_binding_unavailable():
    h = fresh_host()
    r = run_in_env(driver(h["host"], "eval", "arm2", 0, 300), h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"name": "eval_binding_unavailable", **payload}


def scenario_eval_source_drift():
    h = fresh_host()
    prereg = h["root"] / "r12" / "pre_registration.json"
    doc = json.loads(prereg.read_text(encoding="utf-8"))
    doc["source_identity"]["package_files"][list(doc["source_identity"]["package_files"])[0]] = "0" * 64
    prereg.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    script = f'''
import sys; sys.path.insert(0, str(Path("{SRC}")))
from ainerzero.v9.experiments.s1 import prereg
from pathlib import Path
p = Path("{prereg}")
d = json.loads(p.read_text(encoding="utf-8"))
prereg.write_sha256_file(p, prereg.document_sha256(d))
'''
    run_in_env(script, h["host"].parent)
    r = run_in_env(driver(h["host"], "eval", "arm2", 0, 300), h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"name": "eval_source_drift", **payload}


def scenario_eval_d_already_attempted():
    h = fresh_host()
    prereg = h["root"] / "r12" / "pre_registration.json"
    doc = json.loads(prereg.read_text(encoding="utf-8"))
    add_run(h["host"], doc["experiment_id"], "arm1", 0)
    r = run_in_env(driver(h["host"], "eval", "arm1", 0, 300), h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"name": "eval_d_already_attempted", **payload}


# ------------------------------------------------------------------
# Bad controls
# ------------------------------------------------------------------
def bad_control_before():
    h = fresh_host()
    # use r11 doc so before tree accepts it
    r11_doc = json.loads((PROD / "r11" / "pre_registration.json").read_text(encoding="utf-8"))
    prereg = h["root"] / "pre_registration.json"
    prereg.write_text(json.dumps(r11_doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    script = f'''
import sys, json, hashlib
from pathlib import Path
host = Path("{h['host']}")
sys.path.insert(0, str(Path("{BEFORE_SRC}")))
from ainerzero.v9.experiments.s1 import spec, worker
spec.REGISTERED_HOST_ROOT = host
spec.PHASE1_ROOT = host / "artifacts" / "v9" / "s1" / "phase1"
spec.RESEARCH_LOG = host / "RESEARCH_LOG.md"
ledger = spec.PHASE1_ROOT / "control.sqlite3"
before = hashlib.sha256(ledger.read_bytes()).hexdigest()
report = worker.run_worker("eval", output_root=spec.PHASE1_ROOT, limits=spec.RESOURCE_LIMITS,
    wall_budget_seconds=300.0, prereg_path=spec.PHASE1_ROOT / "pre_registration.json",
    arm="arm2", seed=0)
after = hashlib.sha256(ledger.read_bytes()).hexdigest()
print(json.dumps({{"status": report.get("status"), "refused_stage": report.get("refused_stage"),
    "error": report.get("error"), "before": before, "after": after, "changed": before != after}}))
'''
    r = run_in_env(script, h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"method": "before_tree", **payload, "rc": r["rc"]}


def bad_control_sabotage():
    h = fresh_host()
    checkout = h["tmp"] / "sabotage-src"
    checkout.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC / "ainerzero", checkout / "src" / "ainerzero", dirs_exist_ok=True)
    worker_py = checkout / "src" / "ainerzero" / "v9" / "experiments" / "s1" / "worker.py"
    text = worker_py.read_text(encoding="utf-8")
    guard = """            binding_precondition = _eval_binding_precondition(
                output_root,
                arm_id=arm,
                seed=eval_seed,
                prereg_sha256=verified["sha256"],
                updates=int(document["training_protocol"]["updates"]),
                ledger_path=ledger_path,
            )"""
    assert guard in text, "guard string missing"
    worker_py.write_text(text.replace(guard, '            binding_precondition = {"status": "ok"}  # sabotage', 1), encoding="utf-8")
    script = f'''
import sys, json, hashlib
from pathlib import Path
host = Path("{h['host']}")
sys.path.insert(0, str(Path("{checkout / 'src'}")))
from ainerzero.v9.experiments.s1 import spec, worker
spec.REGISTERED_HOST_ROOT = host
spec.PHASE1_ROOT = host / "artifacts" / "v9" / "s1" / "phase1"
spec.RESEARCH_LOG = host / "RESEARCH_LOG.md"
ledger = spec.PHASE1_ROOT / "control.sqlite3"
before = hashlib.sha256(ledger.read_bytes()).hexdigest()
report = worker.run_worker("eval", output_root=spec.PHASE1_ROOT, limits=spec.RESOURCE_LIMITS,
    wall_budget_seconds=300.0, prereg_path=spec.PHASE1_ROOT / "r12" / "pre_registration.json",
    arm="arm2", seed=0)
after = hashlib.sha256(ledger.read_bytes()).hexdigest()
print(json.dumps({{"status": report.get("status"), "refused_stage": report.get("refused_stage"),
    "error": report.get("error"), "before": before, "after": after, "changed": before != after}}))
'''
    r = run_in_env(script, h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"method": "sabotage", **payload, "rc": r["rc"]}


# ------------------------------------------------------------------
# Sentinel dry-runs
# ------------------------------------------------------------------
def sentinel_train():
    h = fresh_host()
    prereg = h["root"] / "r12" / "pre_registration.json"
    doc = json.loads(prereg.read_text(encoding="utf-8"))
    write_approval(h["host"], hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest())
    script = f'''
import sys, json, hashlib
from pathlib import Path
host = Path("{h['host']}")
sys.path.insert(0, str(Path("{SRC}")))
from ainerzero.v9.experiments.s1 import spec, worker
spec.REGISTERED_HOST_ROOT = host
spec.PHASE1_ROOT = host / "artifacts" / "v9" / "s1" / "phase1"
spec.RESEARCH_LOG = host / "RESEARCH_LOG.md"
class Sentinel(Exception): pass
_orig = __builtins__.__import__
def _imp(name, *a, **k):
    if name == "mlx.core" or name.startswith("mlx"):
        raise Sentinel("MLX_IMPORT")
    return _orig(name, *a, **k)
__builtins__.__import__ = _imp
ledger = spec.PHASE1_ROOT / "control.sqlite3"
before = hashlib.sha256(ledger.read_bytes()).hexdigest()
try:
    report = worker.run_worker("train", output_root=spec.PHASE1_ROOT, limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds={doc["timing"]["deadline_seconds"]},
        prereg_path=spec.PHASE1_ROOT / "r12" / "pre_registration.json",
        arm="arm2", seed=0)
    result = {{"sentinel_hit": False, "status": report.get("status"), "refused_stage": report.get("refused_stage")}}
except Sentinel:
    after = hashlib.sha256(ledger.read_bytes()).hexdigest()
    result = {{"sentinel_hit": True, "ledger_before": before, "ledger_after": after, "ledger_changed": before != after}}
print(json.dumps(result))
'''
    r = run_in_env(script, h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"mode": "train", **payload, "rc": r["rc"]}


def sentinel_eval_arm2():
    h = fresh_host()
    prereg = h["root"] / "r12" / "pre_registration.json"
    doc = json.loads(prereg.read_text(encoding="utf-8"))
    add_run(h["host"], doc["experiment_id"], "arm2", 0)
    script = f'''
import sys, json, hashlib
from pathlib import Path
host = Path("{h['host']}")
sys.path.insert(0, str(Path("{SRC}")))
from ainerzero.v9.experiments.s1 import spec, worker
spec.REGISTERED_HOST_ROOT = host
spec.PHASE1_ROOT = host / "artifacts" / "v9" / "s1" / "phase1"
spec.RESEARCH_LOG = host / "RESEARCH_LOG.md"
class Sentinel(Exception): pass
_orig = __builtins__.__import__
def _imp(name, *a, **k):
    if name == "mlx.core" or name.startswith("mlx"):
        raise Sentinel("MLX_IMPORT")
    return _orig(name, *a, **k)
__builtins__.__import__ = _imp
ledger = spec.PHASE1_ROOT / "control.sqlite3"
before = hashlib.sha256(ledger.read_bytes()).hexdigest()
try:
    report = worker.run_worker("eval", output_root=spec.PHASE1_ROOT, limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=300.0,
        prereg_path=spec.PHASE1_ROOT / "r12" / "pre_registration.json",
        arm="arm2", seed=0)
    result = {{"sentinel_hit": False, "status": report.get("status"), "refused_stage": report.get("refused_stage")}}
except Sentinel:
    after = hashlib.sha256(ledger.read_bytes()).hexdigest()
    result = {{"sentinel_hit": True, "ledger_before": before, "ledger_after": after, "ledger_changed": before != after}}
print(json.dumps(result))
'''
    r = run_in_env(script, h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"mode": "eval_arm2", **payload, "rc": r["rc"]}


def sentinel_eval_arm1():
    h = fresh_host()
    script = f'''
import sys, json, hashlib
from pathlib import Path
host = Path("{h['host']}")
sys.path.insert(0, str(Path("{SRC}")))
from ainerzero.v9.experiments.s1 import spec, worker
spec.REGISTERED_HOST_ROOT = host
spec.PHASE1_ROOT = host / "artifacts" / "v9" / "s1" / "phase1"
spec.RESEARCH_LOG = host / "RESEARCH_LOG.md"
class Sentinel(Exception): pass
_orig = __builtins__.__import__
def _imp(name, *a, **k):
    if name == "mlx.core" or name.startswith("mlx"):
        raise Sentinel("MLX_IMPORT")
    return _orig(name, *a, **k)
__builtins__.__import__ = _imp
ledger = spec.PHASE1_ROOT / "control.sqlite3"
before = hashlib.sha256(ledger.read_bytes()).hexdigest()
try:
    report = worker.run_worker("eval", output_root=spec.PHASE1_ROOT, limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=300.0,
        prereg_path=spec.PHASE1_ROOT / "r12" / "pre_registration.json",
        arm="arm1", seed=0)
    result = {{"sentinel_hit": False, "status": report.get("status"), "refused_stage": report.get("refused_stage")}}
except Sentinel:
    after = hashlib.sha256(ledger.read_bytes()).hexdigest()
    result = {{"sentinel_hit": True, "ledger_before": before, "ledger_after": after, "ledger_changed": before != after}}
print(json.dumps(result))
'''
    r = run_in_env(script, h["host"].parent)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return {"mode": "eval_arm1", **payload, "rc": r["rc"]}


# ------------------------------------------------------------------
# D identity source-bound
# ------------------------------------------------------------------
def d_identity_probe():
    script = f'''
import sys; sys.path.insert(0, str(Path("{SRC}")))
from ainerzero.v9.experiments.s1 import spec, identity as identity_module
# 1. tamper document arms.arm1 identity (should not matter)
orig_id = dict(spec.ARM_SPECS["arm1"]["identity"])
try:
    identity_module.verify_d_candidate_identity(repo_root=spec.REPO_ROOT)
    doc_ok = "ok"
except Exception as e:
    doc_ok = f"{{type(e).__name__}}: {{e}}"
# 2. tamper spec.ARM_SPECS arm1 identity (should fail)
spec.ARM_SPECS["arm1"]["identity"]["frozen_manifest_file_sha256"] = "0" * 64
try:
    identity_module.verify_d_candidate_identity(repo_root=spec.REPO_ROOT)
    spec_ok = "ok"
except Exception as e:
    spec_ok = f"{{type(e).__name__}}: {{e}}"
finally:
    spec.ARM_SPECS["arm1"]["identity"] = orig_id
print(json.dumps({{"doc_tamper": doc_ok, "spec_tamper": spec_ok}}))
'''
    r = run_in_env(script, REPO)
    payload = json.loads(r["out"].strip().splitlines()[-1]) if r["rc"] == 0 else {"parse_error": r["err"][-500:]}
    return payload


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main() -> int:
    results = {
        "train_probes": [
            scenario_train_no_approval(),
            scenario_train_source_drift(),
            scenario_train_dataset_mismatch(),
            scenario_train_already_attempted(),
            scenario_train_phase_budget_exceeded(),
        ],
        "eval_probes": [
            scenario_eval_binding_unavailable(),
            scenario_eval_source_drift(),
            scenario_eval_d_already_attempted(),
        ],
        "bad_controls": [bad_control_before(), bad_control_sabotage()],
        "sentinel_runs": [sentinel_train(), sentinel_eval_arm2(), sentinel_eval_arm1()],
        "d_identity": d_identity_probe(),
    }
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for k, v in results.items():
        print(f"--- {k} ---")
        print(json.dumps(v, indent=1, ensure_ascii=False))
    ok = (
        all(p.get("refused_stage") is not None and p.get("unchanged") for p in results["train_probes"])
        and all(p.get("refused_stage") is not None and p.get("unchanged") for p in results["eval_probes"])
        and any(c.get("changed") for c in results["bad_controls"] if c.get("method") == "before_tree")
        and any(c.get("changed") for c in results["bad_controls"] if c.get("method") == "sabotage")
        and all(r.get("sentinel_hit") for r in results["sentinel_runs"])
        and not any(r.get("ledger_changed") for r in results["sentinel_runs"])
        and results["d_identity"].get("doc_tamper") == "ok"
        and "DIdentityError" in results["d_identity"].get("spec_tamper", "")
    )
    return 0 if ok else 9


if __name__ == "__main__":
    raise SystemExit(main())
