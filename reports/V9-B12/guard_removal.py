#!/usr/bin/env python3
"""拆守卫坏控（ADR-0014 r3 §3 末段对 C1–C4 实现卡的硬要求）。

对每一个守卫：在**源码副本**上按字节移除该守卫，跑对应的负例测试，要求它变红；
随后按字节还原并校验 SHA 未变。副本与仓内源码逐字节一致（先校验基线 SHA），
因此"变红"只能由被移除的那一个守卫解释。

用法：``env -u PYTHONPATH .venv/bin/python reports/V9-B12/guard_removal.py``
输出同时写到 ``reports/V9-B12/evidence/03-guard-removal.txt``。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
PYTEST = REPO / ".venv/bin/pytest"
OUT = REPO / "reports/V9-B12/evidence/03-guard-removal.txt"

TESTS = "tests/v9/contracts"

MUTANTS = [
    dict(
        mid="G1",
        change="C1",
        desc="promote 不再拒绝 v1 证据（fail-closed 门被拆）",
        file="interfaces/spatial_memory.py",
        anchor='''        if not evidence.is_v2():
            raise EvidenceRequired(
                f"promote() only accepts PromotionEvidence schema_version='v2', got "
                f"{evidence.schema_version!r}; v1 evidence stays readable but may not promote "
                "(ADR-0014 §3 C1, fail-closed)"
            )
''',
        node=f"{TESTS}/test_spatial_memory.py::test_v1_evidence_is_refused_at_promote",
    ),
    dict(
        mid="G2",
        change="C1",
        desc="v2 证据的字段校验整体不执行",
        file="interfaces/types.py",
        anchor="        self._validate_v2()\n",
        node=f"{TESTS}/test_promotion_evidence_v2.py::test_empty_conformal_certificate_is_refused",
    ),
    dict(
        mid="G3",
        change="C1",
        desc="D/C/T 两两不相交检查被拆",
        file="interfaces/types.py",
        anchor='''        if len(set(identities)) != len(identities):
            raise ValueError(
                f"evidence.data_identity must be pairwise disjoint across D/C/T, got {identities}; "
                "the discovery, calibration and test sets may never overlap (§2 D3)"
            )
''',
        node=f"{TESTS}/test_promotion_evidence_v2.py::test_discovery_calibration_test_identities_must_be_pairwise_disjoint",
    ),
    dict(
        mid="G4",
        change="C2",
        desc="SLOW 守卫不再拦截类别 self（学生自证可通过）",
        file="interfaces/validation.py",
        anchor='''    if category in SLOW_FORBIDDEN_CATEGORIES:
        raise EvidenceRequired(
            f"producers of category {category!r} may not produce SLOW evidence: a promotion needs an "
            f"identity isolated from the generator (ADR-0014 §2 D3-7); producer={producer!r}"
        )
''',
        node=f"{TESTS}/test_promotion_evidence_v2.py::test_student_self_evidence_is_refused_on_the_slow_path",
    ),
    dict(
        mid="G5",
        change="C2",
        desc="不再要求 admission_bindings 里存在该 producer 的绑定（裸自报字符串可过）",
        file="interfaces/validation.py",
        anchor='''    if matched is None:
        raise EvidenceRequired(
            f"trusted_context_binding: producer {producer!r} has no admission binding in trusted "
            f"context {context_id!r}; a bare self-reported producer string is not accepted"
        )
''',
        node=f"{TESTS}/test_promotion_evidence_v2.py::test_bare_self_reported_string_without_binding_is_refused",
    ),
    dict(
        mid="G6",
        change="C2",
        desc="绑定摘要不再校验（绑定可被挪用/伪造）",
        file="interfaces/validation.py",
        anchor='''    if matched.get("binding_sha256") != expected:
        raise EvidenceRequired(
            f"trusted_context_binding: binding_sha256 for producer {producer!r} is not the canonical "
            f"digest of (context_id, producer, category); expected {expected}"
        )
''',
        node=f"{TESTS}/test_promotion_evidence_v2.py::test_binding_digest_must_be_canonical",
    ),
    dict(
        mid="G7",
        change="C3",
        desc="缺来源/对象/动作键的条目仍可晋升",
        file="interfaces/spatial_memory.py",
        anchor='''        gaps = fragment.promotion_gaps()
        if gaps:
            raise EvidenceRequired(
                f"fragment {fragment.fragment_id!r} cannot be promoted: it is missing ARCH §2 "
                f"field(s) {list(gaps)} (ADR-0014 §3 C3)"
            )
''',
        node=f"{TESTS}/test_memory_lifecycle.py::test_fragment_without_provenance_cannot_be_promoted",
    ),
    dict(
        mid="G8",
        change="C3",
        desc="晋升内容与受检内容不再比对（条目摘要检查被拆）",
        file="interfaces/spatial_memory.py",
        anchor='''        actual = fragment.content_digest()
        if actual != evidence.entry_digest:
            raise EvidenceRequired(
                f"evidence.entry_digest does not match the stored entry {fragment.fragment_id!r} "
                f"(evidence {evidence.entry_digest!r} != entry {actual!r}); the promoted content must "
                "be the content that was tested"
            )
''',
        node=f"{TESTS}/test_memory_lifecycle.py::test_entry_digest_must_match_the_stored_content",
    ),
    dict(
        mid="G9",
        change="C3",
        desc="Fragment 标识符不再拦截世界真值 ID（§8.6）",
        file="interfaces/types.py",
        anchor='''        if segment in tokens or segment.startswith(("gt_", "eval_")):
            raise ValueError(
                f"{name} carries a world-truth identifier segment {segment!r} in {identifier!r}; "
                "memory entries may only reference learning-side visible ids (§8.6)"
            )
''',
        node=f"{TESTS}/test_fragment_provenance.py::test_world_truth_identifiers_are_refused",
    ),
    dict(
        mid="G10",
        change="C4",
        desc="版本漂移不再触发重验（漂移条目仍被确定性层使用）",
        file="fakes/spatial_memory.py",
        anchor='''            if promotion["encoder_version"] != encoder_version:
                continue
            if promotion["prior_version"] != prior_version:
                continue
''',
        node=f"{TESTS}/test_memory_lifecycle.py::test_slow_entry_is_usable_only_while_versions_match",
    ),
    dict(
        mid="G11",
        change="C4",
        desc="demote 允许落到 SLOW（降级变升级）",
        file="fakes/spatial_memory.py",
        anchor='''        if to_level not in DEMOTABLE_LEVELS:
            raise ContractViolation(
                f"demote() target must be one of {DEMOTABLE_LEVELS}, got {to_level!r}; "
                "a demotion never lands on SLOW"
            )
''',
        node=f"{TESTS}/test_memory_lifecycle.py::test_demote_never_lands_on_slow",
    ),
    dict(
        mid="G12",
        change="C4",
        desc="supersede 指针可被反复改写（旧版本链断）",
        file="fakes/spatial_memory.py",
        anchor='''        if entry["superseded_by"] is not None:
            raise ContractViolation(
                f"memory item {item_id!r} is already superseded by {entry['superseded_by']!r}"
            )
''',
        node=f"{TESTS}/test_memory_lifecycle.py::test_supersede_is_single_shot",
    ),
    dict(
        mid="G13",
        change="C7",
        desc="ParamBeliefStore 不再限定只由 PARAMETRIC 分支写",
        file="interfaces/cmfl.py",
        anchor='''        if route_code != PARAMETRIC_ROUTE_CODE:
            raise ContractViolation(
                f"ParamBeliefStore is written only by the MSG {PARAMETRIC_ROUTE_CODE} branch "
                f"(ADR-0014 §2 D1 row 5); got route_code={route_code!r}"
            )
''',
        node=f"{TESTS}/test_param_belief.py::test_store_accepts_parametric_writes_only",
    ),
    dict(
        mid="G14",
        change="C7",
        desc="4a/4b 路由记录不再要求 NIS 统计量与自由度",
        file="interfaces/cmfl.py",
        anchor='''        if self.route_code in NIS_ROUTE_CODES:
            if self.nis_stat is None or self.dof is None:
                raise UnsupportedInput(
                    f"route {self.route_code!r} is decided on the NIS statistic and must record "
                    "both nis_stat and dof (§2 D1 rows 4a/4b)"
                )
''',
        node=f"{TESTS}/test_param_belief.py::test_nis_routes_must_record_the_statistic",
    ),
    dict(
        mid="G15",
        change="C5",
        desc="cmfl_registration 不再自校验（冻结件可被手改）",
        file="interfaces/cmfl_registration.py",
        anchor='''        if self.digest() != self.sha256:
            raise UnsupportedInput(
                "cmfl_registration.sha256 does not match the canonical digest of its own content; "
                "a frozen registration may not be edited in place (new fields = new registration id)"
            )
''',
        node=f"{TESTS}/test_cmfl_registration.py::test_tampering_breaks_the_self_check",
    ),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_pytest(node: str, src_root: Path) -> tuple[int, str]:
    env = dict(os.environ)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(key, None)
    env["NO_PROXY"] = "127.0.0.1,localhost,::1"
    env["PYTHONPATH"] = str(src_root)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    completed = subprocess.run(
        [str(PYTEST), node, "-q", "-p", "no:cacheprovider", "--no-header"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return completed.returncode, completed.stdout + completed.stderr


def tail(text: str, lines: int = 4) -> str:
    rows = [row for row in text.strip().splitlines() if row.strip()]
    return " | ".join(rows[-lines:])


def main() -> int:
    log: list[str] = []
    log.append("# 拆守卫坏控（B12 / ADR-0014 §3 C1–C5,C7）")
    log.append(f"# 仓库：{REPO}")
    log.append(f"# 副本：源码树逐字节复制，守卫按字节移除后跑对应负例；每例跑完立即还原并校验 SHA")
    log.append("")

    with tempfile.TemporaryDirectory(prefix="b12-guards-") as tmp:
        tmp_root = Path(tmp)
        pristine = tmp_root / "pristine"
        work = tmp_root / "work"
        shutil.copytree(SRC, pristine)
        shutil.copytree(SRC, work)

        # 副本必须与仓内源码逐字节一致，否则"变红"没有意义
        for path in sorted(SRC.rglob("*.py")):
            relative = path.relative_to(SRC)
            assert sha256(path) == sha256(pristine / relative), f"copy drift: {relative}"
        log.append("## 0. 副本基线校验")
        log.append(f"src/*.py 与仓内逐字节一致（{len(list(SRC.rglob('*.py')))} 个文件）")
        log.append("")

        env = dict(os.environ)
        env["PYTHONPATH"] = str(work)
        probe = subprocess.run(
            [sys.executable, "-c", "import ainerzero.v9.interfaces as m; print(m.__file__)"],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
        )
        resolved = probe.stdout.strip()
        assert resolved.startswith(str(work)), f"import did not resolve to the copy: {resolved}"
        log.append(f"副本优先于 venv 安装：{resolved}")
        log.append("")

        # 控制组：未拆守卫时这些负例必须通过
        controls: dict[str, int] = {}
        log.append("## 1. 控制组（守卫在位 -> 负例通过）")
        for node in sorted({mutant["node"] for mutant in MUTANTS}):
            code, output = run_pytest(node, work)
            controls[node] = code
            status = "PASS" if code == 0 else "FAIL"
            log.append(f"- {status}  {node}")
        log.append("")
        assert all(code == 0 for code in controls.values()), "control run is not green"

        log.append("## 2. 拆守卫（守卫移除 -> 负例必须变红）")
        failures: list[str] = []
        for mutant in MUTANTS:
            target = work / "ainerzero/v9" / mutant["file"]
            original = target.read_bytes()
            before = sha256(target)
            text = original.decode("utf-8")
            occurrences = text.count(mutant["anchor"])
            if occurrences != 1:
                failures.append(f"{mutant['mid']}: anchor found {occurrences} times in {mutant['file']}")
                log.append(f"- ERROR {mutant['mid']} anchor x{occurrences}")
                continue
            mutated = text.replace(mutant["anchor"], "        # [guard removed by B12 control]\n")
            target.write_text(mutated, encoding="utf-8")
            mutated_sha = sha256(target)
            code, output = run_pytest(mutant["node"], work)
            target.write_bytes(original)
            restored = sha256(target)
            assert restored == before, f"{mutant['mid']}: restore failed"
            verdict = "RED (expected)" if code != 0 else "STILL GREEN (guard not load-bearing!)"
            if code == 0:
                failures.append(f"{mutant['mid']}: test stayed green")
            log.append(
                f"- {mutant['mid']} [{mutant['change']}] {mutant['desc']}\n"
                f"    文件 {mutant['file']}  SHA {before[:12]} -> {mutated_sha[:12]} -> {restored[:12]}\n"
                f"    负例 {mutant['node'].split('::')[-1]}\n"
                f"    结果 {verdict}  ({tail(output, 2)})"
            )

        log.append("")
        log.append("## 3. 还原校验")
        for path in sorted(SRC.rglob("*.py")):
            relative = path.relative_to(SRC)
            assert sha256(path) == sha256(work / relative) == sha256(pristine / relative), f"drift: {relative}"
        log.append("仓内源码、副本、还原后副本三方 SHA 全部一致（未污染工作树）")
        log.append("")
        log.append(f"## 结论：{len(MUTANTS) - len(failures)}/{len(MUTANTS)} 个守卫是承重的（移除即变红）")
        if failures:
            log.append("失败项：")
            log.extend(f"- {item}" for item in failures)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
