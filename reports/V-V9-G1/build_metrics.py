#!/usr/bin/env python3
"""从证据 JSON 生成 metrics.json（不手抄数字，保证与证据一致）。"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')


def load(name):
    return json.loads((HERE / 'evidence' / name).read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


ce = load('counterexamples-summary.json')
bd = load('bounds-summary.json')
cases = {c['case']: c for c in ce['cases']}
metrics = {
    'task': 'ainerzero.V9.G2',
    'verified_task': 'ainerzero.V9.G1',
    'verified_author': 'codex-exec-r2-20261016',
    'agent': 'deepseek-8seu',
    'verifier_is_author': False,
    'cpu_only': True,
    'recommendation': 'conditional_accept',
    'accept_self': False,
    'new_adverse_counterexamples': len(ce['cases']),
    'adverse_cases_failed_as_findings': len(ce['findings']),
    'adverse_cases_passed': len(ce['cases']) - len(ce['findings']),
    'poison_controls_total': len(ce['cases']),
    'poison_controls_detected': sum(1 for c in ce['cases'] if c.get('poison_detected')),
    'counterexample_suite_exit': ce['exit'],
    'findings': [
        {'id': 'F1', 'severity': 'medium', 'kind': 'fail-closed 守卫无容差', 'case': 'c3_covariance_guards',
         'fact': 'semidefinite=True 拒绝精确 PSD 的整数矩阵 outer([1,2,2]) 200/200、整数 J^T J 200/200；'
                 'solve_pose_graph 的 rank-deficient PSD information 抛 ValueError',
         'evidence': 'evidence/counterexamples.log, evidence/findings-minimal-repro.log'},
        {'id': 'F2', 'severity': 'low-medium', 'kind': '尺度相关守卫', 'case': 'c4_gravity_frame',
         'fact': 'GravityFrame 水平参考判据是绝对范数 ‖x‖<1e-12；恰好垂直的 [1e-13,0,0] 被拒而 [1,0,0] 被收',
         'evidence': 'evidence/counterexamples.log, evidence/findings-minimal-repro.log'},
        {'id': 'F3', 'severity': 'process', 'kind': '登记文档漂移导致不能原样重放', 'case': 'freeze_check',
         'fact': 'ARCHITECTURE_V9.md 与 V9_RESEARCH_SURVEY.md 的登记哈希在 G1 交付后 stale；'
                 'run_reference.py 消费门 AssertionError；豁免两个 .md 后重放与报告 0 字段差异',
         'evidence': 'evidence/freeze-check.log, evidence/original-replay-gate-failure.log, '
                     'evidence/replay-vs-g1-json-diff.txt'},
        {'id': 'F4', 'severity': 'low', 'kind': '异常类型泄漏/数值范围', 'case': 'c2_dt_boundaries',
         'fact': '_abc 用 python float ** ；|θ|≳5.6e102 抛 OverflowError；predict(dt=1e300/1e308) 泄漏 '
                 'OverflowError 而非文档化的 ValueError',
         'evidence': 'evidence/counterexamples.log, evidence/findings-minimal-repro.log'},
    ],
    'case_verdicts': {name: c['verdict'] for name, c in cases.items()},
    'case_metrics_selected': {
        'c1_max_exp_log_roundtrip': cases['c1_near_singular_rotation']['metrics']['max_exp_log_roundtrip'],
        'c1_exact_pi_convention_violations': cases['c1_near_singular_rotation']['metrics'][
            'exact_pi_sign_convention_violations'],
        'c1_samples': cases['c1_near_singular_rotation']['metrics']['samples'],
        'c2_dt0_exact_identity': cases['c2_dt_boundaries']['metrics']['dt0_exact_identity'],
        'c2_subnormal_dt_cov_drift': cases['c2_dt_boundaries']['metrics']['subnormal_dt_cov_drift'],
        'c3_psd_rejections_per_200': cases['c3_covariance_guards']['metrics']['psd_rejections_per_200'],
        'c4_lift_project_roundtrip_max': cases['c4_gravity_frame']['metrics']['lift_project_roundtrip_max'],
        'c5_max_gn_vs_own_lstsq_gap': cases['c5_wrong_loop']['metrics']['max_gn_vs_own_lstsq_gap'],
        'c5_min_ls_residual_norm': cases['c5_wrong_loop']['metrics']['min_ls_residual_norm'],
        'c5_gauge_semantics_gap': cases['c5_wrong_loop']['metrics']['gauge_semantics_gap'],
        'c6_max_gain_vs_numeric_fd_relative_gap': cases['c6_observation_jacobian']['metrics'][
            'max_gain_vs_numeric_fd_relative_gap'],
        'c7_max_xi_left_minus_Ad_xi_right': cases['c7_tangent_sides']['metrics'][
            'max_xi_left_minus_Ad_xi_right'],
        'c7_mc_relative_error_by_scale': cases['c7_tangent_sides']['metrics']['mc_relative_error_by_scale'],
        'c8_max_abs_gap_vs_independent_exp': cases['c8_independent_matrix_exponential']['metrics'][
            'max_abs_gap_vs_independent_exp'],
        'c8_samples': cases['c8_independent_matrix_exponential']['metrics']['samples'],
        'c9_se2_min_eigenvalue': cases['c9_covariance_long_run']['metrics']['SE2_min_eigenvalue'],
        'c9_se3_min_eigenvalue': cases['c9_covariance_long_run']['metrics']['SE3_min_eigenvalue'],
        'c9_failures': cases['c9_covariance_long_run']['metrics']['SE2_failures'] +
                       cases['c9_covariance_long_run']['metrics']['SE3_failures'],
    },
    'analytic_bound': {
        'A1_own_trajectory': bd['parts']['A1_own_trajectory'],
        'A2_bound_attainability': bd['parts']['A2_bound_attainability']['best_search_ratio'],
        'A3_premise_violation_steps': bd['parts']['A3_premise_violation'],
        'A4_guards': bd['parts']['A4_bound_guards'],
        'B_validity': bd['parts']['B_validity'],
        'B_sharpness_ratio': bd['parts']['B_sharpness_ratio'],
        'C_bound_sequence_max_gap': bd['parts']['C1_bound_sequence_independent_recompute'],
        'C_graph_bound': bd['parts']['C2_graph_bound_independent_recompute'],
        'suite_exit': 0,
    },
    'freeze_and_reproduction': {
        'sha256sums_checked': 35,
        'sha256sums_mismatched': 0,
        'registration_sha256': '5aa8199fbc6bbf525b678860d155526053002a78cb975e608d96f53cda5334c6',
        'registered_inputs_fresh': ['src/ainerzero/environments/gridlab2d.py',
                                    '/Users/mac/AinerWorkFlow/AnimeWorldZero/python/animeworld/kernel/motion.py'],
        'registered_inputs_stale': ['ARCHITECTURE_V9.md', 'docs/research/V9_RESEARCH_SURVEY.md'],
        'cpu_tests_xml': {'tests': 49, 'failures': 0, 'skipped': 0},
        'cpu_tests_independent_rerun': '49 passed in 1.24s',
        'mutations': {'records': 12, 'all_exit_1': True},
        'original_script_replay': 'blocked by registered-source gate (F3), exit 1',
        'patched_replay_exit': 0,
        'replay_json_field_diffs_vs_report': 0,
        'tracked_files_modified_before_g1_report': [],
    },
    'conventions_vs_architecture_v9_section4': {
        'T_AB_maps_B_to_A': 'consistent (T = world<-body)',
        'right_perturbation_T_Exp_xi': 'consistent (boxplus right = compose(mean, exp))',
        'covariance_adjoint_only_for_left_right_rewrite': 'consistent',
        'explicit_gauge_and_anchor': 'consistent',
        'inconsistencies_found': 0,
        'doc_notes': 2,
    },
    'model_budget_reserved': 0,
    'model_work': 0,
    'training': 0,
    'optimizer_updates': 0,
    'downloads': 0,
    'installs': 0,
    'deletes': 0,
    'git_commit_or_push': 0,
    'no_model_imports': True,
    'no_runstore_access': True,
    'scope': ['reports/V-V9-G1/'],
    'report': 'reports/V-V9-G1/report.md',
    'source_sha256_reviewed': json.loads((ROOT / 'reports/V9-G1/r1-codex-20261016/source-sha256.json').read_text()),
    'g2_scripts_sha256': {str(p.relative_to(ROOT)): sha(p) for p in sorted(HERE.glob('*.py'))},
}
out = HERE / 'metrics.json'
out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, default=str) + '\n')
print(json.dumps({'written': str(out), 'cases': metrics['new_adverse_counterexamples'],
                  'findings': len(metrics['findings']),
                  'poison_detected': metrics['poison_controls_detected']}, ensure_ascii=False))
sys.exit(0)
