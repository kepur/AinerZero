"""仓库 __pycache__ 里的旧字节码与当前源码逐项比较（只读）。P2 r1 复核。"""
import dis, importlib.util as u, marshal, os, struct, sys, time, types
from pathlib import Path
R = Path("/Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s3")
def header(p):
    b = p.read_bytes(); flags = struct.unpack("<I", b[4:8])[0]; mt, sz = struct.unpack("<II", b[8:16])
    return flags, mt, sz, marshal.loads(b[16:])
def walk(c, prefix=""):
    yield prefix + c.co_name, c
    for k in c.co_consts:
        if isinstance(k, types.CodeType):
            yield from walk(k, prefix + c.co_name + ".")
def sig(c):
    consts = tuple(("<code>" if isinstance(k, types.CodeType) else (None if isinstance(k, str) and len(k) > 40 else k)) for k in c.co_consts)
    return (c.co_code, c.co_names, c.co_varnames, consts)
for name in ("replay", "arms_p2_mlx", "analysis_p2", "run_guard"):
    src = R / f"{name}.py"; pyc = R / "__pycache__" / f"{name}.cpython-312.pyc"
    fl, mt, sz, code = header(pyc)
    st = src.stat()
    print(f"== {name}: pyc source mtime {time.strftime('%H:%M:%S', time.gmtime(mt))} size {sz} | current mtime {time.strftime('%H:%M:%S', time.gmtime(st.st_mtime))} size {st.st_size} | pyc file mtime {time.strftime('%H:%M:%S', time.gmtime(pyc.stat().st_mtime))} same_source={mt == int(st.st_mtime) and sz == st.st_size}")
    cur = compile(src.read_text(encoding="utf-8"), str(src), "exec", optimize=-1)
    old = {n: c for n, c in walk(code)}; new = {n: c for n, c in walk(cur)}
    if set(old) != set(new): print("  functions differ:", sorted(set(old) ^ set(new)))
    for n in sorted(set(old) & set(new)):
        if sig(old[n]) != sig(new[n]):
            print("  DIFF in", n)
            a = [(i.opname, i.argrepr) for i in dis.get_instructions(old[n])]; b = [(i.opname, i.argrepr) for i in dis.get_instructions(new[n])]
            import difflib
            for l in list(difflib.unified_diff([str(x) for x in a], [str(x) for x in b], lineterm="", n=2))[2:40]: print("    ", l)
    print("  compared functions:", len(set(old) & set(new)), "| identical bytecode:", all(sig(old[n]) == sig(new[n]) for n in set(old) & set(new)) and set(old) == set(new))
