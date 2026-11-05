"""CPU-only preparation of the exact proposed run; never creates freeze approval."""
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import xml.etree.ElementTree as ET

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("p28", here / "measure_unit_cost.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
source = m.source_files()
preflight = json.loads((here / "preflight-003/run.json").read_text())
assert source == preflight["source_files"] and preflight["source_identity_unchanged"]
assert not m.ONCE.exists()
sequences, sample = m.load_inputs()
sample_text = json.dumps(sample, ensure_ascii=False, indent=2) + "\n"
if (here / "sample_manifest.json").exists():
    assert (here / "sample_manifest.json").read_text() == sample_text
else:
    (here / "sample_manifest.json").write_text(sample_text)
python_argv = [str(m.ROOT / ".venv/bin/python"), str(here / "measure_unit_cost.py"),
               "--mode", "real", "--output", str(here / "real-001"), "--freeze", str(here / "freeze.json")]
command = ["/usr/bin/timeout", "-s", "KILL", "600", *python_argv]
cases = list(ET.parse(here / "cpu-tests-r5.xml").iter("testcase"))
failed = sum(case.find("failure") is not None or case.find("error") is not None for case in cases)
assert failed == 0
plan = {"task": m.TASK, "agent": "codex-0fqn", "stage": "freeze_requested_not_authorized_yet",
        "source_files": source, "script_sha256": m.sha(here / "measure_unit_cost.py"),
        "tests_sha256": m.sha(here / "test_measure_unit_cost.py"), "argv": python_argv,
        "bounded_command": command, "wall_hard_max_seconds": 600,
        "wall_estimate": "unknown before measuring; use the full 600-second planning envelope, no CPU extrapolation",
        "cpu_tests": {"passed": len(cases), "failed": failed, "log": str(here / "cpu-tests-r5.log")},
        "sample": {"N": m.N, "manifest_sha256": sample["manifest_sha256"], "file_sha256": m.sha(here / "sample_manifest.json"),
                   "manifest_path": str(here / "sample_manifest.json"), "frames": sample["total_frames"],
                   "transitions": sample["total_transitions"], "family": "e3_identity only"},
        "planned_calls_per_arm": {"forward": {"warmup": 3, "measured": 48}, "encode": {"warmup": 3, "measured": 60},
                                  "probe_graph": {"warmup": 3, "measured": 36}},
        "native_crosscheck": {"product_step_sequence_calls_per_arm": 12, "additional_transitions_per_arm": 48,
                              "unit": "whole native sequence wall divided by transitions; auxiliary check, not a fourth primitive"},
        "arm1": "answer #425: all primitives N/A, stdlib identity only, no D load/C0 inference",
        "resources": preflight["resources"],
        "resource_note": "preflight imports no MLX: allocator is unmeasured, not a measured zero; first real allocator probe occurs under shared lock before models",
        "real_model_runs_so_far": 0,
        "limitations": ["same first 12 scene_id values all e3 family", "untrained seed0 memories, not trained checkpoints",
                        "three primitive sums cannot prove full 20min/4h end-to-end budget", "D batch16 C0 and 175 window batches remain unmeasured"],
        "failure_retention": "initial CPU dryrun refused /dev/null used by platform.platform; retained cpu-tests.log and cpu-dryrun/; fixed device sink exception, no resource/partition lines loosened"}
(here / "freeze-request-r3.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
text = ["# P28 阶段1：申请一级冻结，尚未执行真实 MLX", "", "依据：用户一次≤600秒授权；任务答复#425冻结arm1 N/A口径。",
        f"CPU最终脚本{len(cases)}项通过，0失败；完整无MLX导入干跑在 cpu-tests-pytest-r5/ 下。", "",
        f"脚本SHA256：{plan['script_sha256']}", f"测试SHA256：{plan['tests_sha256']}",
        f"样本清单SHA256：{plan['sample']['file_sha256']}", f"清单内容摘要：{sample['manifest_sha256']}", "",
        "N=12，按scene_id/episode_id排序的前12个development episode，全是e3_identity；60帧/48转移。",
        "arm2/3/4每项3次预热；正式forward48次、encode60次、probe_graph36次；warmup首条单独保留。",
        "按#431，计时区内完成loss/parts求值、pose/predictions numpy强制及memory中MLX叶子eval；memory类型原样保留。",
        "每臂另做12次产品原生step_sequence、共48转移的整段/转移数交叉核对，与单步median并列，不列为第四种30样本primitive。",
        "阶段1没有导入MLX，未创建优化器，未打开P1 RunStore/台账；未生成世界或训练数据。",
        "按#429改用与P1相同的.venv/bin/python，env.txt记录mlx/mlx-metal/numpy元数据版本。",
        "按#429补真实worker_lock的CPU正例与新目录/symlink/范围外写/SQLite/其他mkdir反例；旧未批准候选保留stage1-r1/。",
        "预计墙钟未经实测，保守规划为完整600秒硬上限，不拿CPU假计时外推。", "", "精确命令：", "", "```text",
        "python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.P28 --agent codex-0fqn -- " + shlex.join(command), "```", "",
        "资源实测：", "", "```json", json.dumps(preflight["resources"], ensure_ascii=False, indent=2), "```", "",
        "MLX尚未导入，allocator未测而非实测0；真实进程持既有共享锁后、建模前检查实际allocator，逐调用前后核资源，峰值逐次落盘。",
        "模型不改变默认设备以保持产品路径；记录实际default_device和backend.name，不将backend字符串当设备实测。",
        "已有失败保留：第一次CPU干跑因平台信息读取/dev/null被I/O守卫拒绝；r2/r3各22通过，未消费真实运行额度。",
        "最终换算仅为三项核心耗时的median/p90算术区间；611序列调用已含1492个单步，不双乘。训练、checkpoint window batch、D前向及全端到端仍未知。",
        "等待一级明确冻结通过及此处源码/argv绑定；freeze.json仅在收到答复后记录，不写APPROVED行。", ""]
(here / "STAGE1-r3.md").write_text("\n".join(text))
lines = [digest + "  " + name for name, digest in source.items()]
lines += [m.sha(here / name) + "  " + str((here / name).relative_to(m.ROOT)) for name in
          ("sample_manifest.json", "freeze-request-r3.json", "cpu-tests-r5.log", "cpu-tests-r5.xml", "prepare_freeze.py")]
(here / "SHA256SUMS-stage1-r3.txt").write_text("\n".join(lines) + "\n")
print("script=" + plan["script_sha256"])
print("tests=" + plan["tests_sha256"])
print("samples=" + plan["sample"]["file_sha256"])
print("command=" + shlex.join(command))
print("resources=" + json.dumps(preflight["resources"], ensure_ascii=False))
