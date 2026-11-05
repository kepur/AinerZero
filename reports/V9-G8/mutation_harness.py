"""V9.G8 坏控（变异）框架：把 `src/ainerzero/v9/mechanism/` 复制到临时目录做**文本变异**，
再以独立包名导入。这样坏控改的是真实源码文本，不是复核者重写的一份逻辑。

用法：
    M = load_mutant("M2_conformal_no_finite_sample")
    M.calibrate_conformal_domain(...)

约束：不改仓库源码（文件范围只允许 reports/V9-G8/）；所有变异副本落在 tempdir。
"""
from __future__ import annotations

import hashlib
import importlib
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterable

REPO = Path(__file__).resolve().parents[2]
SRC_PKG = REPO / "src/ainerzero/v9/mechanism"

# 每个坏控 = 一组 (文件名, 原文, 替换文)；每处替换必须**恰好命中一次**，否则报错（防止静默失效）
MUTANTS: dict[str, list[tuple[str, str, str]]] = {
    # 坏控 1a：把 PARAMETRIC 与 STRUCTURAL 的判定块**字面调换**（STRUCTURAL 先判，PARAMETRIC 兜剩下的区间）
    # 语义上应与原实现等价 —— 这条坏控如果能让任何测试变红，说明测试抓的不是"顺序"而是别的。
    "M1a_swap_param_structural_literal": [
        (
            "sufficiency_gate.py",
            "        if nis_hold <= q_hold_high:\n            full_posterior = identify_parameters_bayesian(context, prior_belief)",
            "        if nis_hold > q_hold_high:\n"
            "            # MUTANT M1a: STRUCTURAL 判定块提到 PARAMETRIC 之前（字面调换顺序）\n"
            "            self._structural_failure_pool.append(context)\n"
            "            _k = len(self.structural_independent_contexts)\n"
            "            rec = MSGRouteRecord(\n"
            "                context_id=context.context_id,\n"
            "                t_ticks=context.t_start,\n"
            "                route_code=RouteCode.STRUCTURAL,\n"
            "                reason=(\n"
            "                    f'MUTANT M1a: holdout NIS={nis_hold:.2f} > {q_hold_high:.2f}; '\n"
            "                    f'|I_indep|={_k}/{self.registration.K}'\n"
            "                ),\n"
            "                nis_stat=nis_full,\n"
            "                dof=dof_full,\n"
            "                registration_sha=self._reg_sha,\n"
            "            )\n"
            "            self._route_history.append(rec)\n"
            "            return rec\n"
            "\n"
            "        if nis_hold >= q_hold_low:\n"
            "            full_posterior = identify_parameters_bayesian(context, prior_belief)",
        )
    ],
    # 坏控 1b：把 STRUCTURAL 判到 PARAMETRIC **之前**且不做参数再辨识/留出复检
    # （这才是 ADR「第 5 条先于第 7 条」被违反的实质版本：参数没辨识干净就宣称新结构）
    "M1b_structural_before_parametric": [
        (
            "sufficiency_gate.py",
            "        # 5. PARAMETRIC: fit p(phi|D) on first half of window, test on holdout second half (ADR-0014 §2 D1 row 5)\n"
            "        w = context.states.shape[0]",
            "        # MUTANT M1b: 上尾直接判 STRUCTURAL，跳过参数再辨识与留出复检\n"
            "        self._structural_failure_pool.append(context)\n"
            "        _k = len(self.structural_independent_contexts)\n"
            "        rec = MSGRouteRecord(\n"
            "            context_id=context.context_id,\n"
            "            t_ticks=context.t_start,\n"
            "            route_code=RouteCode.STRUCTURAL,\n"
            "            reason=(\n"
            "                f'MUTANT M1b: full-window NIS={nis_full:.2f} > {q_high:.2f} without parametric re-fit; '\n"
            "                f'|I_indep|={_k}/{self.registration.K}'\n"
            "            ),\n"
            "            nis_stat=nis_full,\n"
            "            dof=dof_full,\n"
            "            registration_sha=self._reg_sha,\n"
            "        )\n"
            "        self._route_history.append(rec)\n"
            "        return rec\n"
            "\n"
            "        # 5. PARAMETRIC: fit p(phi|D) on first half of window, test on holdout second half (ADR-0014 §2 D1 row 5)\n"
            "        w = context.states.shape[0]",
        )
    ],
    # 坏控 2：去掉共形有限样本修正（k = ceil((1-alpha)*n) 且不再因 k>n 作废证书）
    "M2_conformal_no_finite_sample": [
        (
            "promotion_gate.py",
            "    k_ord = int(math.ceil((1.0 - registration.alpha_dom) * (n_cal + 1)))",
            "    k_ord = int(math.ceil((1.0 - registration.alpha_dom) * n_cal))",
        ),
        (
            "promotion_gate.py",
            "    if n_cal < registration.n_cal_min or k_ord > n_cal or n_cal == 0:",
            "    if n_cal < registration.n_cal_min or n_cal == 0:",
        ),
    ],
    # 坏控 3：让"做选择"的视图与"做检验"的视图重叠（data thinning 失效）
    "M3_discovery_test_overlap": [
        (
            "discovery.py",
            "    return r + z, r - z",
            "    return r + z, r + z  # MUTANT M3: 检验视图 = 选择视图（发现与检验数据重叠）",
        )
    ],
    # 坏控 4：去掉正交投影（单上下文 API 与 discover 批量路径都去掉）
    "M4_no_orthogonal_projection": [
        (
            "identification.py",
            "    absorbed_vec = q_basis @ (q_basis.T @ r_vec)\n    r_perp_vec = r_vec - absorbed_vec",
            "    absorbed_vec = np.zeros_like(r_vec)  # MUTANT M4\n    r_perp_vec = r_vec.copy()  # MUTANT M4: 不投影",
        ),
        (
            "discovery.py",
            "        proj = stacked - q_pool @ (q_pool.T @ stacked)",
            "        proj = stacked.copy()  # MUTANT M4: 不投影",
        ),
    ],
    # 反向坏控 5：把 e-LOND 总闸门恒置 False。如果准入结论不变，说明这个"总闸门"没有接线。
    "M5_elond_gate_always_false": [
        (
            "promotion_gate.py",
            "        e_lond_passed = bool(e_pers >= (1.0 / max(alpha_per_cand, 1e-15)) or sup_passed)",
            "        e_lond_passed = False  # MUTANT M5: 总闸门恒不通过",
        )
    ],
    # 反向坏控 6：去掉"空候选"这条前置拒绝（检验负对照是否只能靠它成立）
    "M6_allow_empty_candidate": [
        (
            "promotion_gate.py",
            "        if len(candidate.active_terms) == 0:\n"
            "            reasons.append(\"candidate has 0 active terms (empty discovery)\")",
            "        if False:  # MUTANT M6: 不再因空候选直接拒绝\n"
            "            reasons.append(\"candidate has 0 active terms (empty discovery)\")",
        )
    ],
}

