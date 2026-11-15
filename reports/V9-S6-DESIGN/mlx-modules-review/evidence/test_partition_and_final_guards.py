#!/usr/bin/env python3
"""Evidence 4: Test partition separation, smoke isolation, and final guards."""
import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "reports/V9-S6-PHASE1"))

from ainerzero.v9.experiments.s3 import run_guard as GD
from ainerzero.v9.experiments.s4 import world as W
import run_s6p1 as RUN

print("=== 1. Check partition definitions ===")
print("SETS in run_s6p1.py:")
for s, cfg in RUN.SETS.items():
    print(f"  {s}: cand_ns={cfg['cand_ns']}, test_ns={cfg['test_ns']}")

# Run runner's own partition check
RUN.check_partitions()
print("RUN.check_partitions() passed.")

# Verify registered partitions
print("W.REGISTERED:", sorted(W.REGISTERED))
assert "s6p1-final" in W.REGISTERED
assert "s6p1-cand" not in W.REGISTERED
assert "s6p1-probe" not in W.REGISTERED
assert "s6p1-pcand" not in W.REGISTERED
assert "s6t-smoke-cand" not in W.REGISTERED
assert "s6t-smoke-test" not in W.REGISTERED

# Verify smoke namespace check
for s in ("cand_ns", "test_ns"):
    assert RUN.SETS["smoke"][s].startswith("s6t-"), f"Smoke namespace {RUN.SETS['smoke'][s]} must start with s6t-"
print("Smoke namespace isolation verified: smoke touches only s6t-* stand-in namespaces.")

print("\n=== 2. Guard against accessing registered partition directly ===")
try:
    W.generate_episode("s6p1-final", 0, 6, steps=5, allow_registered=False)
    print("FAIL: direct access to s6p1-final was allowed!")
    sys.exit(1)
except (PermissionError, GD.GuardError) as e:
    print("OK: direct access to s6p1-final raised error as expected:", e)

print("\n=== 3. Static verification of sequence in run_s6p1.py eval ===")
# Parse AST of run_s6p1.py to verify exact order in run_eval:
# 1) verify runs first
# 2) if not passed -> return before touching test partition
# 3) consume_final_read called
# 4) generate_episode called on test_ns
tree = ast.parse(Path(RUN.__file__).read_text(encoding="utf-8"))
eval_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_eval")

# Find line numbers of key calls
calls = []
for node in ast.walk(eval_fn):
    if isinstance(node, ast.Call):
        func_name = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = f"{getattr(node.func.value, 'id', '')}.{node.func.attr}"
        if func_name in ("independent_verify", "GD.consume_final_read", "W.generate_episode"):
            calls.append((node.lineno, func_name))

calls.sort()
print("Sequence of critical operations in run_eval:")
for lineno, name in calls:
    print(f"  Line {lineno}: {name}")

verify_line = next(l for l, n in calls if n == "independent_verify")
consume_line = next(l for l, n in calls if n == "GD.consume_final_read")
generate_line = next(l for l, n in calls if n == "W.generate_episode")

assert verify_line < consume_line < generate_line, (
    f"Order violation: independent_verify ({verify_line}) must precede "
    f"consume_final_read ({consume_line}), which must precede generate_episode ({generate_line})"
)
print("OK: Verification strictly precedes consume_final_read, which strictly precedes test episode generation.")

print("\nALL PARTITION AND FINAL GUARD CHECKS PASSED!")
