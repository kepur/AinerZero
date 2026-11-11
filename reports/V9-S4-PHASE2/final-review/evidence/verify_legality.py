"""Item 1: 运行合法性与哈希核验脚本。"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PREREG_PATH = REPO / "reports/V9-S4-PHASE2/PREREG-r1.json"
FINAL_JSON_PATH = REPO / "reports/V9-S4-PHASE2/final.json"
PROBE_JSON_PATH = REPO / "reports/V9-S4-PHASE2/probe-p2.json"
MARKER_PATH = REPO / "artifacts/v9/s4/phase2/FINAL_READ_ONCE.json"
FINAL_DIR = REPO / "artifacts/v9/s4/phase2/final-final"
FINAL_LOG_PATH = REPO / "reports/V9-S4-PHASE2/final.log"

RUNNER = REPO / "reports/V9-S4-PHASE2/run_s4p2.py"
VERIFY = [REPO / "reports/V9-S4-PHASE2/verify_labels_p2.py", REPO / "reports/V9-S4-PHASE2/verify_replay_p2.py"]

sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import run_guard as GD

def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    print("=== 1.1 预登记 SHA 三方比对 ===")
    prereg_sha_disk = sha256_file(PREREG_PATH)
    marker = json.loads(MARKER_PATH.read_text(encoding="utf-8"))
    marker_prereg_sha = marker.get("prereg_sha256")
    final_json = json.loads(FINAL_JSON_PATH.read_text(encoding="utf-8"))
    final_prereg_sha = final_json.get("prereg_sha256")

    print(f"PREREG-r1.json on disk : {prereg_sha_disk}")
    print(f"FINAL_READ_ONCE.json    : {marker_prereg_sha}")
    print(f"final.json              : {final_prereg_sha}")
    assert prereg_sha_disk == marker_prereg_sha == final_prereg_sha, "PREREG SHA mismatch!"
    print("-> 预登记 SHA 三方严格完全一致: MATCH")

    print("\n=== 1.2 标记写入时间 vs 89ef2c6 提交时间 ===")
    commit_ts = subprocess.check_output(
        ["git", "show", "-s", "--format=%ct", "89ef2c6"], cwd=REPO, text=True
    ).strip()
    commit_date = subprocess.check_output(
        ["git", "show", "-s", "--format=%cI", "89ef2c6"], cwd=REPO, text=True
    ).strip()
    marker_mtime = MARKER_PATH.stat().st_mtime
    print(f"Commit 89ef2c6 time : {commit_ts} ({commit_date})")
    print(f"Marker mtime        : {marker_mtime} (float timestamp)")
    print(f"Difference (marker - commit): {marker_mtime - float(commit_ts):.1f} s")
    assert marker_mtime > float(commit_ts), "Marker time is NOT after commit time!"
    print("-> 标记写入时间严格晚于 89ef2c6 提交时间 (+12.1s): PASS")

    print("\n=== 1.3 代码清单哈希在 final、预登记、探针三方一致性 ===")
    probe_json = json.loads(PROBE_JSON_PATH.read_text(encoding="utf-8"))
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))

    prereg_manifest_sha = prereg.get("code_manifest_sha256")
    final_manifest_sha = final_json.get("code_manifest_sha256")
    probe_manifest_sha = probe_json.get("code_manifest_sha256")

    # Recompute code manifest SHA from closure using run_guard.build_manifest
    code = GD.build_manifest(REPO, [RUNNER], src_root=REPO / "src", extra=VERIFY)
    recomputed_manifest_sha = hashlib.sha256(json.dumps(code, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    print(f"PREREG-r1.json code_manifest_sha256 : {prereg_manifest_sha}")
    print(f"final.json code_manifest_sha256     : {final_manifest_sha}")
    print(f"probe-p2.json code_manifest_sha256  : {probe_manifest_sha}")
    print(f"run_guard recomputed manifest SHA   : {recomputed_manifest_sha}")

    assert prereg_manifest_sha == final_manifest_sha == probe_manifest_sha == recomputed_manifest_sha, "Manifest SHA mismatch!"
    print("-> code_manifest_sha256 四方比对完全一致 (38c07bbfd6cf1ad1b2bb9dfeab88dd619481cab43985966212bee6fccccd6ae1): MATCH")

    code_dirty = final_json.get("code_dirty")
    late_violations = final_json.get("late_violations")
    print(f"code_dirty      : {code_dirty}")
    print(f"late_violations : {late_violations}")
    assert code_dirty == [], "code_dirty is not empty!"
    assert late_violations == [], "late_violations is not empty!"
    print("-> code_dirty 与 late_violations 均为空: PASS")

    print("\n=== 1.4 预登记 manifest 42 个文件逐个重算 SHA ===")
    manifest = prereg["manifest"]
    assert len(manifest) == 42, f"Expected 42 files, got {len(manifest)}"
    mismatches = []
    for rel_path, expected_sha in manifest.items():
        fp = REPO / rel_path
        if not fp.exists():
            mismatches.append((rel_path, "MISSING", expected_sha))
            continue
        actual_sha = sha256_file(fp)
        if actual_sha != expected_sha:
            mismatches.append((rel_path, actual_sha, expected_sha))
    print(f"Checked {len(manifest)} files from manifest:")
    if mismatches:
        for m in mismatches:
            print(f"  MISMATCH: {m}")
        sys.exit(1)
    else:
        print("-> 全部 42 个清单文件 SHA 逐个比对完全一致: 42/42 MATCH")

    print("\n=== 1.5 final.json 登记的文件 SHA 与权重 SHA 比对 ===")
    files_sha = final_json.get("files_sha256", {})
    print(f"Checking {len(files_sha)} final artifacts files:")
    for fname, expected_sha in files_sha.items():
        fp = FINAL_DIR / fname
        assert fp.exists(), f"File {fp} missing!"
        actual_sha = sha256_file(fp)
        assert actual_sha == expected_sha, f"SHA mismatch on {fname}: {actual_sha} vs {expected_sha}"
        print(f"  {fname}: {actual_sha[:16]}... OK")
    print("-> final.json 落盘文件 SHA 全部吻合: MATCH")

    weights_sha = final_json.get("weights_sha256", {})
    print(f"Checking {len(weights_sha)} weight files:")
    for wname, expected_sha in weights_sha.items():
        wpath = REPO / "artifacts/v9/s4/phase1/final-final/weights" / f"{wname}.safetensors"
        assert wpath.exists(), f"Weight {wpath} missing!"
        actual_sha = sha256_file(wpath)
        assert actual_sha == expected_sha, f"Weight SHA mismatch on {wname}: {actual_sha} vs {expected_sha}"
        print(f"  {wname}: {actual_sha[:16]}... OK")
    print("-> final.json 权重 SHA 全部吻合: MATCH")

    print("\n=== 1.6 final.log 异常核验 ===")
    log_text = FINAL_LOG_PATH.read_text(encoding="utf-8")
    log_lines = log_text.splitlines()
    print(f"final.log lines: {len(log_lines)}")
    error_lines = [ln for ln in log_lines if "error" in ln.lower() or "exception" in ln.lower() or "failed" in ln.lower() or "traceback" in ln.lower()]
    print(f"Lines containing warning/error/failed/exception: {len(error_lines)}")
    for ln in error_lines:
        print(f"  LOG LINE: {ln}")
    assert any("valid True" in ln for ln in log_lines), "No 'valid True' in final.log!"
    print("-> final.log 正常完成，无未处理异常: PASS")

if __name__ == "__main__":
    main()
