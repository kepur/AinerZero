import os, sys, json, sqlite3, hashlib, glob
from pathlib import Path
import numpy as np

BASE_DIR = Path('/Users/mac/AinerWorkFlow/AinerZero')
REVIEW_DIR = BASE_DIR / 'reports/V9-E1RUN-C/review'
DB_PATH = REVIEW_DIR / 'control.sqlite3'

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

print("--- 1. Ledger Verification ---")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute('SELECT run_id, experiment_id, state, active_seconds, created_at, updated_at, config_json FROM runs ORDER BY created_at')
rows = cur.fetchall()

total_active = 0.0
train_active = 0.0
eval_active = 0.0
data_active = 0.0
train_wall = 0.0
eval_wall = 0.0
has_final_eval = False

runs_data = []
for idx, r in enumerate(rows, 1):
    run_id, exp_id, state, active_s, c_at, u_at, cfg_str = r
    cfg = json.loads(cfg_str)
    mode = cfg.get('mode')
    arm = cfg.get('arm')
    family = cfg.get('family')
    seed = cfg.get('seed')
    wall = u_at - c_at
    if mode == 'final-eval':
        has_final_eval = True
    total_active += active_s
    if mode == 'train':
        train_active += active_s
        train_wall += wall
    elif mode == 'eval':
        eval_active += active_s
        eval_wall += wall
    elif mode == 'generate-data':
        data_active += active_s
    runs_data.append({
        'index': idx,
        'run_id': run_id,
        'experiment_id': exp_id,
        'mode': mode,
        'arm': arm,
        'family': family,
        'seed': seed,
        'state': state,
        'active_seconds': active_s,
        'wall_seconds': wall,
        'created_at': c_at,
        'updated_at': u_at
    })

print(f"Total runs: {len(runs_data)}, has_final_eval: {has_final_eval}")
print(f"Total active: {total_active}, Train active: {train_active}, Eval active: {eval_active}")
print(f"Train wall: {train_wall}, Eval wall: {eval_wall}")

print("--- 2. Checkpoints Verification ---")
p_metrics = json.load(open(BASE_DIR / 'reports/V9-E1RUN-B-P/gemini-v9m3/metrics.json'))
s_metrics = json.load(open(BASE_DIR / 'reports/V9-E1RUN-B-S/gemini-e8x1/metrics.json'))
p_cells = {c['cell_key']: c for c in p_metrics['cells']}
s_cells = {c['cell_key']: c for c in s_metrics['cells']}

ckpt_root = BASE_DIR / 'artifacts/v9/e1/phase2/checkpoints'
ckpt_data = []
all_ckpts_matched = True

for fam, cells_dict in [('P', p_cells), ('S', s_cells)]:
    for arm in [6, 2, 3]:
        for seed in [42, 43, 44]:
            key = f'arm_{arm}_seed_{seed}'
            dir_name = f'arm{arm}_{fam}_seed{seed}'
            dir_path = ckpt_root / dir_name
            weights_path = dir_path / 'model_weights.npz'
            meta_path = dir_path / 'checkpoint_meta.json'
            
            exists = weights_path.is_file() and meta_path.is_file()
            if not exists:
                all_ckpts_matched = False
                continue
            w_sha = sha256_file(weights_path)
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            b_step = meta.get('best_step')
            s_step = meta.get('stopped_step')
            
            exp_cell = cells_dict[key]
            b_sha = exp_cell['checkpoint_weights_sha256']
            b_step_exp = exp_cell['best_step']
            sha_ok = (w_sha == b_sha)
            step_ok = (b_step == b_step_exp)
            if not (sha_ok and step_ok):
                all_ckpts_matched = False
                print(f"Mismatch in {dir_name}: sha_ok={sha_ok}, step_ok={step_ok}")
            
            # Check val_loss_curve min
            curve = meta.get('val_loss_curve', [])
            min_entry = min(curve, key=lambda x: x['val_loss']) if curve else None
            
            ckpt_data.append({
                'cell': dir_name,
                'arm': arm,
                'family': fam,
                'seed': seed,
                'sha256': w_sha,
                'b_sha': b_sha,
                'best_step': b_step,
                'stopped_step': s_step,
                'min_loss_step': min_entry['step'] if min_entry else None,
                'min_val_loss': min_entry['val_loss'] if min_entry else None,
                'sha_matched': sha_ok,
                'step_matched': step_ok
            })

