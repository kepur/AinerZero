"""闭包规模、实际加载模块、加入 s1.metrics 的影响。只导入，不运行 run_phase1 的 main。"""
import json, os, subprocess, sys
from pathlib import Path
base = Path(sys.argv[1]).resolve()
from ainerzero.v9.experiments.s3 import run_guard as G
src = base / "src"; entry = base / "reports/V9-S3-PHASE1/run_phase1.py"
c = G.import_closure(src, [entry]); rel = [str(p.relative_to(base)) for p in c]
print("closure_with_entry", len(rel)); print("non_s3", [r for r in rel if "/s3/" not in r and not r.startswith("reports")])
print("s3_listed_in_prereg", len([r for r in rel if "/s3/" in r]))
manifest = G.build_manifest(base, [entry], src_root=src)
print("check_manifest", G.check_manifest(base, manifest))
code = f'''
import json, sys
sys.path.insert(0, {str(src)!r})
import mlx.core as mx, mlx.nn as nn, mlx.optimizers as optim
from ainerzero.v9.experiments.s3 import analysis as G, arms_mlx as A, batching as B, data as D, spec
from ainerzero.v9.experiments.s3 import run_guard as RG
from pathlib import Path
m = json.loads({json.dumps(json.dumps(manifest))})
print("loaded_project_modules", len([k for k in sys.modules if k == "ainerzero" or k.startswith("ainerzero.")]))
print("check_loaded_modules_without_run_guard_in_manifest", RG.check_loaded_modules(Path({str(base)!r}), m))
m2 = dict(m); m2["src/ainerzero/v9/experiments/s3/run_guard.py"] = "x"
print("check_loaded_modules_with_run_guard", RG.check_loaded_modules(Path({str(base)!r}), m2))
'''
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}); print(r.stdout, r.stderr[-400:])
fake = Path(sys.argv[2]) / "fake_p2_entry.py"
fake.write_text("from ainerzero.v9.experiments.s1.metrics import memory_interference\nfrom ainerzero.v9.experiments.s3 import data, run_guard\n", encoding="utf-8")
c2 = G.import_closure(src, [fake]); r2 = [str(p.relative_to(base)) for p in c2 if p.is_relative_to(base)]
print("closure_if_entry_imports_s1_metrics", len(r2)); print("s1_files", [x for x in r2 if "/s1/" in x])
