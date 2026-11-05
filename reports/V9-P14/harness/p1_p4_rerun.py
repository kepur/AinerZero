"""V9.P12 self-written counterexamples for the P9 r3 rejection reasons P-1..P-4.

Written by the P12 reviewer (not a P9 author).  Every case is built and run by
this reviewer inside /private/tmp copies; the real tree is only read.

P-1 (train must only ever read spec.RESEARCH_LOG):
  P1-a  --research-log -> executor-writable forged log carrying the exact line
  P1-b  --research-log -> symlink to a *copy* of the canonical log (copy carries
        the exact line in its registered section)
  P1-c  control: --research-log -> symlink to the canonical log itself (same
        file, different path spelling) must still be released (exit 0)
  P1-d  worker side: direct worker invocation with a relocated log must refuse
P-2 (bound source files must still hash to the frozen digests):
  P2-a  drift data.py (one appended comment line), approval line present
  P2-b  drift cli.py (one appended comment line), approval line present
  P2-c  worker side: direct worker invocation inside the drifted tree
P-3 (the run root's dataset must equal data_identity.dataset_digest):
  P3-a  tampered manifest (counts changed) with the reference's manifest_sha256
        rewritten to match the tampered file
  P3-b  tampered data file (packets/train.jsonl + 1 byte), manifest untouched
  P3-c  worker side: direct worker invocation against the tampered dataset
P-4 (the approval line only counts inside the registered section):
  P4-a  line inside another section
  P4-b  line inside a fenced code block within the section
  P4-c  line inside a blockquote within the section
  P4-d  two qualifying lines inside the section
  P4-e  the registered section heading renamed (no such section)

Expectation: every counterexample is refused (exit 3 at the documented stage);
only the P1-c control may pass.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
ROOT = Path("/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/p12run/p1p4")
TREE = Path("/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/p12run/sandbox")
SITE = Path("/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/p12run/site")
PY = str(REAL / ".venv-ainerzero" / "bin" / "python")
OUT = REAL / "reports" / "V9-P14" / "evidence"
DOC = REAL / "artifacts" / "v9" / "s1" / "phase1" / "pre_registration.json"
DATASET_REF = REAL / "artifacts" / "v9" / "s1" / "phase1" / "dataset_ref.json"
DATASET_DIR = REAL / "artifacts" / "v9" / "s1" / "datasets" / (
    "8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26")
PREFIX = "APPROVED s1-phase1 prereg document_sha256="
SECTION = "## R20261021-P1-stageA-budget：S1 第一阶段训练预算登记（p12 sandbox）"
LIMITS_JSON = json.dumps({
    "process_memory_gib": 8.0, "mlx_memory_gib": 4.0, "system_reserve_gib": 16.0,
    "swap_growth_gib": 1.0, "training_duty_cycle": 0.25, "disk_min_free_gib": 50.0,
}, sort_keys=True)



SITECUSTOMIZE = '''"""P14 reviewer shim: replace worker._train, edit no bound file.

