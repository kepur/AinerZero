#!/bin/bash
# r4 refusal evidence: every case below must be a *real* refusal with the
# documented exit code, driven through the real CLI unless a case is explicitly
# a library-level check.  Scratch run roots live under /private/tmp so the
# formal ledger (artifacts/v9/s1/phase1) only ever holds admitted runs.
#
# Changes versus r3 (for r4 / V9.P13):
#   * output and temp paths point at /private/tmp/v9p9r4/neg and reports/V9-P9/r4/evidence
#   * train invocations pass --arm arm2 --seed 0
set -u
REPO=/Users/mac/AinerWorkFlow/AinerZero
PY=$REPO/.venv-ainerzero/bin/python
OUT=$REPO/reports/V9-P9/r4/evidence
NEG=/private/tmp/v9p9r4/neg
rm -rf "$NEG"; mkdir -p "$NEG" "$OUT"
cd "$REPO" || exit 1

run() {  # run <name> <expected_exit> <args...>
  local name=$1 expect=$2; shift 2
  "$@" >"$OUT/$name.out" 2>"$OUT/$name.err"
  local code=$?
  echo "{\"case\": \"$name\", \"expected_exit\": $expect, \"exit\": $code, \"pass\": $([ "$code" = "$expect" ] && echo true || echo false)}" \
    >"$OUT/$name.exit.json"
  echo "$name -> exit $code (expected $expect)"
}

# A. tightened process-memory line cannot be met -> refusal at the start gate
cat >"$NEG/limits-tight-process-memory.json" <<'JSON'
{"process_memory_gib": 0.01, "mlx_memory_gib": 4.0, "system_reserve_gib": 16.0,
 "swap_growth_gib": 1.0, "training_duty_cycle": 0.25, "disk_min_free_gib": 50.0}
JSON
run limits-tight-process-memory 2 "$PY" -m ainerzero.cli s1-phase1 --mode data \
  --output-root "$NEG/tight" --limits-file "$NEG/limits-tight-process-memory.json"

# B. loosening a registered capacity line -> refused before any measurement
cat >"$NEG/limits-loosened-memory.json" <<'JSON'
{"process_memory_gib": 16.0, "mlx_memory_gib": 4.0, "system_reserve_gib": 16.0,
 "swap_growth_gib": 1.0, "training_duty_cycle": 0.25, "disk_min_free_gib": 50.0}
JSON
run limits-loosened-memory 2 "$PY" -m ainerzero.cli s1-phase1 --mode verify \
  --output-root "$NEG/loose" --limits-file "$NEG/limits-loosened-memory.json" \
  --prereg artifacts/v9/s1/phase1/pre_registration.json

# C. loosening the duty cycle -> refused
cat >"$NEG/limits-loosened-duty.json" <<'JSON'
{"process_memory_gib": 8.0, "mlx_memory_gib": 4.0, "system_reserve_gib": 16.0,
 "swap_growth_gib": 1.0, "training_duty_cycle": 1.0, "disk_min_free_gib": 50.0}
JSON
run limits-loosened-duty 2 "$PY" -m ainerzero.cli s1-phase1 --mode verify \
  --output-root "$NEG/duty" --limits-file "$NEG/limits-loosened-duty.json" \
  --prereg artifacts/v9/s1/phase1/pre_registration.json

# D. shared lock held by another process -> exit 4
"$PY" - "$REPO/artifacts/locks/m0-worker.lock" <<'PY' &
import fcntl, sys, time
handle = open(sys.argv[1], "a+")
fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
print("lock held", flush=True)
time.sleep(25)
PY
HOLDER=$!
sleep 2
run lock-busy 4 "$PY" -m ainerzero.cli s1-phase1 --mode data \
  --output-root "$NEG/lockbusy"
kill $HOLDER 2>/dev/null
wait $HOLDER 2>/dev/null

# E. prep wall budget smaller than the pre-work reservation -> RunStore budget stop
mkdir -p "$NEG/budget"
cp artifacts/v9/s1/phase1/dataset_ref.json "$NEG/budget/dataset_ref.json"
run budget-guard 1 "$PY" -m ainerzero.cli s1-phase1 --mode smoke \
  --output-root "$NEG/budget" --wall-budget-seconds 20

