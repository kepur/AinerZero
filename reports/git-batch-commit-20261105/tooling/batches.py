"""Batch definitions for committing the AinerZero working tree (2026-11-05).

CODE_BATCHES: pathspecs per code batch, plus the evidence files the batch's own tests read.
REPORT_BATCHES: untracked report directories assigned to work lines by top-level directory.
Report files are filtered by KEEP rule; excluded files are fingerprinted in a manifest instead.
src/ainerzero/cli.py is shared by several lines: each code batch stages a cli.py variant
(cli_variants.py rebuilds them from the working-tree file and proves HEAD/final round-trip).
"""
import os, re, subprocess

REPO = "/Users/mac/AinerWorkFlow/AinerZero"

CODE_BATCHES = [
    ("b1_contract", "V9 契约层：interfaces/fakes/geometry r2+canonical/RLT + SkillProposal 契约", [
        "src/ainerzero/v9/__init__.py", "src/ainerzero/v9/interfaces", "src/ainerzero/v9/fakes",
        "src/ainerzero/v9/geometry", "src/ainerzero/v9/tokenization",
        "tests/v9/contracts", "tests/v9/geometry", "tests/v9/tokenization",
        "contracts/v9/skill_proposal.v1.schema.json", "contracts/v9/skill_gate_reply.v1.schema.json",
        "contracts/v9/ability_registry_entry.v0.schema.json", "contracts/v9/examples/skill_proposal_v1",
        "docs/v9/SKILL_PROPOSAL.md", "docs/v9/SKILL_PROPOSAL_COORDINATION.md",
        "reports/V9-B12/cmfl_registration.json",
    ], ["tests/v9/contracts", "tests/v9/geometry", "tests/v9/tokenization"]),
    ("b2_cmfl", "CMFL 机制发现原型（G7）", [
        "src/ainerzero/v9/mechanism", "tests/v9/mechanism",
    ], ["tests/v9/mechanism"]),
    ("b3_e1code", "E1 代码：experiments/e1 + e1-phase2 CLI + WorkerLockBusy + 测试 + 预登记草案", [
        "src/ainerzero/v9/experiments/__init__.py", "src/ainerzero/v9/experiments/e1",
        "tests/test_e1_*.py", "tests/fixtures/e1_prior_sphere_regression.npz",
        "reports/V9-P48",
        "reports/V9-E1SMOKE3/gemini-k7a4/smoke_env/datasets/evaluator/S/development",
        "reports/V9-E1SMOKE3/gemini-k7a4/smoke_env/datasets/student/S/development",
    ], ["tests/test_e1_*.py", "tests/test_hardware_cli.py", "tests/test_pilot.py"]),
    ("b4_s1code", "S1 代码：experiments/s1 + s1-phase1 CLI + 基线清单脚本 + 测试", [
        "src/ainerzero/v9/experiments/s1", "tests/v9/experiments",
        "scripts/v9_baseline_manifest_r2.py", "scripts/v9_baseline_manifest_r3.py",
        "reports/V9-baseline/r3", "reports/V9-P9/r1-archive/smoke_metrics.json",
    ], ["tests/v9/experiments"]),
    ("b5_teachers", "教师线代码：cache/mode/benchmark/DA3 受控入口 + teacher CLI + v2.1 缓存契约 + 测试读取的证据 + 教师环境胶水脚本", [
        "src/ainerzero/v9/teachers", "tests/v9/teachers",
        "tests/test_da3_*.py", "tests/test_t28_*.py", "tests/test_teacher_da3_controlled.py",
        "contracts/v9/teacher_cache.v2_1.schema.json", "contracts/v9/examples/teacher_cache_v2_1",
        "docs/v9/TEACHERS_AND_CACHE_V2_1.md", "docs/v9/TEACHERS_AND_CACHE.md",
        # evidence read by the batch's tests (REPO-relative)
        "reports/V9-T28", "reports/V9-T6/r2-calib-fixtures",
        "reports/V9-T30/r2/mutations", "reports/V9-T30/r3/mutations",
        # teacher environment glue (venvs, wheels, caches, weights and third-party checkouts stay out)
        ":(glob)envs/teachers/t4/*.py", ":(glob)envs/teachers/t6/*.py", "envs/teachers/t6/tests",
        "envs/teachers/t10/LICENSE.provenance.json", "envs/teachers/t12/LICENSE.provenance.json",
    ], ["tests/v9/teachers", "tests/test_da3_*.py", "tests/test_t28_*.py", "tests/test_teacher_da3_controlled.py"]),
]
CLI_VARIANT = {"b3_e1code": "cli_e1.py", "b4_s1code": "cli_e1s1.py", "b5_teachers": "cli_all.py"}