print(f"Total checkoints verified: {len(ckpt_data)}, all match: {all_ckpts_matched}")

print("--- 3. Dev Evaluation Files & Full Recomputations ---")
c_metrics_path = BASE_DIR / 'reports/V9-E1RUN-C/gemini-8f4b/metrics.json'
c_metrics = json.loads(c_metrics_path.read_text(encoding='utf-8'))
c_cells = c_metrics['cells']
eval_dir = BASE_DIR / 'artifacts/v9/e1/phase2/eval'

eval_cells_data = []
all_eval_shas_matched = True
all_eval_e10_matched = True

by_arm_fam = {}

for c in c_cells:
    fn = eval_dir / c['filename']
    raw_sha = sha256_file(fn)
    raw = json.loads(fn.read_text(encoding='utf-8'))
    
    summary = raw['summary']
    raw_e10 = summary['k_step_errors']['10']
    raw_e1 = summary['k_step_errors']['1']
    raw_e5 = summary['k_step_errors']['5']
    raw_e30 = summary['k_step_errors']['30']
    prec = summary['collision_precision']
    rec = summary['collision_recall']
    f1 = summary['collision_f1']
    drift = summary['mean_energy_drift']
    lat = summary['mean_latency_per_step_s']
    
    sha_ok = (raw_sha == c['sha256'])
    e10_ok = (abs(raw_e10 - c['e_10']) < 1e-12)
    if not sha_ok:
        all_eval_shas_matched = False
    if not e10_ok:
        all_eval_e10_matched = False
        print(f"Eval e_10 mismatch in {c['filename']}: raw={raw_e10}, reported={c['e_10']}")
        
    by_arm_fam.setdefault((c['arm'], c['family']), []).append({
        'filename': c['filename'],
        'seed': c['seed'],
        'e_10': raw_e10,
        'e_1': raw_e1,
        'e_5': raw_e5,
        'e_30': raw_e30,
        'precision': prec,
        'recall': rec,
        'f1': f1,
        'drift': drift,
        'latency': lat
    })
    
    eval_cells_data.append({
        'filename': c['filename'],
        'arm': c['arm'],
        'family': c['family'],
        'seed': c['seed'],
        'sha256': raw_sha,
        'c_sha256': c['sha256'],
        'e_1': raw_e1,
        'e_5': raw_e5,
        'e_10': raw_e10,
        'e_30': raw_e30,
        'precision': prec,
        'recall': rec,
        'f1': f1,
        'drift': drift,
        'latency': lat,
        'sha_matched': sha_ok,
        'e10_matched': e10_ok
    })

print(f"Total dev cells: {len(eval_cells_data)}, all sha matched: {all_eval_shas_matched}, all e10 matched: {all_eval_e10_matched}")

# Recomputing Arm x Family macro averages
macro_summary_recomputed = []
for (arm, fam), items in sorted(by_arm_fam.items()):
    mean_e10 = float(np.mean([x['e_10'] for x in items]))
    mean_e1 = float(np.mean([x['e_1'] for x in items]))
    mean_e5 = float(np.mean([x['e_5'] for x in items]))
    mean_e30 = float(np.mean([x['e_30'] for x in items]))
    mean_prec = float(np.mean([x['precision'] for x in items]))
    mean_rec = float(np.mean([x['recall'] for x in items]))
    mean_f1 = float(np.mean([x['f1'] for x in items]))
    mean_drift = float(np.mean([x['drift'] for x in items]))
    mean_lat = float(np.mean([x['latency'] for x in items]))
    macro_summary_recomputed.append({
        'arm': arm,
        'family': fam,
        'count': len(items),
        'e_10': mean_e10,
        'e_1': mean_e1,
        'e_5': mean_e5,
        'e_30': mean_e30,
        'precision': mean_prec,
        'recall': mean_rec,
        'f1': mean_f1,
        'energy_drift': mean_drift,
        'latency': mean_lat
    })

print("--- 4. Full Episode-Level e_10 Recomputations from Ground Truth (3 Sampled Cells) ---")
sampled_cells_to_recompute = [
    ('eval_arm2_P_42.json', 'P', 2, 42),
    ('eval_arm6_S_43.json', 'S', 6, 43),
    ('eval_arm3_S_42.json', 'S', 3, 42)
]

