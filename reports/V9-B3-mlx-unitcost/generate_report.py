"""Read preserved evidence and emit the report; no MLX import or model calls."""
import datetime
import hashlib
import json
from pathlib import Path
import shlex
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
run = json.loads((HERE / "real-001/run.json").read_text())
execution = json.loads((HERE / "real-exec-result.json").read_text())
freeze = json.loads((HERE / "freeze.json").read_text())
plan = json.loads((HERE / "freeze-request-r3.json").read_text())
assert execution["returncode"] == 0 and execution["retry"] is False
assert run["status"] == "measurement_completed_not_capability" and run["real_model_runs"] == 1
assert run["source_identity_unchanged"] and (HERE / "REAL_ATTEMPT_ONCE.json").is_file()
changed = [name for name, digest in freeze["source_files"].items()
           if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
assert not changed, changed
samples = json.loads((HERE / "real-001/samples.json").read_text())
assert samples == json.loads((HERE / "sample_manifest.json").read_text())
resource_rows = run["resource_samples"]
resources = {"process_peak_rss_gib": run["process_peak_rss_bytes"] / 2**30,
             "mlx_peak_gib": run["mlx_peak_bytes"] / 2**30,
             "system_available_min_gib": min(row["system_available_gib"] for row in resource_rows),
             "same_boot_swap_growth_max_gib": max(row["swap_growth_gib"] for row in resource_rows),
             "boot_epoch": resource_rows[0]["boot_epoch"], "samples": len(resource_rows),
             "resource_refusals": [row for row in resource_rows if row["reasons"]]}
assert not resources["resource_refusals"]
assert resources["process_peak_rss_gib"] <= 8 and resources["mlx_peak_gib"] <= 4
assert resources["system_available_min_gib"] >= 16 and resources["same_boot_swap_growth_max_gib"] <= 1
arms = {}
actual_timed_regions = 0
for arm in ("arm2", "arm3", "arm4"):
    row = run["arms"][arm]
    assert row["status"] == "completed" and row["parameter_sha256_before"] == row["parameter_sha256_after"]
    for primitive, count in (("forward", 48), ("encode", 60), ("probe_graph", 36)):
        assert row[primitive]["samples"] == count and len(row[primitive]["warmup"]) == 3
    assert row["step_sequence_per_transition"]["samples"] == 12
    raw = [json.loads(line) for line in (HERE / f"real-001/{arm}-raw.jsonl").read_text().splitlines()]
    assert len(raw) == 165
    actual_timed_regions += len(raw)
    arms[arm] = {"parameter_count": row["parameter_count"],
                 "parameter_sha256_before": row["parameter_sha256_before"],
                 "parameter_sha256_after": row["parameter_sha256_after"],
                 "initialization_and_identity_seconds": row["initialization_and_identity_seconds"],
                 **{name: {k: v for k, v in row[name].items() if k not in ("warmup", "measured", "rows")}
                    for name in ("forward", "encode", "probe_graph", "step_sequence_per_transition")}}
cases = list(ET.parse(HERE / "cpu-tests-r5.xml").iter("testcase"))
assert not any(case.find("failure") is not None or case.find("error") is not None for case in cases)
stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).isoformat(timespec="seconds")
environment = json.loads((HERE / "real-001/env.txt").read_text())
environment["metadata_snapshot_stage"] = "before MLX import; mlx_imported=false belongs to that snapshot"
environment["actual_runtime_device"] = run["mlx_default_device"]
environment["product_backend_name"] = run["backend_name"]
(HERE / "env.txt").write_text(json.dumps(environment, ensure_ascii=False, indent=2) + "\n")
metrics = {"schema": "ainerzero.v9.p28.unit_cost.v1", "task": "ainerzero.V9.P28", "agent": "codex-0fqn",
           "status": "reported_pending_non_author_review", "measured_at": stamp,
           "authorization": "RESEARCH_LOG R20261022-S1-B3-mlx-unitcost-budget; task answer #433",
           "runs_authorized": 1, "real_attempts": 1, "real_model_runs": 1, "retries": 0,
           "hard_limit_seconds": 600, "outer_wall_seconds": execution["outer_wall_seconds"],
           "supervision": {"raw_log": str(HERE / "real-exec.log")},
           "execution": execution, "freeze_message_id": 433, "frozen_source_files": freeze["source_files"],
           "source_identity_unchanged": True, "environment": environment, "resources": resources,
           "sample_manifest": str(HERE / "sample_manifest.json"), "sample_manifest_file_sha256": plan["sample"]["file_sha256"],
           "sample_content_sha256": samples["manifest_sha256"], "N": 12, "partition": "development",
           "dataset_digest": samples["dataset_digest"], "families": ["e3_identity"],
           "cpu_tests": {"passed": len(cases), "failed": 0, "log": str(HERE / "cpu-tests-r5.log")},
           "arm1": run["arms"]["arm1"], "arm1_identity": run["arm1_identity"], "arms": arms,
           "actual_call_accounting": {"timed_regions": actual_timed_regions,
              "per_arm": {"primary_forward": 48, "forward_warmup": 3, "encode": 60, "encode_warmup": 3,
                          "probe_graph": 36, "probe_graph_warmup": 3, "native_step_sequence_crosschecks": 12,
                          "native_crosscheck_forward_transitions": 48, "total_forward_terms_including_warmup_and_crosscheck": 99}},
           "extrapolation": run["extrapolation"],
           "negative_evidence": ["initial CPU dryrun failed because /dev/null was refused; original evidence retained",
                "r1 freeze held for lock-mkdir issue (#429); r2 freeze held for materialization and native crosscheck (#431)",
                f"arm3 native sequence per-transition median is {(1-arms['arm3']['step_sequence_per_transition']['ratio_vs_step_median'])*100:.3f}% lower than step median; cause not determined",
                "backend.name says mlx-cpu but observed actual default device was GPU; no override was applied"],
           "unmeasured": run["extrapolation"]["unmeasured"],
           "not_done": ["training", "backward", "optimizer creation", "data generation", "final reads",
                        "checkpoint saving", "P1 RunStore/ledger writes", "APPROVED line", "P1 launch", "second real run"],
           "report_dir": str(HERE), "independent_review": "P29 pending"}
