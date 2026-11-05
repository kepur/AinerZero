#!/usr/bin/env python3
"""B12 r2（一级 claude-az）：在 B12 交付的 15 条拆守卫坏控之上，追加第 16 条——起源硬门（B13 K3）。

复用 B12 的 reports/V9-B12/guard_removal.py（只 import，不改、不覆盖其已交付证据），
追加 G16 后整套重跑，输出写到本目录。用法：env -u PYTHONPATH .venv/bin/python reports/V9-B12/r2-claude-az/guard_removal_r2.py
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("b12_guard_removal", REPO / "reports/V9-B12/guard_removal.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

mod.OUT = REPO / "reports/V9-B12/r2-claude-az/evidence/03-guard-removal-r2.txt"
mod.MUTANTS.append(dict(
    mid="G16",
    change="B13-K3",
    desc="LLM/教师起源的晋升硬门被拆（合法 producer 即可晋升）",
    file="interfaces/spatial_memory.py",
    anchor="        require_slow_eligible_origin(evidence.origin_category)   # V9.B13 K3：起源轴；LLM/教师起源不能靠换 producer 晋升\n",
    node="tests/v9/contracts/test_spatial_memory.py::test_llm_or_teacher_origin_cannot_reach_slow_even_with_a_legitimate_producer",
))
raise SystemExit(mod.main())
