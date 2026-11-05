"""P10 adversarial suite, part 1: the five resource protection lines.

Every case runs the *real* code under test (sandbox copy, byte-identical to the
reviewed tree).  Nothing here touches the production lock or the central
RunStore: the sandbox copy makes ``spec.REPO_ROOT`` point at /tmp.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SB = Path("/private/tmp/vp9rev/sandbox")
PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv-ainerzero/bin/python"
OUT = Path("/private/tmp/vp9rev/results")
OUT.mkdir(parents=True, exist_ok=True)
ENV = {**os.environ, "PYTHONPATH": str(SB / "src"), "PYTHONDONTWRITEBYTECODE": "1"}

sys.path.insert(0, str(SB / "src"))

from ainerzero.v9.experiments.s1 import resource_gate, spec  # noqa: E402

GIB = resource_gate.GIB
rows: list[dict] = []


def cli(args: list[str], *, limits: dict | None = None, tag: str = "case") -> dict:
    """Invoke the real CLI in a subprocess; returns exit code + report."""
    extra = []
    if limits is not None:
        path = OUT / f"limits-{tag}.json"
        path.write_text(json.dumps(limits), encoding="utf-8")
        extra = ["--limits-file", str(path)]
    proc = subprocess.run(
        [PY, "-m", "ainerzero.cli", "s1-phase1", *args, *extra],
        cwd=str(SB), env=ENV, capture_output=True, text=True, timeout=300,
    )
    report = None
    try:
        report = json.loads(proc.stdout)
    except Exception:
        report = {"raw_stdout": proc.stdout[-800:], "raw_stderr": proc.stderr[-800:]}
    return {"exit": proc.returncode, "report": report, "stderr": proc.stderr[-400:]}


def add(cid, name, ok, exit_code, detail, evidence=None):
    rows.append({"id": cid, "name": name, "ok": bool(ok), "exit": exit_code,
                 "detail": detail, "evidence": evidence or {}})
    print(f"{'PASS' if ok else 'FAIL'} {cid} exit={exit_code} {detail}", flush=True)



def _snap(**kw):
    base = dict(process_rss_bytes=0.5 * GIB, mlx_active_bytes=0.0, mlx_peak_bytes=0.0,
                mlx_available=True, system_available_bytes=64 * GIB,
                swap_used_bytes=0.2 * GIB, swap_baseline_bytes=0.2 * GIB,
                disk_free_bytes=500 * GIB)
    base.update(kw)
    return resource_gate.ResourceSnapshot(**base)


probes = {
    "rss_probe": lambda: 0.5 * GIB,
    "mlx_probe": lambda: {"available": True, "active_bytes": 0.0, "peak_bytes": 0.0},
    "memory_probe": lambda: type("M", (), {"available": 64 * GIB})(),
    "swap_probe": lambda: type("S", (), {"used": 0.2 * GIB})(),
    "disk_probe": lambda: 500 * GIB,
}

# --- C1 process memory line (real CLI refusal) ---------------------------
r = cli(["--mode", "data", "--output-root", str(OUT / "c1")],
        limits={**spec.RESOURCE_LIMITS, "process_memory_gib": 0.001}, tag="c1")
reasons = r["report"].get("reasons") or []
add("C1", "进程内存线 8 GiB：RSS 超线真实拒绝",
    r["exit"] == 2 and r["report"].get("status") == "refused"
    and any("process_memory_limit" in x for x in reasons)
    and not (OUT / "c1" / "dataset").exists(),
    r["exit"], f"reasons={reasons}", {"report": r["report"]})

# --- C2 system reserve line ---------------------------------------------
r = cli(["--mode", "data", "--output-root", str(OUT / "c2")],
        limits={**spec.RESOURCE_LIMITS, "system_reserve_gib": 10000.0}, tag="c2")
reasons = r["report"].get("reasons") or []
add("C2", "系统余量线 16 GiB：余量不足真实拒绝",
    r["exit"] == 2 and any("system_reserve_limit" in x for x in reasons),
    r["exit"], f"reasons={reasons}")

# --- C3 disk free line ---------------------------------------------------
# The disk line is a floor: lowering it tightens (and makes it easier to pass),
# raising it is refused as loosening.  So on a healthy host it cannot be driven
# into a failing state through the CLI at all -- only through real low disk.
r = cli(["--mode", "data", "--output-root", str(OUT / "c3")],
        limits={**spec.RESOURCE_LIMITS, "disk_min_free_gib": 1e7}, tag="c3")
reasons = r["report"].get("reasons") or []
loosening_refused = r["exit"] == 2 and any("disk_min_free_gib" in x for x in reasons)
r2 = cli(["--mode", "data", "--output-root", str(OUT / "c3b")],
         limits={**spec.RESOURCE_LIMITS, "disk_min_free_gib": 1.0}, tag="c3b")
tighten_admitted = not (r2["report"].get("reasons") or [])
disk_reasons = []
try:
    resource_gate.assert_start(spec.RESOURCE_LIMITS, root=OUT,
                               probes={**probes, "disk_probe": lambda: 10 * GIB})
except resource_gate.ResourceGateRefused as exc:
    disk_reasons = exc.reasons
add("C3", "磁盘余量线：放宽被拒 + 收紧放行 + 注入低余量时真实拒绝（CLI 侧不可达）",
    loosening_refused and tighten_admitted and any("disk_free_limit" in x for x in disk_reasons),
    2, f"loosening={reasons} injected={disk_reasons}")

# --- C4 duty cycle line (config loosening refused) ----------------------
r = cli(["--mode", "data", "--output-root", str(OUT / "c4")],
        limits={**spec.RESOURCE_LIMITS, "training_duty_cycle": 0.5}, tag="c4")
reasons = r["report"].get("reasons") or []
add("C4", "占空比 0.25：放宽到 0.5 真实拒绝",
    r["exit"] == 2 and any("training_duty_cycle" in x and "loosening refused" in x for x in reasons),
    r["exit"], f"reasons={reasons}")

# --- C5 MLX line (real CLI main, MLX memory actually allocated) ---------
mlx_script = f"""
import json, sys
sys.path.insert(0, {str(SB / 'src')!r})
import mlx.core as mx
buf = mx.zeros((4096, 4096), dtype=mx.float32)   # 64 MiB
mx.eval(buf)
print("MLX_ACTIVE_GIB", mx.get_active_memory() / float(2**30))
from ainerzero.cli import main
limits = {{**__import__('ainerzero.v9.experiments.s1.spec', fromlist=['x']).RESOURCE_LIMITS}}
limits['mlx_memory_gib'] = 0.001
open({str(OUT / 'limits-c5.json')!r}, 'w').write(json.dumps(limits))
code = main(["s1-phase1", "--mode", "data", "--output-root", {str(OUT / 'c5')!r},
             "--limits-file", {str(OUT / 'limits-c5.json')!r}])
