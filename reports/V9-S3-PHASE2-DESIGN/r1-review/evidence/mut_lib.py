"""源码变异框架：先 py_compile，防语法错误造成的假击杀；记录失败原因，标记由 NameError 等偶然错误造成的击杀。"""
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path
R = Path("/Users/mac/AinerWorkFlow/AinerZero"); PY = str(R / ".venv/bin/python")
ACCIDENT = re.compile(r"\b(SyntaxError|IndentationError|NameError|ImportError|ModuleNotFoundError)\b")
def run_group(W, group, mutants, default_tests, out_name):
    base = W / "base"; res = []; mroot = W / f"mut_{group}"; mroot.mkdir(exist_ok=True)
    for spec in mutants:
        name, rel, reps = spec[0], spec[1], spec[2]; tests = spec[3] if len(spec) > 3 else default_tests
        d = mroot / name
        if d.exists(): shutil.rmtree(d)
        shutil.copytree(base, d)
        p = d / rel; s = p.read_text(encoding="utf-8")
        for old, new in reps:
            n = s.count(old)
            assert n == 1, (name, n, old[:60])
            s = s.replace(old, new)
        if group == "runner":
            anchor = """        run_id = f"{a.stage}-{a.use_id or 'final'}"\n"""
            assert s.count(anchor) == 1, name
            s = s.replace(anchor, """        raise SystemExit("REVIEW_STOP_AFTER_CONSUME")\n""" + anchor)
        p.write_text(s, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(d / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        c = subprocess.run([PY, "-c", f"import ast,sys;ast.parse(open({str(p)!r},encoding='utf-8').read())"], capture_output=True, text=True, env=env)
        if c.returncode:
            rec = {"mutant": name, "status": "INVALID_SYNTAX", "detail": c.stderr[-300:]}
            res.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True); shutil.rmtree(d); continue
        t0 = time.time()
        r = subprocess.run([PY, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider", "--tb=line"], cwd=d, env=env, capture_output=True, text=True, timeout=500)
        txt = r.stdout + r.stderr
        failed = sorted(l.split()[1].split("::")[-1] for l in txt.splitlines() if l.startswith("FAILED"))
        errors = sorted(l for l in txt.splitlines() if l.startswith("ERROR"))
        summary = ([l for l in txt.splitlines() if re.search(r"\d+ (passed|failed|error)", l)] or [""])[-1]
        status = "SURVIVED" if r.returncode == 0 else ("COLLECTION_ERROR" if r.returncode == 2 or (errors and not failed) else "KILLED")
        lines = [l for l in txt.splitlines() if re.match(r"^(/|E\s).*:\d+:", l) or "Error" in l][:40]
        accidental = bool(failed) and all(ACCIDENT.search(l) for l in lines) if lines else False
        rec = {"mutant": name, "file": rel.split("/")[-1], "status": status, "failed_n": len(failed), "failed_first": failed[:3], "errors_n": len(errors), "accidental_error_only": accidental, "summary": summary, "sec": round(time.time() - t0, 1)}
        (W / "out" / f"{group}_{name}.txt").write_text(f"### {name}\n{json.dumps(reps, ensure_ascii=False, indent=0)}\n\n{txt}", encoding="utf-8")
        res.append(rec); print(json.dumps({k: rec[k] for k in ("mutant", "status", "failed_n", "failed_first", "accidental_error_only")}, ensure_ascii=False), flush=True)
        shutil.rmtree(d)
    (W / "out" / out_name).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("GROUP_DONE", group, len(res), flush=True)
