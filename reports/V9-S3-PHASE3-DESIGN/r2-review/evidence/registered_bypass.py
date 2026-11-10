"""演示：verify_generation.py 绕过登记分区守卫。只在复核者的副本里，把自起的 s3p3x-rvreg 当作登记分区，从不碰 s3p3-*。
用法：registered_bypass.py <改过 REGISTERED 的副本根> <输出目录>
"""
import json, subprocess, sys
from pathlib import Path
RC, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(RC / "src"))
from ainerzero.v9.experiments.s3 import persist as PS
NS = "s3p3x-rvreg"
assert NS in PS.REGISTERED and not NS.startswith("s3p3-")
res = {}
try:
    PS.generate_sequence(NS, 0, n_episodes=2)
    res["direct_generate_sequence"] = "generated"
except PermissionError as exc:
    res["direct_generate_sequence"] = f"refused: {exc}"
fake = OUT / "fake.jsonl"
fake.write_text(json.dumps({"world": 0, "observations": [], "queries": [], "fast_events": [], "world_seed": 0, "layout_sha256": ""}) + "\n")
r = subprocess.run([sys.executable, "-I", str(RC / "reports/V9-S3-PHASE3/verify_generation.py"), str(fake), NS, "2"], capture_output=True, text=True)
out = json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-500:]}
res["verify_generation_on_a_fake_log"] = {"returncode": r.returncode, "problems": out.get("problems"), "passed": out.get("passed")}
json.dump(res, open(OUT / "registered_bypass.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