``python -m pkg.mod`` executes the module body as ``__main__`` (runpy), so a
plain ``import ...; module._train = ...`` patch is discarded.  The shim instead
intercepts the worker entry itself, imports the module normally, replaces
``_train`` and then calls ``worker.main()`` -- the same JSON-on-stdout contract.
"""
import sys

_ORIG = getattr(sys, "orig_argv", sys.argv)
if _ORIG[1:3] == ["-m", "ainerzero.v9.experiments.s1.worker"]:
    from ainerzero.v9.experiments.s1 import worker as _w

    _w._train = lambda *a, **k: {
        "stub": "reviewer_stub_no_training",
        "updates": 0,
        "status": "completed",
        "arm_id": "arm2",
        "seed": 0,
        "wall_seconds": 0.01,
    }
    raise SystemExit(_w.main(_ORIG[3:]))
'''


def make_sitecustomize() -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")


def canonical_sha(document: dict) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_log(path: Path, *extra: str) -> Path:
    body = "# RESEARCH_LOG copy (p12 reviewer sandbox)\n\n" + SECTION + "\n\n"
    body += "- 预算与资源线：进程 8 GiB、MLX 4 GiB、系统余量 16 GiB、占空比 0.25。\n"
    body += "\n".join(extra) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def clone_tree(dst: Path, drift_rel: str | None = None) -> Path:
    """A sandbox tree copy; optionally append one comment line to a bound file."""
    if dst.exists():
        shutil.rmtree(dst)
    subprocess.run(["rsync", "-a", f"{TREE}/src/", f"{dst}/src/"], check=True)
    subprocess.run(["rsync", "-a", f"{TREE}/RESEARCH_LOG.md", f"{dst}/RESEARCH_LOG.md"], check=True)
    (dst / "artifacts" / "locks").mkdir(parents=True, exist_ok=True)
    (dst / "artifacts" / "v9" / "s1").mkdir(parents=True, exist_ok=True)
    (dst / "artifacts" / "v9" / "s1" / "datasets").symlink_to(
        REAL / "artifacts" / "v9" / "s1" / "datasets")
    subprocess.run(["find", str(dst / "src"), "-name", "__pycache__", "-type", "d",
                    "-exec", "rm", "-rf", "{}", "+"], check=False)
    if drift_rel is not None:
        target = dst / drift_rel
        target.write_text(target.read_text(encoding="utf-8") + "\n# p12 drift marker\n",
                          encoding="utf-8")
    return dst


def fresh_case(name: str, *, dataset_ref: dict | None = None) -> Path:
    case = ROOT / name
    if case.exists():
        shutil.rmtree(case)
    (case / "phase1").mkdir(parents=True)
    shutil.copy2(DOC, case / "phase1" / "pre_registration.json")
    shutil.copy2(DOC.with_suffix(".json.sha256"), case / "phase1" / "pre_registration.json.sha256")
    ref = dataset_ref if dataset_ref is not None else json.loads(DATASET_REF.read_text())
    (case / "phase1" / "dataset_ref.json").write_text(
        json.dumps(ref, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return case


def run_cli(tree: Path, case: Path, log: Path | None) -> dict:
    command = [
        PY, "-m", "ainerzero.cli", "s1-phase1", "--mode", "train",
        "--arm", "arm2", "--seed", "0",
        "--output-root", str(case / "phase1"),
        "--prereg", str(case / "phase1" / "pre_registration.json"),
    ]
    if log is not None:
        command += ["--research-log", str(log)]
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": f"{tree / 'src'}:{SITE}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": "/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/p12run",
    }
    proc = subprocess.run(command, cwd=str(tree), capture_output=True, text=True, timeout=600, env=env)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = {"unparsed_stdout": proc.stdout[-1500:]}
    approval = report.get("approval") or {}
    return {
        "exit_code": proc.returncode,
        "stage": report.get("stage") or report.get("refused_stage") or report.get("status"),
        "status": report.get("status"),
        "approval_reasons": approval.get("reasons"),
        "source_binding_status": (report.get("source_binding") or {}).get("status"),
        "drifted": (report.get("source_binding") or {}).get("drifted"),
        "dataset_status": (report.get("dataset") or {}).get("status"),
        "dataset_reason": (report.get("dataset") or {}).get("reason"),
        "requested_research_log": report.get("requested_research_log"),
        "run_id": report.get("run_id"),
        "stderr_tail": proc.stderr.strip()[-300:],
    }


def run_worker_direct(tree: Path, case: Path, log: Path | None, *, use_stub: bool = False) -> dict:
    """Invoke the worker module itself (defence-in-depth side), no supervisor.

    ``use_stub`` adds the sitecustomize shim; the refusal cases never reach
    ``_train``, so they run without the shim and the process exit code is the
    worker's own ``worker_exit``.
    """
    command = [
        PY, "-m", "ainerzero.v9.experiments.s1.worker",
        "--mode", "train",
        "--arm", "arm2", "--seed", "0",
        "--output-root", str(case / "phase1"),
        "--limits-json", LIMITS_JSON,
        "--wall-budget-seconds", "60",
        "--prereg", str(case / "phase1" / "pre_registration.json"),
    ]
    if log is not None:
        command += ["--research-log", str(log)]
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": f"{tree / 'src'}" + (f":{SITE}" if use_stub else ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": "/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/p12run",
    }
    proc = subprocess.run(command, cwd=str(tree), capture_output=True, text=True, timeout=600, env=env)
    try:
        report = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        report = {"unparsed_stdout": proc.stdout[-1500:]}
    return {
        "exit_code": proc.returncode,
        "status": report.get("status"),
        "refused_stage": report.get("refused_stage"),
        "worker_exit": report.get("worker_exit"),
        "message": (report.get("message") or "")[:200],
        "stderr_tail": proc.stderr.strip()[-300:],
    }


def main() -> int:
    make_sitecustomize()
    doc = json.loads(DOC.read_text(encoding="utf-8"))
    digest = canonical_sha(doc)
    line = PREFIX + digest
    results: list[dict] = []

    # ---------------- P-1 ----------------
    # canonical log reset with the exact line (needed by the control case and by
    # every P-2/P-3/P-4 case where approval must pass before the tested gate)
    reset = lambda tree: write_log(tree / "RESEARCH_LOG.md", line)  # noqa: E731

    # P1-a: forged log in an executor-writable location
    case = fresh_case("P1a_forged_log")
    reset(TREE)
    forged = write_log(ROOT / "P1a_forged" / "RESEARCH_LOG.md", line)
    r = run_cli(TREE, case, forged)
    r.update(id="P1-a", gate="P-1", label="--research-log 指向可写位置伪造的日志（内含完全一致的批准行）",
             expectation="refused exit 3 research_log_not_canonical")
    results.append(r)

    # P1-b: symlink to a *copy* of the canonical log (copy carries the exact line)
    case = fresh_case("P1b_symlink_copy")
    reset(TREE)
    copy_dir = ROOT / "P1b_copy"
    copy_dir.mkdir(parents=True, exist_ok=True)
    copy_log = copy_dir / "RESEARCH_LOG.md"
    shutil.copy2(TREE / "RESEARCH_LOG.md", copy_log)
    link = copy_dir / "log-link.md"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(copy_log)
    r = run_cli(TREE, case, link)
    r.update(id="P1-b", gate="P-1",
             label="--research-log 用符号链接指向 spec.RESEARCH_LOG 的副本（副本内有合格批准行）",
             expectation="refused exit 3 research_log_not_canonical",
             symlink_target=str(copy_log))
    results.append(r)

    # P1-c (control): symlink to the canonical log itself must still be released
    case = fresh_case("P1c_symlink_self")
    reset(TREE)
    link2 = ROOT / "P1c_link.md"
    if link2.is_symlink() or link2.exists():
        link2.unlink()
    link2.symlink_to(TREE / "RESEARCH_LOG.md")
    r = run_cli(TREE, case, link2)
    r.update(id="P1-c", gate="P-1 (control)",
             label="--research-log 用符号链接指向规范日志本体（resolve 后同一文件）",
             expectation="released exit 0 (same file, only the path spelling differs)")
    results.append(r)

    # P1-d: worker side, direct invocation with a relocated log
    case = fresh_case("P1d_worker")
    reset(TREE)
    forged2 = write_log(ROOT / "P1d_forged" / "RESEARCH_LOG.md", line)
    r = run_worker_direct(TREE, case, forged2)
    r.update(id="P1-d", gate="P-1 (worker side)",
             label="直接调 worker，--research-log 指向伪造日志",
             expectation="refused research_log_not_canonical")
    results.append(r)

    # ---------------- P-2 ----------------
    # NOTE: the drifted tree and the case root must be distinct directories
    # (the case root is rebuilt by fresh_case; reusing one path would delete
    # the tree and silently fall back to the real installation).
    for cid, rel, tree_name, case_name in (
        ("P2-a", "src/ainerzero/v9/experiments/s1/data.py", "P2a_tree", "P2a_case"),
        ("P2-b", "src/ainerzero/cli.py", "P2b_tree", "P2b_case"),
    ):
        tree = clone_tree(ROOT / tree_name, drift_rel=rel)
        case = fresh_case(case_name)
        reset(tree)
        r = run_cli(tree, case, None)
        r.update(id=cid, gate="P-2", label=f"改动绑定源文件后跑 train（{rel} 追加一行注释，批准行合格）",
                 expectation="refused exit 3 source_binding_drift")
        results.append(r)

    # P2-c: worker side inside the drifted tree
    tree = clone_tree(ROOT / "P2c_worker_drift", drift_rel="src/ainerzero/v9/experiments/s1/data.py")
    case = fresh_case("P2c_worker")
    reset(tree)
    r = run_worker_direct(tree, case, None)
    r.update(id="P2-c", gate="P-2 (worker side)",
             label="直接调 worker（data.py 已漂移）",
             expectation="refused source_binding_drift")
    results.append(r)

    # ---------------- P-3 ----------------
    ref0 = json.loads(DATASET_REF.read_text(encoding="utf-8"))
    manifest_path = DATASET_DIR / "dataset_manifest.json"
    manifest0 = json.loads(manifest_path.read_text(encoding="utf-8"))

    # P3-a: tampered manifest, reference's manifest_sha256 rewritten to match
    tamper_a = ROOT / "P3a_dataset" / ref0["dataset_digest"]
    tamper_a.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DATASET_DIR, tamper_a)
    manifest_a = json.loads(json.dumps(manifest0))
    manifest_a["counts"]["train_episodes"] = manifest_a["counts"]["train_episodes"] + 1
    (tamper_a / "dataset_manifest.json").write_text(
        json.dumps(manifest_a, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    ref_a = dict(ref0, dataset_dir=str(tamper_a), manifest_sha256=sha_file(tamper_a / "dataset_manifest.json"))
    case = fresh_case("P3a_manifest_tampered", dataset_ref=ref_a)
    reset(TREE)
    r = run_cli(TREE, case, None)
    r.update(id="P3-a", gate="P-3",
             label="改动数据集 manifest（counts+1）并把 dataset_ref 的 manifest_sha256 一并改写后跑 train",
             expectation="refused exit 3 dataset_identity_mismatch",
             tampered_manifest_train_episodes=manifest_a["counts"]["train_episodes"])
    results.append(r)

    # P3-b: tampered data file, manifest and reference untouched
    tamper_b = ROOT / "P3b_dataset" / ref0["dataset_digest"]
    tamper_b.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DATASET_DIR, tamper_b)
    with open(tamper_b / "packets" / "train.jsonl", "ab") as fh:
        fh.write(b"\n")
    ref_b = dict(ref0, dataset_dir=str(tamper_b))
    case = fresh_case("P3b_datafile_tampered", dataset_ref=ref_b)
    reset(TREE)
    r = run_cli(TREE, case, None)
    r.update(id="P3-b", gate="P-3",
             label="改动数据集数据文件（packets/train.jsonl 追加 1 字节），manifest 未动",
             expectation="refused exit 3 dataset_identity_mismatch")
    results.append(r)

    # P3-c: worker side against the tampered dataset
    case = fresh_case("P3c_worker", dataset_ref=ref_b)
    reset(TREE)
    r = run_worker_direct(TREE, case, None)
    r.update(id="P3-c", gate="P-3 (worker side)",
             label="直接调 worker（数据集文件已被改）",
             expectation="refused dataset_identity_mismatch")
    results.append(r)

    # ---------------- P-4 ----------------
    p4_cases = [
        ("P4-a", "P4a_other_section", "批准行写在另一个小节里",
         lambda p: write_log(p, *[]) if False else _other_section_log(p, line), None),
        ("P4-b", "P4b_fenced", "批准行写在注册节的围栏代码块里",
         lambda p: write_log(p, "格式示例：", "", "```", line, "```"), None),
        ("P4-c", "P4c_blockquote", "批准行写在注册节的引用块里",
         lambda p: write_log(p, "> 别人引用过的行：", f"> {line}"), None),
        ("P4-d", "P4d_two_lines", "注册节里同时有两条合格批准行",
         lambda p: write_log(p, line, "", line), None),
        ("P4-e", "P4e_renamed_heading", "注册节标题被改名（节不存在）",
         lambda p: _renamed_heading_log(p, line), None),
    ]
    for cid, name, label, writer, _ in p4_cases:
        case = fresh_case(name)
        log = writer(TREE / "RESEARCH_LOG.md")
        r = run_cli(TREE, case, None)
        r.update(id=cid, gate="P-4", label=label,
                 expectation="refused exit 3 (preregistration_not_approved, P-4)")
        results.append(r)

    (OUT / "p1-p4-counterexamples-rerun-p14.json").write_text(
        json.dumps({"harness": "reports/V9-P12/harness/p1_p4_counterexamples.py",
                    "frozen_document_sha256": digest,
                    "reviewer": "p12 self-written counterexamples",
                    "cases": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in results:
        print(f"{r['id']:5s} exit={r['exit_code']} stage={r.get('stage') or r.get('refused_stage')}  {r['label']}")
    return 0


def _other_section_log(path: Path, line: str) -> Path:
    body = ("# RESEARCH_LOG copy (p12 reviewer sandbox)\n\n"
            "## D20261012-01：别的条目\n\n"
            "- 预算与资源线：进程 8 GiB、MLX 4 GiB、系统余量 16 GiB、占空比 0.25。\n"
            + line + "\n\n"
            + SECTION + "\n\n- 本节为空。\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _renamed_heading_log(path: Path, line: str) -> Path:
    body = ("# RESEARCH_LOG copy (p12 reviewer sandbox)\n\n"
            "## R20261021-P1-stageA-budget-renamed：被改名的小节\n\n"
            "- 预算与资源线：进程 8 GiB、MLX 4 GiB、系统余量 16 GiB、占空比 0.25。\n"
            + line + "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


if __name__ == "__main__":
    sys.exit(main())