_BASE = Path(tempfile.mkdtemp(prefix="g8_mutants_"))
_LOADED: dict[str, object] = {}


def _apply(src: str, patches: Iterable[tuple[str, str, str]]) -> dict[str, str]:
    files = {p.name: p.read_text(encoding="utf-8") for p in SRC_PKG.glob("*.py")}
    for fname, old, new in patches:
        if fname not in files:
            raise KeyError(f"unknown mutant target file {fname!r}")
        hits = files[fname].count(old)
        if hits != 1:
            raise RuntimeError(f"mutation patch for {fname!r} matched {hits} times (must be exactly 1)")
        files[fname] = files[fname].replace(old, new)
    return files


def load_mutant(name: str):
    """构建（并缓存）一个变异包，返回模块对象。"""
    if name in _LOADED:
        return _LOADED[name]
    if name not in MUTANTS:
        raise KeyError(f"unknown mutant {name!r}; known: {sorted(MUTANTS)}")
    pkg_name = "cmfl_mech_" + hashlib.sha1(name.encode()).hexdigest()[:8]
    pkg_dir = _BASE / pkg_name
    if pkg_dir.exists():
        shutil.rmtree(pkg_dir)
    pkg_dir.mkdir(parents=True)
    for fname, text in _apply(name, MUTANTS[name]).items():
        (pkg_dir / fname).write_text(text, encoding="utf-8")
    if str(_BASE) not in sys.path:
        sys.path.insert(0, str(_BASE))
    mod = importlib.import_module(pkg_name)
    _LOADED[name] = mod
    return mod


def mutant_digest(name: str) -> dict[str, str]:
    """记录变异后各文件的 SHA-256，便于报告里核对坏控确实改到了东西。"""
    files = _apply(name, MUTANTS[name])
    return {f: hashlib.sha256(t.encode()).hexdigest() for f, t in sorted(files.items())}