# Supervision values are parsed from the actual CLI line, not invented constants.
supervision_line = next(line for line in (HERE / "real-exec.log").read_text().splitlines() if "墙钟监督证据：" in line)
supervision = json.loads(supervision_line.split("墙钟监督证据：", 1)[1])
assert supervision["confirmed_empty"] is True and supervision["members_left"] == []
metrics["supervision"] = supervision | {"raw_log": str(HERE / "real-exec.log")}
(HERE / "指标.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
details = ["# P28 测量明细", "", "生成时间：" + stamp, "",
    "依据用户一次≤600秒授权与一级答复#425/#429/#431/#433。唯一真实命令已完成，没有重跑。", "",
    "## 精确命令", "", "```text", shlex.join(execution["command"]), "```", "",
    "## 设备、同步与样本边界", "",
    "实际设备 " + run["mlx_default_device"] + "；产品后端名字是 " + run["backend_name"] + "。没有更改默认设备；后端名字不作为设备证据。",
    "每个单步都调用产品 forward_terms(burn_in=0, batch=1, 两帧切片)，并在计时结束前 eval(loss,parts)、物化pose/predictions、遍历原memory对象并eval其中MLX叶子。类型保持产品原样。",
    "计时不含样本切片、资源采样与落盘；它们在计时区之外。另对每个样本完整调用一次产品MlxBackend.step_sequence，整段/转移数包含其原生切片/转换/循环开销，两种结果并列。",
    "首3次预热丢弃，首条单独记录；first_call是首次调用总开销，不是独立测得的纯编译耗时。三臂在同一进程按arm2→arm3→arm4运行，后臂可能复用已热内核/缓存，首调用不代表独立冷启动。",
    "N=12，固定development清单按scene_id/episode_id排序，全是e3_identity，60帧/48转移；不能代表其他family或训练后更复杂的memory。",
    "arm1按#425只做既有stdlib身份校验，三项N/A，未加载D到MLX或用C0批做推理；身份检查会按既有校验器核验其钉扎文件字节。D真实前向的2秒截止仍未测。", "",
    "## 单位耗时（毫秒；median / p90 / max，首调用另列）", "",
    "| 臂 | 参数数 | 操作 | 正式样本 | median ms | p90 ms | max ms | 首调用 ms |", "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |"]
for arm, row in arms.items():
    for op in ("forward", "encode", "probe_graph", "step_sequence_per_transition"):
        item = row[op]
        first = item.get("first_call_seconds")
        details.append(f"| {arm} | {row['parameter_count']} | {op} | {item['samples']} | {item['median_seconds']*1000:.6f} | {item['p90_seconds']*1000:.6f} | {item['max_seconds']*1000:.6f} | {first*1000:.6f} |" if first is not None else
                       f"| {arm} | {row['parameter_count']} | {op} | {item['samples']} | {item['median_seconds']*1000:.6f} | {item['p90_seconds']*1000:.6f} | {item['max_seconds']*1000:.6f} | 非单独冷启动 |")
details += ["", "## 原生交叉核对差异", "", "| 臂 | 原生median / 逐步median | 差值 ms |", "| --- | ---: | ---: |"]
for arm, row in arms.items():
    cross = row["step_sequence_per_transition"]
    details.append(f"| {arm} | {cross['ratio_vs_step_median']:.6f} | {cross['delta_vs_step_median_seconds']*1000:.6f} |")
details += ["", "arm3原生平均单步比逐步median低约26%；本次没有独立实验分离差距原因。完整原生调用节奏和逐步测量的封装/间隔不同，保留两种数据，不能把差距归因写成已验证事实。主换算仍按本卡逐步单位数据计算。", "",
    "## 第8步：调用量乘单位耗时", "",
    "P18 r4的已实测调用量按每臂每种子：1492单步forward、3500外部encode、800 probe_graph。611 step_sequence已包含1492步，平均1492/611步/调用，不再双乘611。",
    "T(q)=1492×forward(q)+3500×encode(q)+800×probe_graph(q)，q分别取各项median、p90。三个种子与三臂的9次评测只是seed0初始结构的算术情景，不是实测9次训练后评测。", "",
    "| 臂/种子 | median情景秒 | p90情景秒 | 占1200s范围 |", "| --- | ---: | ---: | --- |"]
for arm, row in run["extrapolation"]["per_arm_seed"].items():
    details.append(f"| {arm} / seed0投射 | {row['median_seconds']:.6f} | {row['p90_seconds']:.6f} | {100*row['median_seconds_fraction_of_1200']:.4f}%–{100*row['p90_seconds_fraction_of_1200']:.4f}% |")
phase = run["extrapolation"]["nine_eval_invocations_arithmetic"]
details += ["", f"9次核心评测情景合计：{phase['median_seconds']:.6f}–{phase['p90_seconds']:.6f}s，占14400s的{phase['median_seconds']/14400*100:.4f}%–{phase['p90_seconds']/14400*100:.4f}%。",
    "这个区间不是置信区间或联合p90。尚不含175个独立window-forward_loss批、D的2秒前向、checkpoint加载、完整I/O/序列记账、训练时间与其他family/训练后memory规模；不能据此确认P1完整20分钟/4小时预算或写批准行。", "",
    "## 资源、完整性与失败保留", "", "```json", json.dumps(resources, ensure_ascii=False, indent=2), "```", "",
    "参数SHA三臂前后完全相同，详见指标.json。全部23项冻结源码/数据绑定在运行后仍相同，样本清单逐字相同。495条原始计时region在real-001/*-raw.jsonl，逐次warmup/正式计时及交叉核对JSON全部保留。",
    "CPU证据：初版21过/1败（/dev/null的环境元数据读取被拒绝），其余r2/r3各22过；修订锁边界r4为28过；最终r5为29过。旧候选stage1-r1/、stage1-r2/与所有失败日志均保留。",
    "新目录、symlink锁父目录、范围外写与SQLite正反例；final路径/最终分区symlink守卫；优化器毒桩/禁调用；同步时钟与原生交叉流程，都在最终CPU测试中通过。",
    "真实运行只执行一次，硬链接ONCE标记已存在，600s KILL未触发；真实exec原始退出码0、进程组确认空。未训练/反向/优化器/生成世界/final/保存checkpoint/写P1账本/批准/启动P1。", "",
    "## 脚本直接生成的身份", "", "生成命令：`.venv/bin/python reports/V9-B3-mlx-unitcost/generate_report.py`；完整文件级SHA256见SHA256SUMS.txt。", "", "```text"]
details += [digest + "  " + name for name, digest in freeze["source_files"].items()]
details += ["```", ""]
(HERE / "DETAILS.md").write_text("\n".join(details))
short = ["# ainerzero.V9.P28 执行报告", "角色：executor；负责人：codex-0fqn；时间：" + stamp,
    "任务状态：reported，待P29非作者复核；实验状态：唯一MLX测量completed，不代表能力通过。",
    "任务依据：R20261022-S1-B3-mlx-unitcost-budget一次≤600秒；一级#425/#429/#431口径及#433最终冻结。",
    "输入身份：脚本/测试/23项源码及数据/精确argv见freeze.json与SHA256SUMS.txt；运行后全部未变。",
    "文件范围：仅reports/V9-B3-mlx-unitcost/；未修改产品源码。",
    "实际执行：冻结argv外套relay exec与系统timeout -s KILL 600，恰好1次，0重跑；原始命令/输出见DETAILS.md和real-exec.log。",
    f"墙钟：外层{execution['outer_wall_seconds']:.3f}s，登记进程组{supervision['elapsed_s']:.3f}s；退出0，confirmed_empty=true，无剩余成员。",
    "样本：development固定前12场景，全e3_identity，60帧/48转移；完整清单及SHA已交。",
    "每臂：forward3预热+48正式、encode3+60、probe_graph3+36；另12次原生step_sequence/48转移交叉核对。",
    "arm1：按一级#425三项N/A，只验冻结D身份；不测C0 batch16，D真实2秒前向仍未知。",
    "硬件：Apple M2 Max，macOS27.2，mlx/mlx-metal0.32.2，numpy2.5.3；实际Device(gpu,0)，backend名字mlx-cpu不作为设备证据。",
    f"资源：进程峰值{resources['process_peak_rss_gib']:.6f}GiB，MLX峰值{resources['mlx_peak_gib']:.6f}GiB，系统余量最低{resources['system_available_min_gib']:.3f}GiB，开机swap增长0。",
    "三臂参数SHA前后相同；无优化器/反向/训练/保存checkpoint/生成数据/final/P1账本或批准行。",
    "逐步forward median(ms)：" + "；".join(f"{arm}={arms[arm]['forward']['median_seconds']*1000:.6f}" for arm in arms) + "。",
    "原生序列平均单步/逐步median比值：" + "；".join(f"{arm}={arms[arm]['step_sequence_per_transition']['ratio_vs_step_median']:.4f}" for arm in arms) + "，原因未验证，不替换不利结果。",
    f"P18调用量算术：每臂/种子核心约{min(row['median_seconds'] for row in run['extrapolation']['per_arm_seed'].values()):.2f}–{max(row['p90_seconds'] for row in run['extrapolation']['per_arm_seed'].values()):.2f}s；9次情景合计{phase['median_seconds']:.3f}–{phase['p90_seconds']:.3f}s，非联合p90/置信区间。",
    "未测：175个window批、D真实前向、checkpoint/I/O、训练及其他family/训练后memory；不能据此确认完整20分钟/4小时预算或放行P1。",
    f"CPU最终{len(cases)}过/0败，完整假后端无MLX；初版/dev/null失败及两轮冻结暂缓均保留，真实预算未用于重试。",
    "产物：指标.json、DETAILS.md、env.txt、SHA256SUMS.txt、real-001逐臂/逐次JSON、所有原始CPU/MLX日志、freeze.json及ONCE。",
    "交回统筹：交P29静态非作者复核，不再实测、不自行accept、不启动P1。"]
assert len(short) <= 30
(HERE / "报告.md").write_text("\n".join(short) + "\n")
files = {str(ROOT / name): digest for name, digest in freeze["source_files"].items()}
for path in sorted(HERE.rglob("*")):
    if path.is_file() and path.name != "SHA256SUMS.txt" and "__pycache__" not in path.parts:
        files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
sha_text = "\n".join(digest + "  " + str(Path(name).relative_to(ROOT)) for name, digest in sorted(files.items())) + "\n"
(HERE / "SHA256SUMS.txt").write_text(sha_text)
print("real runs=1; retries=0; source drift=0; raw timed regions=" + str(actual_timed_regions))
print("group wall seconds=" + str(supervision["elapsed_s"]))
print("core nine-eval arithmetic seconds=" + json.dumps(phase))
print("script SHA256=" + freeze["source_files"]["reports/V9-B3-mlx-unitcost/measure_unit_cost.py"])
print("tests SHA256=" + freeze["source_files"]["reports/V9-B3-mlx-unitcost/test_measure_unit_cost.py"])
print("complete SHA script output saved to " + str(HERE / "SHA256SUMS.txt"))