print("CLI_EXIT", code)
"""
proc = subprocess.run([PY, "-c", mlx_script], cwd=str(SB), env=ENV,
                      capture_output=True, text=True, timeout=300)
mlx_active = [ln for ln in proc.stdout.splitlines() if ln.startswith("MLX_ACTIVE_GIB")]
cli_exit = [ln for ln in proc.stdout.splitlines() if ln.startswith("CLI_EXIT")]
tail = proc.stdout[proc.stdout.find("{"):] if "{" in proc.stdout else ""
try:
    rep5 = json.loads(tail.split("\nCLI_EXIT")[0])
except Exception:
    rep5 = {}
reasons5 = rep5.get("reasons") or []
add("C5", "MLX 4 GiB 线：MLX 实占超线真实拒绝",
    bool(cli_exit) and cli_exit[0].endswith("2") and any("mlx_memory_limit" in x for x in reasons5),
    int(cli_exit[0].split()[-1]) if cli_exit else None,
    f"mlx_active={mlx_active} reasons={reasons5}")

# --- C6 swap growth line (runtime guard; admission growth is 0 by design) --
swap_probes = {**probes, "swap_probe": lambda: type("S", (), {"used": 2.0 * GIB})()}
guard = resource_gate.RuntimeGuard(spec.RESOURCE_LIMITS, root=OUT, initial_swap_bytes=0.2 * GIB,
                                   min_interval_seconds=0.0, probes=swap_probes)
swap_reasons = []
try:
    guard.sample(force=True)
except resource_gate.ResourceGateRefused as exc:
    swap_reasons = exc.reasons
# Admission-time growth is identically zero: collect() uses the current swap as its own baseline.
s0 = resource_gate.collect(root=OUT)
growth0 = s0.swap_used_bytes - s0.swap_baseline_bytes
add("C6", "交换区增长 1 GiB：运行期守卫真实拒绝（启动时增长恒为 0）",
    any("swap_growth_limit" in x for x in swap_reasons) and growth0 == 0.0,
    0, f"guard_reasons={swap_reasons} admission_growth={growth0}")

# --- C6b duty branch of evaluate() is unreachable through validate_limits --
grid = [0.0, 1e-9, 0.01, 0.1, 0.25, 0.2500001, 0.3, 0.5, 1.0, -0.1]
reachable = []
for duty in grid:
    limits = {**spec.RESOURCE_LIMITS, "training_duty_cycle": duty}
    if resource_gate.validate_limits(limits):
        continue                      # assert_start never reaches evaluate()
    reasons = resource_gate.evaluate(_snap(), limits)
    if any("duty_cycle_limit" in x for x in reasons):
        reachable.append(duty)
add("C6b", "evaluate() 的 duty_cycle_limit 分支在 validate_limits 之后不可达",
    reachable == [], 0, f"reachable_duty_values={reachable}")

(OUT / "p1.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n{sum(r['ok'] for r in rows)}/{len(rows)} passed")