# Report lines, in commit order. Pattern is matched against the top-level name under reports/.
REPORT_LINES = [
    ("r1_b", "B 线报告：SkillProposal / 晋升证据（V9-B*、V-V9-B*）", r"^(V-)?V9-B"),
    ("r2_ga", "G/A 线报告：几何 r2、CMFL ADR-0014 审议与原型（V9-G*、V-V9-G*、V9-A11–A14、frontier-integration）",
     r"^((V-)?V9-G|V9-A1[1-4]$|frontier-integration-)"),
    ("r3_registry", "R 线：研究适配器登记 r3/r4 报告与 docs/research 登记表", r"^(V-)?V9-R"),
    ("r4_s1", "S1 线报告：P1–P62 执行与复核、S1 r12–r15/final、基线清单 A2/A3",
     r"^(V9-S1|V-V9-P2$|V-V9-P9$|V9-P9$|V9-P(1[0-9]|2[0-9]|3[0-9]|4[0-7]|49|5[0-9]|6[0-2])$|V9-baseline$|V-V9-baseline$)"),
    ("r5_e1", "E1 线报告：E1 预登记、冒烟、运行 A/B/C/r2、复核与冻结（V9-E1*、V9-P48*）", r"^(V9-E1|V9-P48)"),
    ("r6_teachers", "教师 / DA3 线报告（V9-T*、V-V9-T*、安装下载、TPREP、P63）",
     r"^((V-)?V9-T|V9-TPREP$|V9-P63$|(V-)?teachers-install-download-)"),
    ("r7_misc", "跨项目与统筹：CF-D1/CF-H1、coordination 待拍板清单、CLAUDE.md / COORDINATION.md", r"^(CF-|coordination$)"),
]
EXTRA_FILES = {
    "r3_registry": ["docs/research/ADAPTER_REGISTRY.md", "docs/research/adapter_registry.json"],
    "r7_misc": ["CLAUDE.md", "COORDINATION.md"],
}
KEEP_LIMIT = 1_000_000


def files_for(specs):
    out = subprocess.run(["git", "-C", REPO, "-c", "core.quotepath=off", "ls-files", "-z", "--others", "--modified",
                          "--exclude-standard", "--", *specs], capture_output=True, text=True, check=True).stdout
    return sorted(set(p for p in out.split("\0") if p))


def keep_reason(path):
    """None if a report file is committed; otherwise the exclusion class."""
    full = os.path.join(REPO, path)
    if os.path.islink(full):
        return "symlink"
    parts = path.split("/")
    if "datasets" in parts[:-1]:
        return "datasets"
    if "checkpoints" in parts[:-1]:
        return "checkpoints"
    if path.endswith((".npz", ".npy")):
        return "arrays"
    if os.path.getsize(full) > KEEP_LIMIT:
        return "over_1MB"
    return None


def code_files():
    return {name: files_for(specs) for name, desc, specs, tests in CODE_BATCHES}


def report_batches(code=None):
    """{line: (kept_files, excluded[(path, reason)])} for untracked reports not in code batches."""
    code = code if code is not None else code_files()
    in_code = set(f for fs in code.values() for f in fs)
    reports = [f for f in files_for(["reports"]) if f not in in_code]
    out = {name: ([], []) for name, _, _ in REPORT_LINES}
    unassigned = []
    for f in reports:
        top = f.split("/")[1]
        line = next((n for n, _, pat in REPORT_LINES if re.match(pat, top)), None)
        if line is None:
            unassigned.append(f)
            continue
        reason = keep_reason(f)
        (out[line][0] if reason is None else out[line][1]).append(f if reason is None else (f, reason))
    if unassigned:
        raise SystemExit(f"unassigned report files: {sorted(set(u.split('/')[1] for u in unassigned))}")
    for line, extra in EXTRA_FILES.items():
        out[line][0].extend(files_for(extra))
    return out


def all_batches():
    """Ordered [(name, desc, files)] for every batch (code then reports)."""
    code = code_files()
    rep = report_batches(code)
    seq = [(n, d, code[n]) for n, d, s, t in CODE_BATCHES]
    seq += [(n, d, sorted(rep[n][0])) for n, d, _ in REPORT_LINES]
    return seq, rep
