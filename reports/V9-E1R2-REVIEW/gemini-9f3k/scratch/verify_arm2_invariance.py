import json, glob, numpy as np
from pathlib import Path
from ainerzero.v9.experiments.e1.arms_net import PureNetArm
from ainerzero.v9.experiments.e1.eval_runner import evaluate_episode

families = ["P", "S"]
seeds = [42, 43, 44]

arm2_diffs = {}
global_max_diff = 0.0

for fam in families:
    s_files = sorted(glob.glob(f"artifacts/v9/e1/phase2/datasets/student/{fam}/development/*.json"))
    t_files = sorted(glob.glob(f"artifacts/v9/e1/phase2/datasets/evaluator/{fam}/development/*.json"))
    s_eps = [json.loads(Path(f).read_text(encoding="utf-8")) for f in s_files]
    t_eps = {ep["sequence_id"]: ep for ep in (json.loads(Path(f).read_text(encoding="utf-8")) for f in t_files)}

    for seed in seeds:
        key = f"arm2_{fam}_{seed}"
        ckpt_file = Path(f"artifacts/v9/e1/phase2/checkpoints/arm2_{fam}_seed{seed}/model_weights.npz")
        eval_json_file = Path(f"artifacts/v9/e1/phase2/eval/eval_{key}.json")
        
        saved_eval = json.loads(eval_json_file.read_text(encoding="utf-8"))
        saved_preds = {ep["sequence_id"]: ep["pred_positions"] for ep in saved_eval["episodes"]}
        
        model = PureNetArm(seed=seed)
        model.load(ckpt_file)
        
        max_diff = 0.0
        compared_points = 0
        for s_ep in s_eps:
            sid = s_ep["sequence_id"]
            eval_res = evaluate_episode(model, s_ep, t_eps[sid])
            new_pred = eval_res["pred_positions"]
            old_pred = saved_preds[sid]
            for b in new_pred:
                arr_new = np.asarray(new_pred[b], dtype=np.float64)
                arr_old = np.asarray(old_pred[b], dtype=np.float64)
                diff = float(np.max(np.abs(arr_new - arr_old)))
                if diff > max_diff:
                    max_diff = diff
                compared_points += arr_new.size
                
        if max_diff > global_max_diff:
            global_max_diff = max_diff
            
        arm2_diffs[key] = {
            "family": fam,
            "seed": seed,
            "episodes": len(s_eps),
            "points_compared": compared_points,
            "max_difference": max_diff,
            "can_reuse": bool(max_diff == 0.0 or max_diff < 1e-7),
        }
        print(f"{key:15}: ep={len(s_eps):3d}, points={compared_points:6d}, max_diff={max_diff:.2e}, reusable={arm2_diffs[key]['can_reuse']}")

print(f"GLOBAL MAX DIFFERENCE: {global_max_diff:.2e}")

with open("reports/V9-E1R2-REVIEW/gemini-9f3k/scratch/arm2_diffs.json", "w") as f:
    json.dump({"global_max_diff": global_max_diff, "arms": arm2_diffs}, f, indent=2)
