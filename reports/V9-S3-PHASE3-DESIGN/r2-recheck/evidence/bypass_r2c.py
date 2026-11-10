"""在复核者副本里重打 K2b 授权：替身登记名 s3p3x-rvreg（final 型）、s3p3x-rvdev（dev 型），从不碰 s3p3-*。
副本的 ROOT 是 <副本>/artifacts/v9/s3/phase3（在暂存目录里）。每种情形记录 verify_generation 的判定和实际生成了几个世界。
用法：bypass_r2c.py <副本根> <输出目录>
"""
import json, os, shutil, subprocess, sys
from pathlib import Path
RC, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
VG = RC / "reports/V9-S3-PHASE3/verify_generation.py"
ROOT = RC / "artifacts/v9/s3/phase3"
FAKE = json.dumps({"world": 0, "observations": [], "queries": [], "fast_events": [], "world_seed": 0, "layout_sha256": ""}) + "\n"
res = {}


def reset():
    if ROOT.exists() or ROOT.is_symlink():
        shutil.rmtree(RC / "artifacts")
    ROOT.mkdir(parents=True)
    side = OUT / "side"
    if side.exists():
        shutil.rmtree(side)
    side.mkdir()
    return side


def run(name, path, ns="s3p3x-rvreg"):
    log = OUT / f"gen_{name}.log"
    if log.exists():
        log.unlink()
    env = dict(os.environ, RV_GENLOG=str(log))
    r = subprocess.run([sys.executable, "-I", str(VG), str(path), ns, "2"], capture_output=True, text=True, env=env)
    out = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {"exit": r.returncode, "stderr": r.stderr[-200:]}
    gen = len(log.read_text().splitlines()) if log.exists() else 0
    res[name] = {"generated_worlds": gen, "first_problem": (out.get("problems") or [None])[0], "exit": out.get("exit")}
    print(name, res[name], flush=True)


side = reset(); f = side / "worlds.jsonl"; f.write_text(FAKE)
run("01_outside_no_marker", f)
side = reset(); (ROOT / "final-final").mkdir(); (ROOT / "final-final/worlds.jsonl").write_text(FAKE)
run("02_inside_no_marker", ROOT / "final-final/worlds.jsonl")
side = reset(); (side / "worlds.jsonl").write_text(FAKE); (ROOT / "final-final").mkdir(); (ROOT / "FINAL_READ_ONCE.json").write_text("{}")
(ROOT / "final-final/worlds.jsonl").symlink_to(side / "worlds.jsonl")
run("03_symlink_in_run_dir_to_outside_with_marker", ROOT / "final-final/worlds.jsonl")
side = reset(); (side / "worlds.jsonl").write_text(FAKE); (ROOT / "FINAL_READ_ONCE.json").write_text("{}")
(ROOT / "final-final").symlink_to(side, target_is_directory=True)
run("04_run_dir_is_symlink_to_outside_with_marker", ROOT / "final-final/worlds.jsonl")
side = reset(); (ROOT / "final-final").mkdir(); (ROOT / "final-final/worlds.jsonl").write_text(FAKE); (ROOT / "FINAL_READ_ONCE.json").write_text("{}")
run("05_case_variant_dir_with_marker", ROOT / "FINAL-FINAL/worlds.jsonl")
run("06_dotdot_path_with_marker", ROOT / "final-final/../final-final/worlds.jsonl")
(side / "worlds.jsonl").symlink_to(ROOT / "final-final/worlds.jsonl")
run("07_outside_symlink_to_the_run_file_with_marker", side / "worlds.jsonl")
run("08_forged_marker_and_run_dir", ROOT / "final-final/worlds.jsonl")
(ROOT / "FINAL_READ_ONCE.json").unlink(); (ROOT / "FINAL_READ_ONCE.json").mkdir()
run("09_marker_is_a_directory", ROOT / "final-final/worlds.jsonl")
side = reset(); (ROOT / "dev-anything").mkdir(); (ROOT / "dev-anything/worlds.jsonl").write_text(FAKE); (ROOT / "dev_uses.json").write_text("[]")
run("10_dev_empty_ledger_any_dev_dir", ROOT / "dev-anything/worlds.jsonl", ns="s3p3x-rvdev")
side = reset(); (ROOT / "final-final").mkdir(); (ROOT / "final-final/worlds.jsonl").write_text(FAKE); (ROOT / "FINAL_READ_ONCE.json").write_text("{}")
run("11_final_name_under_dev_rule", ROOT / "final-final/worlds.jsonl", ns="s3p3x-rvdev")
shutil.rmtree(RC / "artifacts")
json.dump(res, open(OUT / "bypass_r2c.json", "w"), ensure_ascii=False, indent=1)