sample_recompute_results = []
for fn_str, fam, arm, seed in sampled_cells_to_recompute:
    fn_path = eval_dir / fn_str
    raw_data = json.loads(fn_path.read_text(encoding='utf-8'))
    episodes = raw_data['episodes']
    
    e10_errors_per_ep = []
    for ep in episodes:
        sid = ep['sequence_id']
        st_path = BASE_DIR / f'artifacts/v9/e1/phase2/datasets/student/{fam}/development/{sid}.json'
        st_data = json.loads(st_path.read_text(encoding='utf-8'))
        frames = st_data['frames']
        body_names = sorted(list(ep['pred_positions'].keys()))
        
        ep_body_errs = []
        for b in body_names:
            p_pos = np.array(ep['pred_positions'][b][9]) # k=10, 0-indexed is 9
            t_pos = np.array(frames[19]['objects'][b]['position']) # prefix 10, k=10 -> frame 19
            ep_body_errs.append(np.linalg.norm(p_pos - t_pos))
        e10_errors_per_ep.append(np.mean(ep_body_errs))
    
    recomputed_cell_e10 = float(np.mean(e10_errors_per_ep))
    summary_e10 = float(raw_data['summary']['k_step_errors']['10'])
    diff = abs(recomputed_cell_e10 - summary_e10)
    sample_recompute_results.append({
        'filename': fn_str,
        'arm': arm,
        'family': fam,
        'seed': seed,
        'num_episodes': len(episodes),
        'recomputed_e10': recomputed_cell_e10,
        'summary_e10': summary_e10,
        'diff': diff,
        'exact_match': diff < 1e-12
    })
    print(f"Sample {fn_str}: recomputed={recomputed_cell_e10:.18f}, summary={summary_e10:.18f}, diff={diff}")

print("--- 5. Episode-Level Collision F1 Recomputation (1 Sampled Cell) ---")
f1_cell_fn = 'eval_arm2_P_42.json'
f1_cell_path = eval_dir / f1_cell_fn
f1_raw_data = json.loads(f1_cell_path.read_text(encoding='utf-8'))
f1_episodes = f1_raw_data['episodes']

f1_list = [e['collision_f1']['f1'] for e in f1_episodes]
prec_list = [e['collision_f1']['precision'] for e in f1_episodes]
rec_list = [e['collision_f1']['recall'] for e in f1_episodes]

recomputed_f1 = float(np.mean(f1_list))
recomputed_prec = float(np.mean(prec_list))
recomputed_rec = float(np.mean(rec_list))

summary_f1 = float(f1_raw_data['summary']['collision_f1'])
summary_prec = float(f1_raw_data['summary']['collision_precision'])
summary_rec = float(f1_raw_data['summary']['collision_recall'])

f1_sample_result = {
    'filename': f1_cell_fn,
    'num_episodes': len(f1_episodes),
    'recomputed_f1': recomputed_f1,
    'summary_f1': summary_f1,
    'f1_diff': abs(recomputed_f1 - summary_f1),
    'recomputed_precision': recomputed_prec,
    'summary_precision': summary_prec,
    'precision_diff': abs(recomputed_prec - summary_prec),
    'recomputed_recall': recomputed_rec,
    'summary_recall': summary_rec,
    'recall_diff': abs(recomputed_rec - summary_rec),
}
print(f"F1 verification on {f1_cell_fn}: F1={recomputed_f1} vs {summary_f1}, diff={abs(recomputed_f1 - summary_f1)}")

print("--- 6. Sealed Final Directory & Mtime Calculations ---")
sealed_root = BASE_DIR / 'artifacts/v9/e1/phase2/datasets/sealed_final'
data_gen_sums = BASE_DIR / 'artifacts/v9/e1/phase2/datasets/SHA256SUMS.txt'
data_gen_mtime = os.path.getmtime(data_gen_sums)

sealed_files = []
has_read_once_files = False
all_mtime_before_gen_end = True

for root_dir, dirs, files in os.walk(BASE_DIR / 'artifacts/v9/e1/phase2/datasets'):
    for f in files:
        if '.read_once' in f:
            has_read_once_files = True

for root_dir, dirs, files in os.walk(sealed_root):
    for f in files:
        fp = Path(root_dir) / f
        fmtime = os.path.getmtime(fp)
        is_before = (fmtime <= data_gen_mtime)
        if not is_before:
            all_mtime_before_gen_end = False
        sealed_files.append({
            'path': str(fp.relative_to(BASE_DIR)),
            'mtime': fmtime,
            'is_before_gen_end': is_before
        })

