"""从 dev-tune 与 dev-tune-b 的 dev 指标写出 dev-distill 用的 tune 文件。只读运行目录，不训练、不拿锁。

选值规则都用 ``plan_s5p1.choose_value``（同一取值先对 R2 AP 取平均，高者胜；平局取更小的取值）：
- supervised_lr：dev-tune 的 6 个 A0 格（3 档 L × 2 个学习率）；
- distill_lr：dev-tune-b 的 2 个读出头格（两个蒸馏学习率候选学生各一组 L=512 读出头）；
- eta：dev-tune 与 dev-tune-b 中 3 个 A4 格（η 取值从格名解析，并与计划里的格逐个核对）。
每个格都要求在所属运行的 cell_end 里登记过，指标文件名与计划格名一致。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import plan_s5p1 as plan  # noqa: E402


def _events(run: Path) -> list[dict]:
    return [json.loads(line) for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def _finished(run: Path) -> set[str]:
    return {e["cell_id"] for e in _events(run) if e.get("event") == "cell_end"}


def _stage(run: Path) -> str:
    starts = [e for e in _events(run) if e.get("event") == "stage_start"]
    if len(starts) != 1:
        raise SystemExit(f"{run}: expected one stage_start")
    return str(starts[0]["stage"])


def _metric(run: Path, cell_id: str) -> dict:
    if cell_id not in _finished(run):
        raise SystemExit(f"{run}: {cell_id} has no cell_end")
    path = run / "metrics" / f"{cell_id}.json"
    if not path.is_file():
        raise SystemExit(f"missing metrics file {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build(tune_run: Path, tune_b_run: Path) -> dict:
    if _stage(tune_run) != "dev-tune" or _stage(tune_b_run) != "dev-tune-b":
        raise SystemExit("run directories must be a dev-tune run and a dev-tune-b run")
    tune_cells = plan.stage_cells("dev-tune")
    b_cells = plan.stage_cells("dev-tune-b")

    sup_rows = []
    for cell in tune_cells:
        if cell.get("role") != "supervised_lr":
            continue
        m = _metric(tune_run, cell["cell_id"])
        assert float(m["lr"]) == float(cell["lr"]) and int(m["label_n"]) == int(cell["label_n"]), cell["cell_id"]
        sup_rows.append({"cell_id": cell["cell_id"], "lr": float(cell["lr"]), "label_n": cell["label_n"], "r2_ap": float(m["r2_ap"])})
    if len(sup_rows) != len(plan.SUPER_LRS) * len(plan.L_WORLDS):
        raise SystemExit("supervised tuning rows are incomplete")
    sup = plan.choose_value(sup_rows, "lr")

    dl_rows = []
    for cell in b_cells:
        if cell.get("role") != "distill_lr":
            continue
        m = _metric(tune_b_run, cell["cell_id"])
        assert float(m["distill_lr"]) == float(cell["distill_lr"]), cell["cell_id"]
        dl_rows.append({"cell_id": cell["cell_id"], "distill_lr": float(cell["distill_lr"]), "r2_ap": float(m["r2_ap"])})
    if len(dl_rows) != len(plan.DISTILL_LRS):
        raise SystemExit("distill-lr readout rows are incomplete")
    dl = plan.choose_value(dl_rows, "distill_lr")

    eta_rows = []
    for cell in tune_cells:
        if cell.get("role") != "eta":
            continue
        run = tune_run if cell["cell_id"] in _finished(tune_run) else tune_b_run
        m = _metric(run, cell["cell_id"])
        if float(m["lr"]) != float(sup["value"]):
            raise SystemExit(f"{cell['cell_id']} used lr {m['lr']}, tuned supervised lr is {sup['value']}")
        eta_rows.append({"cell_id": cell["cell_id"], "eta": float(cell["eta"]), "run": run.name, "r2_ap": float(m["r2_ap"])})
    if sorted(r["eta"] for r in eta_rows) != sorted(plan.ETAS):
        raise SystemExit("eta rows are incomplete")
    eta = plan.choose_value(eta_rows, "eta")

    return {
        "rule": "plan_s5p1.choose_value: mean dev R2 AP per value, higher wins, tie -> smaller value",
        "dev_tune_run": str(tune_run),
        "dev_tune_b_run": str(tune_b_run),
        "supervised_rows": sup_rows, "supervised_choice": sup, "supervised_lr": sup["value"],
        "distill_lr_rows": dl_rows, "distill_lr_choice": dl, "distill_lr": dl["value"],
        "eta_rows": eta_rows, "eta_choice": eta, "eta": eta["value"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tune-run", required=True)
    parser.add_argument("--tune-b-run", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    doc = build(Path(args.tune_run).resolve(), Path(args.tune_b_run).resolve())
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("supervised_lr", "distill_lr", "eta")}))
    print(hashlib.sha256(out.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