# F. train mode without any approval line -> exit 3 (approval gate)
run train-not-approved 3 "$PY" -m ainerzero.cli s1-phase1 --mode train \
  --arm arm2 --seed 0 \
  --output-root "$NEG/train" --prereg artifacts/v9/s1/phase1/pre_registration.json

# G. forged status + recomputed document SHA + rewritten sidecar -> exit 3
"$PY" - "$NEG/forged" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "src")
from ainerzero.v9.experiments.s1 import prereg
src = Path("artifacts/v9/s1/phase1/pre_registration.json")
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
doc = json.loads(src.read_text(encoding="utf-8"))
doc["status"] = "approved"
path = out / "pre_registration.json"
path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
digest = prereg.document_sha256(doc)
prereg.write_sha256_file(path, digest)
print(json.dumps({"forged_document_sha256": digest, "status": doc["status"]}))
PY
run forged-status 3 "$PY" -m ainerzero.cli s1-phase1 --mode train \
  --arm arm2 --seed 0 \
  --output-root "$NEG/forged" --prereg "$NEG/forged/pre_registration.json"

FROZEN_SHA=$("$PY" -c "import json,sys; sys.path.insert(0,'src'); from pathlib import Path; from ainerzero.v9.experiments.s1 import prereg; print(prereg.document_sha256(json.loads(Path('artifacts/v9/s1/phase1/pre_registration.json').read_text())))")

# H. P-1: a relocated log carrying the *exact* line is still refused (exit 3)
printf '## R20261021-P1-stageA-budget：test\n\nAPPROVED s1-phase1 prereg document_sha256=%s\n' \
  "$FROZEN_SHA" >"$NEG/research-log-exact.md"
run train-relocated-log 3 "$PY" -m ainerzero.cli s1-phase1 --mode train \
  --arm arm2 --seed 0 \
  --output-root "$NEG/relocated" --prereg artifacts/v9/s1/phase1/pre_registration.json \
  --research-log "$NEG/research-log-exact.md"

# I. library level: exact line inside the section accepted, one digit off refused
"$PY" - "$FROZEN_SHA" "$NEG" >"$OUT/approval-exact.json" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "src")
from ainerzero.v9.experiments.s1 import prereg
digest, neg = sys.argv[1], Path(sys.argv[2])
doc = json.loads(Path("artifacts/v9/s1/phase1/pre_registration.json").read_text(encoding="utf-8"))
line = prereg.APPROVAL_TEMPLATE.format(document_sha256=digest)
def log(name, body):
    path = neg / name
    path.write_text(body, encoding="utf-8")
    return path
exact = log("log-exact.md", f"## {prereg.APPROVAL_SECTION}\n\n{line}\n")
broken_sha = digest[:-1] + ("0" if digest[-1] != "0" else "1")
off = log("log-off-by-one.md", f"## {prereg.APPROVAL_SECTION}\n\n{prereg.APPROVAL_TEMPLATE.format(document_sha256=broken_sha)}\n")
outside = log("log-outside.md", f"## other\n\n{line}\n")
record = prereg.require_coordinator_approval(doc, digest, log_path=exact)
refusals = {}
for name, path in (("one_digit_off", off), ("outside_section", outside)):
    try:
        prereg.require_coordinator_approval(doc, digest, log_path=path)
        refusals[name] = {"refused": False}
    except prereg.ApprovalRefused as exc:
        refusals[name] = {"refused": True, "reasons": exc.reasons}
print(json.dumps({
    "accepted": True, "line": record["line"], "line_number": record["line_number"],
    "document_sha256": record["document_sha256"], "status_field": record["status_field"],
    "status_field_is_authoritative": record["status_field_is_authoritative"],
    "refusals": refusals,
}, ensure_ascii=False, indent=1))
PY
echo "approval-exact -> accepted; off-by-one / outside-section refused (see approval-exact.json)"