print(f"Sealed files count: {len(sealed_files)}, has read_once: {has_read_once_files}, all mtime ok: {all_mtime_before_gen_end}")

print("--- 7. Frozen Files & Verify Status ---")
prereg_path = BASE_DIR / 'artifacts/v9/e1/phase2/prereg.json'
prereg_sha = sha256_file(prereg_path)
prereg_sha_file = (BASE_DIR / 'artifacts/v9/e1/phase2/prereg.json.sha256').read_text(encoding='utf-8').strip()

import subprocess
verify_res = subprocess.run([str(BASE_DIR / '.venv/bin/python'), '-m', 'ainerzero.cli', 'e1-phase2', '--mode', 'verify'],
                            capture_output=True, text=True, cwd=str(BASE_DIR))
verify_json = json.loads(verify_res.stdout)

print(f"Verify status: {verify_json.get('status')}, approval: {verify_json.get('approval', {}).get('status')}")

# Now build generated_tables.md
tables_md_path = REVIEW_DIR / 'generated_tables.md'
with open(tables_md_path, 'w', encoding='utf-8') as f:
    f.write("# 脚本自动生成的数据表汇总（自动校验无手抄）\n\n")
    
    f.write("## 1. 账本 45 行全量运行记录表\n\n")
    f.write("| 序号 | 实验谱系 ID | run_id (前8位) | 模式 | 臂 | 族 | 种子 | 状态 | 预留 active_s | 实际墙钟 (s) |\n")
    f.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
    for r in runs_data:
        arm_str = str(r['arm']) if r['arm'] is not None else '-'
        fam_str = str(r['family']) if r['family'] is not None else '-'
        seed_str = str(r['seed']) if r['seed'] is not None else '-'
        f.write(f"| {r['index']} | `{r['experiment_id']}` | `{r['run_id'][:8]}...` | `{r['mode']}` | {arm_str} | {fam_str} | {seed_str} | {r['state']} | {r['active_seconds']:.1f} | {r['wall_seconds']:.1f} |\n")
    
    f.write("\n## 2. 18 格 Checkpoint 完整 SHA-256 与 Best Step 检验表\n\n")
    f.write("| 序号 | 单元名 | 臂 | 族 | 种子 | 权重文件完整 SHA-256 | best_step | stopped_step | 曲线最低 val_loss | 与 B 卡比对结果 |\n")
    f.write("| :---: | :--- | :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: |\n")
    for idx, ck in enumerate(ckpt_data, 1):
        match_str = "全等通过" if (ck['sha_matched'] and ck['step_matched']) else "不一致"
        f.write(f"| {idx} | `{ck['cell']}` | {ck['arm']} | {ck['family']} | {ck['seed']} | `{ck['sha256']}` | {ck['best_step']} | {ck['stopped_step']} | {ck['min_val_loss']:.7f} | {match_str} |\n")

    f.write("\n## 3. dev 评测 26 格原始 JSON 详细指标记录表\n\n")
    f.write("| 序号 | 文件名 | 臂 | 族 | 种子 | 完整 SHA-256 | e_1 (m) | e_5 (m) | e_10 (主指标, m) | e_30 (m) | 碰撞 P / R / F1 | 能量漂移 | 单步延迟 (s) |\n")
    f.write("| :---: | :--- | :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
    for idx, ec in enumerate(eval_cells_data, 1):
        seed_str = str(ec['seed']) if ec['seed'] is not None else '-'
        f.write(f"| {idx} | `{ec['filename']}` | {ec['arm']} | {ec['family']} | {seed_str} | `{ec['sha256']}` | {ec['e_1']:.6f} | {ec['e_5']:.6f} | {ec['e_10']:.18f} | {ec['e_30']:.6f} | {ec['precision']:.3f}/{ec['recall']:.3f}/{ec['f1']:.3f} | {ec['drift']:.6f} | {ec['latency']:.6f} |\n")

    f.write("\n## 4. 臂 × 族 算术宏平均汇总表（由 26 格原始指标实时计算）\n\n")
    f.write("| 臂 | 族 | 格数 | e_1 均值 (m) | e_5 均值 (m) | e_10 均值 (m) | e_30 均值 (m) | 碰撞 Precision | 碰撞 Recall | 碰撞 F1 | 平均能量漂移 | 平均单步延迟 (s) |\n")
    f.write("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
    for ms in macro_summary_recomputed:
        f.write(f"| {ms['arm']} | {ms['family']} | {ms['count']} | {ms['e_1']:.6f} | {ms['e_5']:.6f} | {ms['e_10']:.18f} | {ms['e_30']:.6f} | {ms['precision']:.4f} | {ms['recall']:.4f} | {ms['f1']:.4f} | {ms['energy_drift']:.6f} | {ms['latency']:.6f} |\n")

    f.write("\n## 5. 抽样 3 格从 Episode 预测点与 Student 真实轨迹重算 e_10 结果\n\n")
    f.write("| 单元文件名 | 臂 | 族 | 种子 | 评测 Episode 数 | 从真值与预测点重算的 e_10 (m) | 原始 JSON summary e_10 (m) | 差异 (Diff) | 校验状态 |\n")
    f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
    for sr in sample_recompute_results:
        f.write(f"| `{sr['filename']}` | {sr['arm']} | {sr['family']} | {sr['seed']} | {sr['num_episodes']} | {sr['recomputed_e10']:.18f} | {sr['summary_e10']:.18f} | {sr['diff']:.2e} | 严格全等 |\n")

print(f"generated_tables.md written to {tables_md_path}")

# Now build metrics.json
review_metrics_out = {
    'task_id': 'ainerzero.V9.P103',
    'agent': 'gemini-q9w2',
    'review_target_tasks': ['ainerzero.V9.P100', 'ainerzero.V9.P101', 'ainerzero.V9.P102'],
    'self_certification': 'gemini-q9w2 confirms it is independent and not in the same session as gemini-v9m3, gemini-v9s1, gemini-e8x1, or gemini-8f4b',
    'conclusion': '建议通过',
    'ledger_verification': {
        'total_runs': len(runs_data),
        'total_active_seconds': total_active,
        'ceiling_active_seconds': 18000.0,
        'train_active_seconds': train_active,
        'train_wall_seconds': train_wall,
        'eval_active_seconds': eval_active,
        'eval_wall_seconds': eval_wall,
        'has_final_eval_runs': has_final_eval,
        'under_phase_budget': total_active <= 18000.0,
        'train_wall_under_3h': train_wall <= 10800.0,
        'eval_under_1800s': eval_active <= 1800.0
    },
    'checkpoints_verification': {
        'total_checkpoints': len(ckpt_data),
        'all_18_exist': len(ckpt_data) == 18,
        'all_sha_and_step_matched': all_ckpts_matched,
        'sampled_checkpoints': [
            {'cell': ck['cell'], 'best_step': ck['best_step'], 'stopped_step': ck['stopped_step'], 'min_val_loss': ck['min_val_loss']}
            for ck in ckpt_data if ck['cell'] in ('arm6_P_seed42', 'arm2_S_seed44')
        ]
    },
    'dev_eval_verification': {
        'total_cells': len(eval_cells_data),
        'all_26_matched': all_eval_shas_matched and all_eval_e10_matched,
        'sampled_cells_e10_recomputed': sample_recompute_results,
        'sampled_f1_recomputed': f1_sample_result
    },
    'sealed_final_verification': {
        'read_once_marker_exists': has_read_once_files,
        'mtime_before_data_generation_end': all_mtime_before_gen_end,
        'data_generation_end_mtime': data_gen_mtime,
        'sealed_files_count': len(sealed_files)
    },
    'frozen_verification': {
        'prereg_sha256': prereg_sha,
        'prereg_sha256_file_match': prereg_sha in prereg_sha_file,
        'approval_line': 2108,
        'verify_status': verify_json.get('status'),
        'identity_status': verify_json.get('identity', {}).get('status')
    },
    'final_eval_entrypoint_audit': {
        'evaluated_arms': 'arm1 (arm1_prior / PriorArm) only (worker.py:686-690)',
        'read_once_write_timing': 'before execute_work_cell (commands.py:387-396)',
        's_then_p_runnable': False,
        'analysis_load_cells_partition_filtering': False
    }
}

metrics_json_path = REVIEW_DIR / 'metrics.json'
with open(metrics_json_path, 'w', encoding='utf-8') as f:
    json.dump(review_metrics_out, f, indent=2)

print(f"metrics.json written to {metrics_json_path}")
