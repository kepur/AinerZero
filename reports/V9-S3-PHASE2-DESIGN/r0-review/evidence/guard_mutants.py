"""run_guard.py 的 22 个源码变异，只跑 test_s3_run_guard.py。"""
import json, os, shutil, subprocess, sys
from pathlib import Path
W = Path(sys.argv[1]); R = Path("/Users/mac/AinerWorkFlow/AinerZero"); PY = str(R / ".venv/bin/python")
F = "src/ainerzero/v9/experiments/s3/run_guard.py"
M = [
 ("g01_require_held_noop", '    if not isinstance(lock, RunLock) or not lock.held:\n        raise GuardError("the shared lock must be held before any ledger or marker is written")', '    return'),
 ("g02_held_not_checked", 'if not isinstance(lock, RunLock) or not lock.held:', 'if not isinstance(lock, RunLock):'),
 ("g03_shared_instead_of_exclusive", 'fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)', 'fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)'),
 ("g05_closure_top_level_only", 'for node in ast.walk(tree):', 'for node in tree.body:'),
 ("g06_relative_imports_skipped", '            if node.level:\n                if src_root is None:', '            if node.level:\n                continue\n                if src_root is None:'),
 ("g07_no_ancestor_init", 'for i in range(1, len(parts) + 1):', 'for i in range(len(parts), len(parts) + 1):'),
 ("g08_empty_manifest_ok", '        return ["manifest is empty"]', '        return []'),
 ("g09_changes_ignored", 'elif sha256_file(p) != want:', 'elif False:'),
 ("g10_loaded_check_noop", 'if Path(file).resolve() not in known:', 'if False:'),
 ("g11_limit_off_by_one", 'if len(uses) >= max_uses:', 'if len(uses) > max_uses:'),
 ("g12_duplicate_id_ok", 'if use_id in [u.get("id") for u in uses]:', 'if False:'),
 ("g13_marker_not_checked", 'if marker.exists():', 'if False:'),
 ("g14_marker_open_w", 'with marker.open("x", encoding="utf-8") as fh:', 'with marker.open("w", encoding="utf-8") as fh:'),
 ("g15_ledger_not_atomic", '    os.replace(tmp, path)', '    path.write_text(text, encoding="utf-8"); tmp.unlink()'),
 ("g16_extra_files_dropped", 'paths = set(import_closure(src_root, entries)) | {Path(p).resolve() for p in extra}', 'paths = set(import_closure(src_root, entries))'),
 ("g17_smoke_reads_dev", 'wanted = {"smoke": probe, "dev": dev, "final": final}', 'wanted = {"smoke": dev, "dev": dev, "final": final}'),
 ("g18_any_approval_ok", 'if (approval or "").strip() != expected:', 'if not (approval or "").strip():'),
 ("g19_report_append", 'path.open("x", encoding="utf-8").close()', 'path.open("a", encoding="utf-8").close()'),
 ("g20_deadline_strict", 'if self.left() <= 0:', 'if self.left() < 0:'),
 ("g21_from_import_names_dropped", '            names.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")\n', ''),
 ("g22_blank_purpose_ok", 'if not use_id or not (purpose or "").strip():', 'if not use_id or not purpose:'),
 ("g23_loaded_filter_inverted", '        if name != package and not name.startswith(package + "."):\n            continue\n        file = getattr', '        if name == package or name.startswith(package + "."):\n            continue\n        file = getattr'),
]
base = W / "base"; res = []
for name, old, new in M:
    d = W / "gm" / name
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True)
    shutil.copytree(base / "src", d / "src"); (d / "tests/v9/experiments").mkdir(parents=True); shutil.copy(base / "tests/v9/experiments/test_s3_run_guard.py", d / "tests/v9/experiments/")
    p = d / F; s = p.read_text(encoding="utf-8"); assert s.count(old) == 1, (name, s.count(old)); p.write_text(s.replace(old, new), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(d / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([PY, "-m", "pytest", "tests/v9/experiments/test_s3_run_guard.py", "-q", "-p", "no:cacheprovider", "--tb=line", "--timeout=60"] if False else [PY, "-m", "pytest", "tests/v9/experiments/test_s3_run_guard.py", "-q", "-p", "no:cacheprovider", "--tb=line"], cwd=d, env=env, capture_output=True, text=True, timeout=120)
    fails = sorted(l.split()[1].split("::")[-1] for l in r.stdout.splitlines() if l.startswith("FAILED"))
    last = [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
    res.append({"mutant": name, "exit": r.returncode, "failed": fails, "tail": last}); print(("KILLED  " if r.returncode else "SURVIVE ") + name, fails[:3], last, flush=True)
    (W / "out" / f"{name}.txt").write_text(f"### {name}\n--- OLD\n{old}\n--- NEW\n{new}\n\n{r.stdout}\n{r.stderr}\n", encoding="utf-8")
    shutil.rmtree(d)
(W / "out/guard_mutations.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
