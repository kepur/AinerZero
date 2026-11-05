import subprocess, os, shutil, json

workspace_src = "reports/V9-E1R2-REVIEW/gemini-9f3k/scratch/mutation_workspace/src/ainerzero/v9/experiments/e1"
workspace_tests = "reports/V9-E1R2-REVIEW/gemini-9f3k/scratch/mutation_workspace/tests"
pythonpath = os.path.abspath("reports/V9-E1R2-REVIEW/gemini-9f3k/scratch/mutation_workspace/src")

mutations = [
    {
        "id": "MUT_1",
        "file": "contact_geometry.py",
        "desc": "Transpose ramp rotation matrix in static_primitive",
        "test": f"{workspace_tests}/test_e1_contact_geometry.py",
        "target": "rot = [[1.0, local_y[0], n[0]], [0.0, local_y[1], n[1]], [0.0, local_y[2], n[2]]]",
        "replace": "rot = [[1.0, 0.0, 0.0], [local_y[0], local_y[1], local_y[2]], [n[0], n[1], n[2]]]",
    },
    {
        "id": "MUT_2",
        "file": "eval_runner.py",
        "desc": "Shift frame index in _predicted_pair_contact_series (PREFIX_FRAMES + t -> t)",
        "test": f"{workspace_tests}/test_e1_eval_runner.py",
        "target": "fr_objects = frames[PREFIX_FRAMES + t][\"objects\"]",
        "replace": "fr_objects = frames[t][\"objects\"]",
    },
    {
        "id": "MUT_3",
        "file": "prior.py",
        "desc": "Invert normal in _sphere_obb_contact",
        "test": f"{workspace_tests}/test_e1_prior_box.py",
        "target": "return depth, R @ (diff / dist)",
        "replace": "return depth, -(R @ (diff / dist))",
    },
    {
        "id": "MUT_4",
        "file": "analysis.py",
        "desc": "Remove partition check in load_cells",
        "test": f"{workspace_tests}/test_e1_final_entry.py",
        "target": "if data.get(\"partition\", partition) != partition:\n            continue",
        "replace": "# partition check removed\n        pass",
    },
]

results = []

env = dict(os.environ)
env["PYTHONPATH"] = pythonpath

for m in mutations:
    filepath = os.path.join(workspace_src, m["file"])
    with open(filepath) as f:
        orig_content = f.read()
    if m["target"] not in orig_content:
        raise ValueError(f"Target not found for mutation {m['id']}")
    
    mutated_content = orig_content.replace(m["target"], m["replace"], 1)
    with open(filepath, "w") as f:
        f.write(mutated_content)
    
    cmd = [".venv/bin/python", "-m", "pytest", m["test"], "-q"]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    
    with open(filepath, "w") as f:
        f.write(orig_content)
    
    caught = (proc.returncode != 0)
    out_lines = proc.stdout.strip().splitlines()
    summary = out_lines[-1] if out_lines else proc.stderr.strip()
    
    res = {
        "id": m["id"],
        "file": m["file"],
        "desc": m["desc"],
        "caught": caught,
        "summary": summary,
    }
    results.append(res)
    print(f"[{m['id']}] {m['desc']}: caught={caught} ({summary})")

with open("reports/V9-E1R2-REVIEW/gemini-9f3k/scratch/mutation_results.json", "w") as f:
    json.dump(results, f, indent=2)
