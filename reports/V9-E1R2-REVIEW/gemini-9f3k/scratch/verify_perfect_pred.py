import json, glob, numpy as np
from collections import defaultdict
from ainerzero.v9.experiments.e1.eval_runner import evaluate_episode, PREFIX_FRAMES

class GroundTruthArm:
    def __init__(self, current_student_ep=None):
        self.current_student_ep = current_student_ep
    
    def predict(self, observed_prefix, static_env, n_future, geometry_by_body=None):
        frames = self.current_student_ep["frames"]
        res = {}
        for name in observed_prefix.keys():
            traj = []
            for t in range(n_future):
                f = frames[PREFIX_FRAMES + t]["objects"][name]
                p = f["position"]
                v = f["linear_velocity"]
                traj.append(list(p) + list(v))
            res[name] = np.array(traj, dtype=np.float64)
        return res

arm = GroundTruthArm()
results = {}

for fam in ["P", "S"]:
    s_files = sorted(glob.glob(f"artifacts/v9/e1/phase2/datasets/student/{fam}/development/*.json"))
    t_files = sorted(glob.glob(f"artifacts/v9/e1/phase2/datasets/evaluator/{fam}/development/*.json"))
    
    assert len(s_files) == 200 and len(t_files) == 200
    
    truth_by_id = {}
    for tf in t_files:
        with open(tf) as f:
            t_ep = json.load(f)
            truth_by_id[t_ep["sequence_id"]] = t_ep
            
    fam_stats = defaultdict(lambda: {"events": 0, "tp": 0, "fp": 0, "fn": 0, "episodes": 0})
    
    for sf in s_files:
        with open(sf) as f:
            s_ep = json.load(f)
        sid = s_ep["sequence_id"]
        t_ep = truth_by_id[sid]
        arm.current_student_ep = s_ep
        eval_res = evaluate_episode(arm, s_ep, t_ep)
        sc = eval_res["scenario_type"]
        f1_data = eval_res["collision_f1"]
        
        for key in (sc, "ALL"):
            fam_stats[key]["episodes"] += 1
            fam_stats[key]["events"] += f1_data["num_true_events"]
            fam_stats[key]["tp"] += f1_data["true_positives"]
            fam_stats[key]["fp"] += f1_data["false_positives"]
            fam_stats[key]["fn"] += f1_data["false_negatives"]
        
    results[fam] = {k: dict(v) for k, v in fam_stats.items()}

for fam, stats in results.items():
    print(f"=== Family {fam} ===")
    for sc in sorted(stats.keys()):
        d = stats[sc]
        tp, fp, fn = d["tp"], d["fp"], d["fn"]
        p = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 1.0
        print(f"  {sc:20}: ep={d['episodes']:3d}, events={d['events']:3d}, TP={tp:3d}, FP={fp:3d}, FN={fn:3d}, F1={f1:.4f}")

with open("reports/V9-E1R2-REVIEW/gemini-9f3k/scratch/perfect_prediction_results.json", "w") as f:
    json.dump(results, f, indent=2)
