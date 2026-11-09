"""并行源码变异：先解析语法防假击杀，记录失败原因。分区已在基线副本里换成替身。"""
import json, os, re, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
R = Path("/Users/mac/AinerWorkFlow/AinerZero"); PY = str(R / ".venv/bin/python")
ACCIDENT = re.compile(r"\b(SyntaxError|IndentationError|NameError|ImportError|ModuleNotFoundError)\b")
def one(W, group, spec):
    name, rel, reps = spec[0], spec[1], spec[2]; tests = spec[3]
    d = W / f"mut_{group}" / name
    if d.exists(): shutil.rmtree(d)
    shutil.copytree(W / "base", d)
    p = d / rel; s = p.read_text(encoding="utf-8")
    for old, new in reps:
        n = s.count(old)
        if n != 1: return {"mutant": name, "status": "BAD_PATTERN", "detail": (n, old[:70])}
        s = s.replace(old, new)
    p.write_text(s, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(d / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    c = subprocess.run([PY, "-c", f"import ast;ast.parse(open({str(p)!r},encoding='utf-8').read())"], capture_output=True, text=True, env=env)
    if c.returncode: return {"mutant": name, "status": "INVALID_SYNTAX", "detail": c.stderr[-300:]}
    t0 = time.time()
    r = subprocess.run([PY, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider", "--tb=line"], cwd=d, env=env, capture_output=True, text=True, timeout=1200)
    txt = r.stdout + r.stderr
    failed = sorted(l.split()[1].split("::")[-1] for l in txt.splitlines() if l.startswith("FAILED"))
    errs = sorted(l.split()[1].split("::")[-1] for l in txt.splitlines() if l.startswith("ERROR"))
    summ = ([l for l in txt.splitlines() if re.search(r"\d+ (passed|failed|error)", l)] or [""])[-1]
    status = "SURVIVED" if r.returncode == 0 else ("KILLED" if failed else "COLLECTION_ERROR")
    lines = [l for l in txt.splitlines() if re.match(r"^(/|E\s).*:\d+:", l) or "Error" in l][:40]
    acc = bool(failed) and all(ACCIDENT.search(l) for l in lines) if lines else False
    (W / "out" / f"{group}_{name}.txt").write_text(f"### {name}\n{json.dumps(reps, ensure_ascii=False)}\n\n{txt}", encoding="utf-8")
    shutil.rmtree(d)
    return {"mutant": name, "file": rel.split("/")[-1], "status": status, "failed_n": len(failed), "errors_n": len(errs), "failed_first": failed[:4], "accidental_error_only": acc, "summary": summ, "sec": round(time.time() - t0, 1)}
def run(W, group, specs, out_name, workers):
    (W / f"mut_{group}").mkdir(exist_ok=True); res = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for rec in ex.map(lambda s: one(W, group, s), specs):
            res.append(rec); print(json.dumps({k: rec.get(k) for k in ("mutant", "status", "failed_n", "failed_first", "accidental_error_only")}, ensure_ascii=False), flush=True)
    (W / "out" / out_name).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8"); print("GROUP_DONE", group, len(res), flush=True)
