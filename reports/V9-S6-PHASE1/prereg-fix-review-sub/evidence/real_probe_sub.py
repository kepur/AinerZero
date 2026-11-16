"""P262-sub: run the REAL builder CLI (make_prereg.main via runpy) on the REAL probe report inside an
ISOLATED clone (git clone of HEAD a33d34b + byte-identical copies of the three reviewed files, the real
report and the real artifacts/v9/s6/phase1/probe closure). Optionally tamper the copy first.

usage: python -B real_probe_sub.py <case_root> <tamper-name>

Prints: tamper applied, MLX blocker state, builder outcome (exception type/message or written), whether the
output file exists, every write-mode open/rename/remove/mkdir seen by an audit hook during the builder,
subprocess argv seen, and the whole-tree (including .git) SHA comparison before/after the builder.
Never touches the live repository: every path is under <case_root>.
"""
import hashlib
import importlib.abc
import json
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True


class NoMLX(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mlx" or fullname.startswith("mlx."):
            raise RuntimeError("P262-sub FORBIDDEN MLX IMPORT: " + fullname)


sys.meta_path.insert(0, NoMLX())
root = Path(sys.argv[1]).resolve()
tamper = sys.argv[2]
LIVE = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
assert not root.is_relative_to(LIVE), "case root must not be inside the live repository"
REPORT = root / "reports/V9-S6-PHASE1/probe/EVAL-probe.json"
RAW = root / "artifacts/v9/s6/phase1/probe"
OUT = root / "PREREG-candidate.json"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(p):
    return json.loads(Path(p).read_text())


def dump(p, v):
    Path(p).write_text(json.dumps(v, ensure_ascii=False, indent=1))


def edit_report(fn):
    pr = load(REPORT)
    fn(pr)
    dump(REPORT, pr)


def rebind_cell(cell):
    edit_report(lambda p: p["cells_sha256"].__setitem__(cell, sha(RAW / "cells" / cell / "cell.json")))


def rebind_eval(name):
    edit_report(lambda p: p["files_sha256"].__setitem__(name, sha(RAW / "eval-s6p1-probe" / name)))


def t_coordinated_train(sec_scale):
    # coordinated rewrite of every cell.json seconds/timings, the ledger, and the report bindings
    led = load(RAW / "train-ledger.json")
    for arm in ("R", "E", "Z", "T", "P", "G"):
        cell = arm + "-r0"
        p = RAW / "cells" / cell / "cell.json"
        rec = load(p)
        rec["seconds"] = round(rec["seconds"] * sec_scale, 1)
        for t in rec["timings"]:
            t["train_s"] = round(t["train_s"] * sec_scale, 2)
            t["select_s"] = round(t["select_s"] * sec_scale, 2)
        p.write_text(json.dumps(rec, sort_keys=True))
        for c in led[0]["cells"]:
            if c["arm"] == arm:
                c["seconds"] = rec["seconds"]
        edit_report(lambda pr, cell=cell, s=rec["seconds"]: pr["train_seconds"].__setitem__(cell, s))
        rebind_cell(cell)
    dump(RAW / "train-ledger.json", led)


def t_verify_raw(fn):
    p = RAW / "eval-s6p1-probe/verify.json"
    v = load(p)
    fn(v)
    p.write_text(json.dumps(v, indent=1))
    rebind_eval("verify.json")
    edit_report(lambda pr: pr.__setitem__("verify", v))


TAMPERS = {
    "none": lambda: None,
    # --- budget-input bypass attempts on the report's own timing fields ---
    "verify-616-to-515": lambda: edit_report(lambda p: p.__setitem__("verify_seconds", 515.0)),
    "verify-616-to-516": lambda: edit_report(lambda p: p.__setitem__("verify_seconds", 516.0)),
    "verify-616-to-400-and-elapsed": lambda: edit_report(lambda p: p.update(verify_seconds=400.0, elapsed_s=430.0)),
    "eval-19.6-to-1": lambda: edit_report(lambda p: p.__setitem__("eval_seconds", 1.0)),
    "verify-zero": lambda: edit_report(lambda p: p.__setitem__("verify_seconds", 0)),
    "verify-negative": lambda: edit_report(lambda p: p.__setitem__("verify_seconds", -616.0)),
    "verify-string": lambda: edit_report(lambda p: p.__setitem__("verify_seconds", "616.0")),
    "verify-key-removed": lambda: edit_report(lambda p: p.pop("verify_seconds")),
    "elapsed-over-probe-cap": lambda: edit_report(lambda p: p.__setitem__("elapsed_s", 3600.5)),
    # --- cell set / timing / sets tampering ---
    "report-drop-cell-G": lambda: edit_report(lambda p: (p["cells_sha256"].pop("G-r0"), p["train_seconds"].pop("G-r0"))),
    "report-extra-cells-r999": lambda: edit_report(lambda p: [p["train_seconds"].__setitem__(a + "-r999", 1.0) for a in "REZTPG"]),
    "report-train-seconds-lowered": lambda: edit_report(lambda p: p["train_seconds"].__setitem__("P-r0", 100.0)),
    "report-sets-final-G-reps-1": lambda: edit_report(lambda p: p["sets"]["final"]["reps"].__setitem__("G", 1)),
    "report-sets-final-eval-limit-9999": lambda: edit_report(lambda p: p["sets"]["final"].__setitem__("eval_limit_s", 9999)),
    "report-sets-final-worlds-halved": lambda: edit_report(lambda p: p["sets"]["final"].__setitem__("worlds", [100, 50])),
    "report-config-probe-worlds-doubled": lambda: edit_report(lambda p: (p["config"].__setitem__("worlds", [100, 50]), p["sets"]["probe"].__setitem__("worlds", [100, 50]))),
    "raw-cell-dir-removed-G": lambda: __import__("shutil").rmtree(RAW / "cells/G-r0"),
    "coordinated-train-x0.5": lambda: t_coordinated_train(0.5),
    # --- F1 / F2 class on the real closure ---
    "raw-verify-retrain-false-rebound": lambda: t_verify_raw(lambda v: v["retrain"]["P-r0-n0"].__setitem__("passed", False)),
    "report-verify-summary-only": lambda: edit_report(lambda p: p.__setitem__("verify", {"passed": True})),
    "report-gates-emptied": lambda: edit_report(lambda p: p["result"].__setitem__("gates", {})),
    "ledger-old-code": lambda: (lambda led: (led[0].__setitem__("code_manifest_sha256", "0" * 64), dump(RAW / "train-ledger.json", led)))(load(RAW / "train-ledger.json")),
    "ledger-open": lambda: (lambda led: (led[0].__setitem__("closed", False), dump(RAW / "train-ledger.json", led)))(load(RAW / "train-ledger.json")),
    # --- P259 F1-F3 defects transplanted one at a time onto the COMPLETE real report/closure ---
    "F1a-no-artifacts": lambda: __import__("shutil").rmtree(root / "artifacts"),
    "F1b-invalid-empty-gates-summary-verify": lambda: edit_report(lambda p: p.update(result={"valid": False, "gates": {}}, verify={"passed": True})),
    "F1c-report-replay-E-false": lambda: edit_report(lambda p: p["verify"]["replay"]["E-r0"].__setitem__("passed", False)),
    "F1c-raw-replay-E-false-rebound": lambda: t_verify_raw(lambda v: v["replay"]["E-r0"].__setitem__("passed", False)),
    "F1d-raw-passed-string-rebound": lambda: t_verify_raw(lambda v: v.__setitem__("passed", "false")),
    "F1e-schema-missing": lambda: edit_report(lambda p: p.pop("schema")),
    "F1e-git-head-null": lambda: edit_report(lambda p: p.__setitem__("git_head", None)),
    "F1e-git-head-unknown-commit": lambda: edit_report(lambda p: p.__setitem__("git_head", "1" * 40)),
    "F1e-third-party-mlx-0.32.2": lambda: edit_report(lambda p: p["third_party"].__setitem__("mlx", "0.32.2")),
    "F2-ledger-git-head-unknown-commit": lambda: (lambda led: (led[0].__setitem__("git_head", "1" * 40), dump(RAW / "train-ledger.json", led)))(load(RAW / "train-ledger.json")),
    "F2-ledger-extra-row-old-code": lambda: (lambda led: (led.append({**led[0], "start": led[0]["start"] - 100, "last_beat": led[0]["start"] - 50, "cells": [], "code_manifest_sha256": "f" * 64}), dump(RAW / "train-ledger.json", led)))(load(RAW / "train-ledger.json")),
    "F2-report-code-sha-other": lambda: edit_report(lambda p: p.__setitem__("code_manifest_sha256", "f" * 64)),
    "F3-negative-times": lambda: edit_report(lambda p: (p.__setitem__("train_seconds", {c: -500 for c in p["train_seconds"]}), p.update(verify_seconds=-100, eval_seconds=-100))),
    "F3-zero-times": lambda: edit_report(lambda p: (p.__setitem__("train_seconds", {c: 0 for c in p["train_seconds"]}), p.update(verify_seconds=0, eval_seconds=0))),
    "F3-extra-r999-cells-zero": lambda: edit_report(lambda p: [d.__setitem__(a + "-r999", 0) for d in (p["train_seconds"], p["cells_sha256"]) for a in "REZTPG"]),
    "F3-nan-verify": lambda: REPORT.write_text(REPORT.read_text().replace('"verify_seconds": 616.0', '"verify_seconds": NaN')),
    "F3-inf-eval": lambda: REPORT.write_text(REPORT.read_text().replace('"eval_seconds": 19.6', '"eval_seconds": Infinity')),
}


def tree():
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


P259_CASES = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-PHASE1/prefreeze-review-codex/cases")


def p259(spec):
    """'p259:<case-stem>:<raw|norm>[:noart]' - put P259's ORIGINAL counterexample report at the probe path.
    norm: only third_party is set to this environment's versions so that the refusal must come from the
    defect the case was built for (raw keeps P259's mlx '0.32.2'). noart: delete the raw artifacts first
    (P259 F1 baseline 'no cell/verify/errors files at all')."""
    _, stem, mode, *rest = spec.split(":")
    v = json.loads((P259_CASES / f"{stem}-SYNTHETIC-probe.json").read_text())
    if mode in ("norm", "complete") and isinstance(v.get("third_party"), dict) and stem != "missing_schema_head_other_versions":
        v["third_party"] = {"numpy": __import__("numpy").__version__, "mlx": "unknown"}
    if mode == "complete":
        # an adversary completes P259's report with every key the new builder requires, copied from the
        # real report, keeping P259's defect fields (including its placeholder digests) untouched
        real = load(REPORT)
        for k, val in real.items():
            v.setdefault(k, val)
    if rest == ["noart"]:
        __import__("shutil").rmtree(root / "artifacts")
    REPORT.write_text(json.dumps(v, ensure_ascii=False, indent=1))


if tamper.startswith("p259:"):
    p259(tamper)
else:
    TAMPERS[tamper]()
print("TAMPER", tamper, flush=True)
print("REPORT_SHA256_AFTER_TAMPER", sha(REPORT), flush=True)
before = tree()
events = []


def hook(event, args):
    if event == "open":
        path, mode = args[0], args[1]
        flags = args[2] if len(args) > 2 else 0
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & 0b11):
            events.append(["open-write", str(path), str(mode), flags])
    elif event in ("os.rename", "os.replace", "os.remove", "os.unlink", "os.mkdir", "os.rmdir", "shutil.rmtree",
                   "shutil.copyfile", "shutil.move", "os.truncate", "os.chmod", "os.utime"):
        events.append([event, [str(a) for a in args]])
    elif event == "subprocess.Popen":
        events.append(["subprocess", [str(a) for a in args[1]] if args[1] else str(args[0])])


