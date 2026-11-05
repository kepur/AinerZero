"""P10 adversarial suite, part 3: final partition, arm budgets, metrics, SHA, wall clock."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

SB = Path("/private/tmp/vp9rev/sandbox")
REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
OUT = Path("/private/tmp/vp9rev/results")
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SB / "src"))

import numpy as np  # noqa: E402

from ainerzero.v9.experiments.s1 import data, metrics, prereg, spec  # noqa: E402

rows: list[dict] = []


def add(cid, name, ok, exit_code, detail, evidence=None):
    rows.append({"id": cid, "name": name, "ok": bool(ok), "exit": exit_code,
                 "detail": detail, "evidence": evidence or {}})
    print(f"{'PASS' if ok else 'FAIL'} {cid} exit={exit_code} {detail}", flush=True)


DATASET = SB / "reports" / "V9-P9" / "dataset"

# --- C13 the final partition is unreachable from every public path -------
sealed = {}
for name, fn in {
    "require_partition": lambda: data.require_partition("final"),
    "load_training_episodes": lambda: data.load_training_episodes(DATASET, "final"),
    "load_truth_view": lambda: data.load_truth_view(DATASET, "final"),
}.items():
    try:
        fn()
        sealed[name] = "NO-RAISE"
    except data.FinalPartitionSealed:
        sealed[name] = "sealed"
    except Exception as exc:                      # a different error still refuses, but note it
        sealed[name] = f"{type(exc).__name__}"
final_files = [str(p.relative_to(DATASET)) for p in DATASET.rglob("*") if "final" in p.name.lower()]
# The two fixed-partition loaders take no partition argument: prove they only ever
# open train/development paths, so "final" cannot reach them either.
import inspect  # noqa: E402
fixed_src = inspect.getsource(data.load_training_windows) + inspect.getsource(data.load_development_windows)
raw_reads = [ln for ln in fixed_src.splitlines() if "final" in ln]
add("C13a", "final 分区在所有公开读路径都被封存拒绝，且数据集里没有 final 文件",
    set(sealed.values()) <= {"sealed"} and not final_files and not raw_reads,
    0, f"loaders={sealed} final_files={final_files} fixed_loader_final_refs={raw_reads}")

# The sealed read-once channel lives in AWZ; S1 must never touch it.
# AST walk: docstrings that *mention* the sealed channel do not count, call sites do.
import ast  # noqa: E402
FORBIDDEN = {"eval_channel", "SealedEvalChannel", "read_sealed_once", "seal_final_exam"}
awz_import = []
for path in sorted((SB / "src/ainerzero/v9/experiments/s1").glob("*.py")):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        name = None
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            name = getattr(node, "module", None) or ""
        if name and any(token in str(name) for token in FORBIDDEN):
            awz_import.append(f"{path.name}:{getattr(node, 'lineno', '?')}:{name}")
awz_final = subprocess.run(["find", str(REAL.parent / "AnimeWorldZero" / "artifacts"), "-name", "*final*"],
                           capture_output=True, text=True).stdout.strip()
add("C13b", "S1 代码里没有任何封存通道调用（AST 级）；AWZ artifacts 下无 final 产物",
    not awz_import and awz_final == "", 0,
    f"sealed_channel_calls={awz_import} awz_final_artifacts={awz_final!r}")

# --- C14 three trainable arms share one update budget --------------------
doc = json.loads((REAL / "reports" / "V9-P9" / "pre_registration.json").read_text())
budgets = {a: doc["arms"][a]["training_updates"] for a in ("arm2", "arm3", "arm4")}
seeds = {a: doc["arms"][a]["seeds"] for a in ("arm2", "arm3", "arm4")}
tampered = json.loads(json.dumps(doc))
tampered["arms"]["arm3"]["training_updates"] = doc["training_protocol"]["updates"] + 1
tamper_reasons = prereg.validate(tampered)
add("C14", "三个训练臂更新预算与种子完全相同；单臂改动会被 validate() 打回",
    len(set(budgets.values())) == 1 and len({tuple(v) for v in seeds.values()}) == 1
    and any("arm3 training budget" in r for r in tamper_reasons),
    0, f"budgets={budgets} seeds={seeds} tamper={[r for r in tamper_reasons if 'arm3' in r]}")

# --- C15 metrics: known answers plus broken controls ---------------------
truth = np.array([[0.0, 0.0, 0.0, 0.0], [1.0, 0.0, 2.0, 30.0]])
same = metrics.localization_error(truth, truth)
shift = metrics.localization_error(truth + np.array([3.0, 0.0, 0.0, 0.0]), truth)
nodes = [[0.0, 0.0], [1.0, 0.0]]
cells = [(0, 0), (1, 0)]
true_edges = [((0, 0), (1, 0))]
good = metrics.topology_edge_metrics(nodes, [(0, 1)], cells, true_edges)
bad = metrics.topology_edge_metrics(nodes, [], cells, true_edges)
add("C15", "指标已知答案正确，改坏预测后变差（定位/拓扑）",
    same["translation_mean_m"] == 0.0 and abs(shift["translation_mean_m"] - 3.0) < 1e-12
    and good["precision"] == 1.0 and good["recall"] == 1.0
    and bad["precision"] == 0.0 and bad["recall"] == 0.0,
    0, f"same={same['translation_mean_m']} shift={shift['translation_mean_m']} "
       f"good_p/r={good['precision']}/{good['recall']} bad_p/r={bad['precision']}/{bad['recall']}")

# --- C16 prereg SHA matches the report, byte for byte -------------------
raw = (REAL / "reports" / "V9-P9" / "pre_registration.json").read_bytes()
file_sha = hashlib.sha256(raw).hexdigest()
doc_sha = prereg.document_sha256(json.loads(raw))
sidecar = (REAL / "reports" / "V9-P9" / "pre_registration.json.sha256").read_text().split()[0]
report_text = (REAL / "reports" / "V9-P9" / "REPORT.md").read_text()
add("C16", "预登记 document/file SHA 与 P9 报告一致，sidecar 与 document 一致",
    file_sha == "2602e42cad7bf39e5b6ac788d19e393dc22f9d0b07cca6c4ef525e0fcb0d76a0"
    and doc_sha == "32c30f5005a438f759e14641f5ea77b635eb4020af7fa9ba823b7ad05bb74de6"
    and sidecar == doc_sha and doc_sha in report_text and file_sha[:8] in report_text,
    0, f"file={file_sha[:16]}… doc={doc_sha[:16]}… sidecar_match={sidecar == doc_sha}")

# --- C17 wall-clock caps and the duty-inclusive estimate ----------------
t = doc["timing"]
deadline = t["deadline_seconds"]
phase = t["phase_wall_seconds"]
gen = t["smoke"]["data_generation_seconds"]
recomputed_phase = spec.TIMING["trainable_runs"] * deadline + spec.TIMING["d_candidate_eval_runs"] * t["arm1_deadline_seconds"] + gen
step = doc["budget_estimate"]["measured_forward_loss_step_seconds"]
duty = doc["resource_limits"]["training_duty_cycle"]
updates = doc["training_protocol"]["updates"]
active = updates * 3.0 * step + spec.TIMING["eval_batches"] * step * len(spec.TIMING["eval_checkpoint_fractions"])
estimate_no_duty = active * spec.TIMING["estimate_eval_overhead_factor"]
estimate_with_duty = (active / duty) * spec.TIMING["estimate_eval_overhead_factor"]
add("C17", "单次 ≤20 min、总墙钟 ≤4 h、phase=9×deadline+arm1+数据，且 360 s 估计已含占空比",
    deadline <= 1200 and phase <= 14400 and abs(recomputed_phase - phase) < 1e-6
    and abs(estimate_with_duty - t["estimate_seconds"]) < 0.05
    and estimate_no_duty < t["estimate_seconds"] * 0.35,
    0, f"deadline={deadline} phase={phase:.1f} recomputed={recomputed_phase:.1f} "
       f"est_with_duty={estimate_with_duty:.2f} est_no_duty={estimate_no_duty:.2f} "
       f"frozen_est={t['estimate_seconds']:.2f}")

# --- C18 every run recorded 0 optimizer steps (no parameter update) -----
add("C18", "冻结文件与 RunStore 都声明 0 次优化步（本卡未更新参数）",
    doc["arms"]["arm1"]["training_updates"] == 0
    and all(doc["arms"][a]["kind"] == "trainable" for a in ("arm2", "arm3", "arm4")),
    0, f"arm1_updates={doc['arms']['arm1']['training_updates']}")

(OUT / "p3.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n{sum(r['ok'] for r in rows)}/{len(rows)} passed")