sys.addaudithook(hook)
sys.argv = ["make_prereg.py", "--design", str(root / "reports/V9-S6-DESIGN/DESIGN-r2.md"),
            "--probe", str(REPORT), "--out", str(OUT)]
outcome = "WRITTEN"
try:
    runpy.run_path(str(root / "reports/V9-S6-PHASE1/make_prereg.py"), run_name="__main__")
except BaseException as exc:  # noqa: BLE001 - we report every refusal type
    outcome = f"REFUSED {type(exc).__module__}.{type(exc).__name__}: {exc}"
after = tree()
print("BUILDER_OUTCOME", outcome, flush=True)
print("OUTPUT_EXISTS", OUT.exists(), flush=True)
if OUT.exists():
    doc = json.loads(OUT.read_text())
    print("OUTPUT_BUDGET", json.dumps(doc["budget"], sort_keys=True), flush=True)
    print("OUTPUT_PROBE_REPORT_SHA256", doc["probe_report_sha256"], flush=True)
print("WRITE_EVENTS", json.dumps(events), flush=True)
changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
print("TREE_FILES", len(before), "CHANGED_DURING_BUILDER", json.dumps(changed), flush=True)
mods = {n: getattr(m, "__file__", None) for n, m in list(sys.modules.items())
        if n in ("ainerzero", "prereg_evidence", "ainerzero.v9.experiments.s6.analysis", "ainerzero.v9.experiments.s3.run_guard")}
print("MODULES_FROM_CASE_ROOT", all(str(v).startswith(str(root)) for v in mods.values() if v), json.dumps(mods), flush=True)
print("MLX_IN_SYS_MODULES", any(n == "mlx" or n.startswith("mlx.") for n in sys.modules), flush=True)
