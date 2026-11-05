"""T6 DA3 标定 runner（relay V9.T37 重写）。忠实实现 reports/V9-T28/proposal.json（T28 预登记）。

与 r1 的根本区别：
  * 阶段计划、process_res、容差、阈值、世界划分**全部从 T28 预登记读取**，并在启动前核对 proposal /
    manifest / 统计协议 / 生成器的 SHA；不再有写死的口径。
  * 证据里的每个结论字段都由测量值产生。r1 里写死的 `rotation_offset_deg: 180`、`full_calibration_completed: True`、
    以及根本没执行却写 `"verified": True` 的两个逆向控制，全部删除。
  * 位姿约定：管线回执 extrinsics 是 world_to_camera，先取逆成 camera_to_world 再算 T28 锚点相对残差；
    不再拿绝对位姿比较，也不再用目标视图自拟合的深度指标。
  * 尺寸不匹配是硬错误，不做任何静默缩放；按预登记用 process_res=280（输出 210x280，与真值同形）。
  * 失败策略按 T28：任一对拍/逆向控制/来源校验失败 -> 非零退出，并保留已产生的输出。
  * **模型加载之前**先做可满足性预检：协议若无法在当前 teacher 上被满足，直接拒绝（退出码 6），
    不消耗任何前向。`--preflight-only` 零模型、零账本，供统筹在放行真跑前先跑。

退出码：0 通过；1 意外错误；2 预检失败（输入/哈希/输出目录）；5 阶段失败（对拍/逆向控制等）；6 协议不可满足。
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from PIL import Image

import importlib.util


def _load_math():
    """按文件路径加载数学模块：worker 以脚本方式、不带 PYTHONPATH 启动本文件，且要避开包 __init__ 的副作用。"""
    name = "da3_calibration_math"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("da3_calibration_math.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_registration():
    """按文件路径加载登记模块：worker 以脚本方式、不带 PYTHONPATH 启动本文件，且避开包 __init__ 的副作用。"""
    pkg_name = "ainerzero.v9.teachers.t28_registration"
    if pkg_name in sys.modules:
        return sys.modules[pkg_name]
    name = "t28_registration"
    if name in sys.modules:
        return sys.modules[name]
    reg_path = Path(__file__).with_name("t28_registration.py")
    spec = importlib.util.spec_from_file_location(pkg_name, reg_path)
    if spec is None or spec.loader is None:
        spec = importlib.util.spec_from_file_location(name, reg_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot find t28_registration.py relative to {__file__}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = mod
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load_math()

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
T6_ENV_DIR = REPO_ROOT / "envs/teachers/t6"
FIXTURES_DIR = REPO_ROOT / "reports/V9-T6/r2-calib-fixtures"


def get_default_proposal_path() -> Path:
    if os.environ.get("T6_PROPOSAL_PATH"):
        return Path(os.environ["T6_PROPOSAL_PATH"]).resolve()
    reg = _load_registration()
    repo = getattr(reg, "REPO_ROOT", None) or REPO_ROOT
    reg_file = repo / "reports/V9-T28/REGISTERED.json"
    if reg_file.is_file():
        try:
            reg_info = reg.load_t28_registration(repo_root=repo)
        except Exception as exc:
            raise PreflightError(f"Failed to read T28 registration: {exc}") from exc
        if reg_info.is_registered and reg_info.proposal_path:
            candidate = Path(reg_info.proposal_path)
            if not candidate.is_file():
                raise PreflightError(f"Registered proposal path not found: {candidate}")
            return candidate.resolve()
        raise PreflightError(f"REGISTERED.json exists at {reg_file} but has no valid registered proposal_path")
    return (repo / "reports/V9-T28/proposal.json").resolve()


# 默认提案路径：有登记时用登记里的 proposal_path，没有登记时保持 r1。
try:
    PROPOSAL_PATH = get_default_proposal_path()
except Exception:
    PROPOSAL_PATH = (REPO_ROOT / "reports/V9-T28/proposal.json").resolve()
GENERATOR_PATH = T6_ENV_DIR / "prepare_calibration_fixtures.py"

EXIT_OK, EXIT_ERROR, EXIT_PREFLIGHT, EXIT_STAGE_FAILED, EXIT_UNSATISFIABLE = 0, 1, 2, 5, 6

# 这版 DA3 在没有外参时完全忽略内参：model/da3.py 的 `if extrinsics is not None:` 才会走 cam_enc(extrinsics, intrinsics, …)，
# api.py 的 _align_to_input_extrinsics_intrinsics 在 extrinsics is None 时直接返回。T28 规定"不给外参"，
# 所以"已知 K"与"内参逆向控制"都无法通过喂 K 影响模型输出。tests 里有一条漂移探测，上游改了会失败。
REAL_DA3_CONDITIONS_ON_INTRINSICS_ONLY = False


class PreflightError(Exception):
    """输入/哈希/输出目录问题：未做任何模型工作。"""


class ProtocolUnsatisfiable(Exception):
    """预登记协议在当前 teacher 上无法被满足：未做任何模型工作。"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ───────────────────────────── 预登记读取 ─────────────────────────────
@dataclass(frozen=True)
class Plan:
    proposal: Mapping[str, Any]
    shas: Mapping[str, str]
    process_res: int
    anchor_view: int
    scored_view: int
    scale_view: int
    fit_worlds: tuple[str, ...]
    holdout_worlds: tuple[str, ...]
    variants: tuple[str, ...]
    stages: tuple[Mapping[str, Any], ...]
    calls_per_variant: int
    views_per_variant: int
    known_intrinsics: bool
    focal_scale: tuple[float, float]
    red_floor: float
    red_rel: float
    parity_fields: tuple[str, ...]
    parity_cpu: tuple[float, float]
    parity_half: tuple[float, float]
    claims_forbidden: tuple[str, ...]
    output_status: str
    extra: dict = field(default_factory=dict)


def load_plan(proposal_path: Path | None = None, fixtures_dir: Path = FIXTURES_DIR,
              generator_path: Path = GENERATOR_PATH, verify_hashes: bool = True) -> Plan:
    proposal_path = Path(proposal_path) if proposal_path is not None else get_default_proposal_path()
    fixtures_dir = Path(fixtures_dir)
    if not proposal_path.is_file():
        raise PreflightError(f"missing T28 proposal: {proposal_path}")
    p = json.loads(proposal_path.read_text(encoding="utf-8"))
    shas = {"proposal": sha256_file(proposal_path),
            "manifest": sha256_file(fixtures_dir / "manifest.json"),
            "protocol": sha256_file(fixtures_dir / "statistical_protocol.json"),
            "generator": sha256_file(generator_path) if Path(generator_path).is_file() else ""}
    if verify_hashes:
        reg = _load_registration()
        repo = getattr(reg, "REPO_ROOT", None) or REPO_ROOT
        try:
            reg_info = reg.load_t28_registration(repo_root=repo)
        except Exception as exc:
            raise PreflightError(f"Failed to read T28 registration: {exc}") from exc
        if reg_info.is_registered:
            # MUTANT 2: Registration SHA check deleted!
            pass
        sidecar = proposal_path.with_name("proposal.sha256")
        if sidecar.is_file() and sidecar.read_text().split()[0] != shas["proposal"]:
            raise PreflightError("T28 proposal.json differs from its registered proposal.sha256")
        for key, field_name in (("manifest", "input_manifest_sha256"), ("protocol", "lead_protocol_observed_sha256"),
                                ("generator", "generator_sha256")):
            if shas[key] != p[field_name]:
                raise PreflightError(f"{key} SHA {shas[key][:12]} != T28 {field_name} {p[field_name][:12]}")
    models = p["budget"]["models"]
    stages0 = models[0]["stages"]
    for m in models[1:]:
        if [s["stage"] for s in m["stages"]] != [s["stage"] for s in stages0]:
            raise PreflightError("T28 stage lists differ between variants; refusing to guess")
    adv_text = p["negative_controls"].get("intrinsics")          # r2 去掉了内参逆向控制
    m_adv = re.search(r"focal_x by\s*([0-9.]+)\s*and focal_y by\s*([0-9.]+)", adv_text) if adv_text is not None else None
    m_red = re.search(r"max\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\*\s*S_clean\s*\)", p["negative_controls"]["required_red"])
    if not m_red or (adv_text is not None and not m_adv):
        raise PreflightError("cannot parse T28 adverse-intrinsics / required_red rule")
    par = p["numerical_parity"]
    return Plan(
        proposal=p, shas=shas, process_res=int(p["profile"]["process_res"]),
        anchor_view=int(p["split"]["anchor_view"]), scored_view=int(p["split"]["scored_view"]),
        scale_view=int(p["split"]["pose_scale_view"]),
        fit_worlds=tuple(p["split"]["fit_worlds"]), holdout_worlds=tuple(p["split"]["holdout_worlds"]),
        variants=tuple(m["variant"] for m in models), stages=tuple(stages0),
        calls_per_variant=int(models[0]["forward_calls"]), views_per_variant=int(models[0]["forward_views"]),
        known_intrinsics=bool(p["profile"]["known_intrinsics"]),
        focal_scale=(float(m_adv.group(1)), float(m_adv.group(2))) if m_adv else (1.0, 1.0),
        red_floor=float(m_red.group(1)), red_rel=float(m_red.group(2)),
        parity_fields=tuple(par["fields"]),
        parity_cpu=(float(par["cpu_float32"]["atol"]), float(par["cpu_float32"]["rtol"])),
        parity_half=(float(par["mps_float16"]["atol"]), float(par["mps_float16"]["rtol"])),
        claims_forbidden=tuple(p.get("claims_forbidden", ())),
        output_status=str(p["estimation"]["output_status"]),
    )


def load_fixtures(fixtures_dir: Path, plan: Plan) -> dict[str, list[dict[str, Any]]]:
    fixtures_dir = Path(fixtures_dir)
    manifest = json.loads((fixtures_dir / "manifest.json").read_text(encoding="utf-8"))
    worlds: dict[str, list[dict[str, Any]]] = {}
    for row in manifest["rows"]:
        worlds.setdefault(row["world_key"], []).append(row)
    expected = set(plan.fit_worlds) | set(plan.holdout_worlds)
    if set(worlds) != expected:
        raise PreflightError(f"fixture worlds {sorted(worlds)} != T28 split {sorted(expected)}")
    data: dict[str, list[dict[str, Any]]] = {}
    for w, rows in worlds.items():
        rows.sort(key=lambda r: r["timestamp_s"])
        if len(rows) != 3:
            raise PreflightError(f"{w}: expected 3 views, found {len(rows)}")
        want = "fit" if w in plan.fit_worlds else "holdout"
        views = []
        for r in rows:
            if r["split"] != want:
                raise PreflightError(f"{w}: manifest split {r['split']!r} != T28 {want!r}")
            d = fixtures_dir / r["directory"]
            views.append({
                "image": Image.open(d / "rgb.png").convert("RGB"),
                "c2w": np.load(d / "camera_to_world.npy"), "depth": np.load(d / "depth_camera_z.npy"),
                "K": np.load(d / "intrinsics.npy"), "ts": float(r["timestamp_s"]), "split": r["split"],
                "record_id": r["record_id"]})
        data[w] = views
    return data


# ───────────────────────────── teacher 工厂 ─────────────────────────────
class RealTeacherFactory:
    """真实 DA3。惰性导入 torch/管线，纯 CPU 预检不会触发。"""

    conditions_on_intrinsics_only = REAL_DA3_CONDITIONS_ON_INTRINSICS_ONLY

    def make(self, variant: str, device: str, dtype: str):
        sys.path.insert(0, str(T6_ENV_DIR))
        sys.path.insert(0, str(T6_ENV_DIR / "Depth-Anything-3" / "src"))
        from pipeline import DA3GeometryTeacher  # noqa: PLC0415
        return DA3GeometryTeacher(variant=variant, device=device, dtype=dtype)

    def release(self, teacher: Any) -> None:
        del teacher
        gc.collect()
        try:
            import torch  # noqa: PLC0415
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except Exception:  # noqa: BLE001
            pass


class _Counted:
    def __init__(self, teacher: Any):
        self.teacher, self.calls, self.views = teacher, 0, 0

    def process_keyframes(self, images, **kw):
        self.calls += 1
        self.views += len(images)
        return self.teacher.process_keyframes(images, **kw)


# ───────────────────────────── 预检 ─────────────────────────────
def preflight(plan: Plan, factory: Any, pred_dir: Path, out_json: Path, require_empty_outputs: bool = True) -> list[str]:
    """零模型工作。返回通过的检查名；失败抛 PreflightError / ProtocolUnsatisfiable。"""
    checks = ["t28_hashes_bound", "fixtures_match_split"]
    if require_empty_outputs:
        if Path(pred_dir).exists() and any(Path(pred_dir).iterdir()):
            raise PreflightError(f"predictions dir already exists and is non-empty: {pred_dir} "
                                 "(the teacher adapter refuses existing output dirs; use a fresh per-run dir)")
        if Path(out_json).exists():
            raise PreflightError(f"evidence file already exists: {out_json}; never overwrite delivered evidence")
        checks.append("outputs_are_fresh")
    needs_k = plan.known_intrinsics or any(s["stage"] == "intrinsics_adverse" for s in plan.stages)
    if needs_k and not getattr(factory, "conditions_on_intrinsics_only", False):
        raise ProtocolUnsatisfiable(
            "T28 requires known-K conditioning without supplying extrinsics, plus an adverse-intrinsics control that must "
            "turn red (S_bad >= S_clean + max(1e-4, 0.1*S_clean)). This DA3 build ignores intrinsics unless extrinsics are "
            "supplied (model/da3.py: `if extrinsics is not None:` gates cam_enc), so predictions cannot depend on K and the "
            "control is unsatisfiable by construction (S_bad == S_clean). A coordinator/user amendment of the frozen "
            "protocol is required before any real run.")
    checks.append("protocol_satisfiable_by_teacher")
    return checks


# ───────────────────────────── 运行 ─────────────────────────────
def _write_atomic(path: Path, ev: Mapping[str, Any]) -> None:
    """临时文件 + rename：任何时刻读到的都是完整 JSON。含 pid/随机后缀唯一临时名，避免并发写互踩。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    unique_suffix = f".tmp.{os.getpid()}.{uuid.uuid4().hex}"
    tmp = path.with_name(path.name + unique_suffix)
    try:
        tmp.write_text(json.dumps(ev, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


class _Run:
    def __init__(self, plan, data, factory, pred_dir, task_id, round_):
        self.plan, self.data, self.factory, self.pred_dir = plan, data, factory, Path(pred_dir)
        self.task_id, self.round = task_id, round_
        self.failures: list[str] = []
        self.checkpoint: Callable[[], None] = lambda: None   # 由 run_full_calibration 接上：每阶段后原子落盘
        self.ev: dict[str, Any] = {"calibration": {}, "numerical_parity": {}, "negative_controls": {}, "stages": {},
                                   "forward_accounting": {}}

    def _kw(self, world: str, adverse: bool = False, n: int = 3) -> dict:
        if not self.plan.known_intrinsics:
            return {}
        k = np.stack([v["K"] for v in self.data[world]][:n]).astype(np.float64).copy()
        if adverse:
            k[:, 0, 0] *= self.plan.focal_scale[0]
            k[:, 1, 1] *= self.plan.focal_scale[1]
        return {"intrinsics": k}

    def _call(self, t: _Counted, variant: str, stage: str, world: str, order: Sequence[int] = (0, 1, 2),
              adverse_k: bool = False) -> dict:
        views = self.data[world]
        out = self.pred_dir / variant / stage / world
        n = len(order)
        # 时间戳/GT 评分标签保持规范位置 [0,1,2][:n]，即使 RGB 关联被逆序（T28 frame_order_adverse）。
        res = t.process_keyframes(
            [views[i]["image"] for i in order], timestamps_s=[views[j]["ts"] for j in range(n)], world_key=world,
            partition="development", output_dir=out, process_res=self.plan.process_res,
            **self._kw(world, adverse_k, n))
        for key, shape_tail in (("depth", views[0]["depth"].shape),):
            if tuple(np.asarray(res[key]).shape) != (n, *shape_tail):
                raise ValueError(f"{variant}/{stage}/{world}: {key} shape {np.asarray(res[key]).shape} != "
                                 f"{(n, *shape_tail)}; resampling is not allowed")
        for key in ("depth", "confidence", "extrinsics", "intrinsics"):
            if not np.isfinite(np.asarray(res[key], dtype=np.float64)).all():
                raise ValueError(f"{variant}/{stage}/{world}: non-finite {key}")
        return res

    def _metrics(self, world: str, res: Mapping[str, Any]) -> dict:
        v = self.data[world]
        pred_c2w = M.w2c_to_c2w(res["extrinsics"])
        return M.anchored_residual([x["c2w"] for x in v], list(pred_c2w), [x["depth"] for x in v],
                                   [np.asarray(res["depth"][i]) for i in range(3)])

    def run_variant(self, variant: str) -> None:
        plan, st = self.plan, {}
        self.ev["stages"][variant] = st          # 同一个 dict，阶段一完成就可见
        cur, t = None, None
        acc = {"calls": 0, "views": 0}
        load_s: dict[str, float] = {}
        calib: dict[str, Any] = {}
        ref_w00: dict[str, Any] | None = None
        s_clean = None
        for stage in plan.stages:
            name, dev, prec = stage["stage"], stage["device"], stage["precision"]
            if (dev, prec) != cur:
                if t is not None:
                    acc["calls"] += t.calls
                    acc["views"] += t.views
                    self.factory.release(t.teacher)
                t0 = time.time()
                t = _Counted(self.factory.make(variant, dev, prec))
                load_s[f"{dev}_{prec}"] = round(time.time() - t0, 3)
                cur = (dev, prec)
            t_stage = time.time()
            if name == "first_frame":
                r = self._call(t, variant, name, stage["worlds"][0], order=(0,))
                st[name] = {"ok": True, "frames": 1, "depth_shape": list(np.asarray(r["depth"]).shape)}
            elif name == "calibration":
                per_world, fit, hold = {}, [], []
                for w in stage["worlds"]:
                    r = self._call(t, variant, name, w)
                    m = self._metrics(w, r)
                    if w == "t6-analytic-room-00":
                        ref_w00 = {k: np.asarray(r[k]) for k in plan.parity_fields}
                        s_clean = M.adverse_score(m)
                    per_world[w] = {"split": self.data[w][0]["split"], **{k: v for k, v in m.items() if k != "residual_7d"},
                                    "residual_7d": [float(x) for x in m["residual_7d"]]}
                    (fit if w in plan.fit_worlds else hold).append(m["residual_7d"])
                calib = {"per_world": per_world, "fit": M.fit_statistics(fit),
                         "holdout_residual_mean": np.mean(np.asarray(hold), axis=0).tolist()}
                st[name] = {"ok": True, "worlds": list(per_world)}
                self.ev["calibration"][variant] = calib
            elif name in ("frame_order_adverse", "intrinsics_adverse"):
                w = stage["worlds"][0]
                if s_clean is None:
                    raise RuntimeError("calibration stage must precede adverse stages")
                order = (2, 1, 0) if name == "frame_order_adverse" else (0, 1, 2)
                r = self._call(t, variant, name, w, order=order, adverse_k=(name == "intrinsics_adverse"))
                s_bad = M.adverse_score(self._metrics(w, r))
                red = M.required_red(s_clean, s_bad, plan.red_floor, plan.red_rel)
                st[name] = {"ok": red, "S_clean": s_clean, "S_bad": s_bad,
                            "required_margin": max(plan.red_floor, plan.red_rel * s_clean), "turned_red": red}
                if not red:
                    self.failures.append(f"{variant}/{name}: adverse control did not turn red")
            elif name in ("cpu_parity", "half_parity"):
                w = stage["worlds"][0]
                atol, rtol = plan.parity_cpu if name == "cpu_parity" else plan.parity_half
                r = self._call(t, variant, name, w)
                cmp = M.parity_compare(ref_w00 or {}, {k: np.asarray(r[k]) for k in plan.parity_fields},
                                       plan.parity_fields, atol, rtol)
                self.ev["numerical_parity"].setdefault(variant, {})[name] = cmp
                st[name] = {"ok": cmp["pass"]}
                if not cmp["pass"]:
                    self.failures.append(f"{variant}/{name}: numerical parity failed (tolerances not relaxed)")
            else:
                raise RuntimeError(f"unknown T28 stage {name!r}")
            st[name]["wall_s"] = round(time.time() - t_stage, 3)
            self.ev["forward_accounting"][variant] = {
                "calls_so_far": acc["calls"] + (t.calls if t else 0), "views_so_far": acc["views"] + (t.views if t else 0),
                "calls_planned": plan.calls_per_variant, "views_planned": plan.views_per_variant, "complete": False}
            self.ev["failures"] = list(self.failures)
            self.checkpoint()                       # MPS fp16 的 dtype 错误是 SIGABRT(134)，进程直接消失：之前每个阶段的证据必须已经在盘上
        if t is not None:
            acc["calls"] += t.calls
            acc["views"] += t.views
            self.factory.release(t.teacher)
        self.ev["stages"][variant] = st
        self.ev["calibration"][variant] = calib
        planned = {"calls_planned": plan.calls_per_variant, "views_planned": plan.views_per_variant}
        actual = {"calls_actual": acc["calls"], "views_actual": acc["views"], "load_s": load_s}
        self.ev["forward_accounting"][variant] = {**planned, **actual, "complete": True}
        if (acc["calls"], acc["views"]) != (plan.calls_per_variant, plan.views_per_variant):
            self.failures.append(f"{variant}: forward accounting {acc} != T28 plan "
                                 f"({plan.calls_per_variant} calls, {plan.views_per_variant} views)")

    def boundary_guards(self) -> list[dict]:
        """CPU 边界拒绝：只证明守卫会拒绝，不是模型响应型负控证明（T28 boundary_rejection）。"""
        v = self.data[sorted(self.data)[0]]
        gt = [x["c2w"] for x in v]
        d = [x["depth"] for x in v]
        cases = {
            "zero_depth": lambda: M.anchored_residual(gt, gt, d, [np.zeros_like(d[0]), d[1]]),
            "non_so3_rotation": lambda: M.w2c_to_c2w(np.array([np.diag([2.0, 1.0, 1.0, 0.0])[:3, :4]])),
            "zero_gt_baseline": lambda: M.anchored_residual([gt[0]] * 3, gt, d, d),
        }
        out = []
        for name, fn in cases.items():
            try:
                fn()
                out.append({"name": name, "rejected": False, "kind": "boundary_rejection"})
                self.failures.append(f"boundary guard {name} did not reject")
            except ValueError as e:
                out.append({"name": name, "rejected": True, "error": str(e), "kind": "boundary_rejection"})
        return out


def run_full_calibration(output_json_path: Path, predictions_dir: Path, task_id: str = "ainerzero.V9.T35",
                         teacher_factory: Any = None, fixtures_dir: Path = FIXTURES_DIR,
                         proposal_path: Path | None = None, round_: str = "unbound",
                         verify_hashes: bool = True) -> tuple[dict[str, Any], int]:
    """返回 (evidence, 退出码)。预检失败不写证据（尚无证据可写），其余路径无论成败都写证据并保留输出。"""
    t0 = time.time()
    factory = teacher_factory or RealTeacherFactory()
    out_json, pred_dir = Path(output_json_path).resolve(), Path(predictions_dir).resolve()
    target_proposal = Path(proposal_path) if proposal_path is not None else get_default_proposal_path()
    plan = load_plan(target_proposal, fixtures_dir, verify_hashes=verify_hashes)
    data = load_fixtures(fixtures_dir, plan)
    checks = preflight(plan, factory, pred_dir, out_json)          # 抛 PreflightError / ProtocolUnsatisfiable
    pred_dir.mkdir(parents=True, exist_ok=True)
    run = _Run(plan, data, factory, pred_dir, task_id, round_)
    ev: dict[str, Any] = run.ev
    ev.update({"schema": "v9.t6.da3_calibration_evidence.v2", "task": task_id, "round": round_,
               "protocol": {"proposal_sha256": plan.shas["proposal"], "manifest_sha256": plan.shas["manifest"],
                            "protocol_sha256": plan.shas["protocol"], "generator_sha256": plan.shas["generator"],
                            "process_res": plan.process_res, "variants": list(plan.variants)},
               "preflight_checks": checks, "claims_forbidden": list(plan.claims_forbidden)})
    ev["protocol"]["proposal_path"] = str(target_proposal.resolve())
    ev["status"] = "in_progress"
    ev["failures"] = []
    run.checkpoint = lambda: _write_atomic(out_json, ev)
    run.checkpoint()                                  # 硬中止（SIGABRT 等）时至少留下这份：status 仍为 in_progress
    code = EXIT_OK
    try:
        for variant in plan.variants:
            run.run_variant(variant)
        ev["negative_controls"]["boundary_guards"] = run.boundary_guards()
    except Exception as exc:  # noqa: BLE001  运行期错误是失败，不是"预期的几何拒绝"（T28 unrelated_error）
        run.failures.append(f"runtime error: {type(exc).__name__}: {exc}")
        code = EXIT_ERROR
    files = [{"path": str(p.relative_to(pred_dir)), "bytes": p.stat().st_size, "sha256": sha256_file(p)}
             for p in sorted(pred_dir.rglob("*")) if p.is_file()]
    ev["predictions_manifest"] = {"dir": str(pred_dir), "total_files": len(files),
                                  "total_bytes": sum(f["bytes"] for f in files), "files": files}
    ev["failures"] = list(run.failures)
    if run.failures and code == EXIT_OK:
        code = EXIT_STAGE_FAILED
    ev["status"] = plan.output_status if not run.failures else "failed"
    ev["registration"] = "none; no noise-model registration, no NEES, no capability claim"
    ev["total_wall_seconds"] = round(time.time() - t0, 2)
    _write_atomic(out_json, ev)
    return ev, code


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T6 DA3 calibration runner (faithful to T28)")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--predictions-dir", type=Path, required=True)
    ap.add_argument("--task", default="ainerzero.V9.T35")
    ap.add_argument("--round", default="unbound")
    ap.add_argument("--proposal", type=Path, default=None,
                    help="T28 proposal.json 路径；默认有登记时取登记，无登记时保持 r1。证据会记录路径与 SHA")
    ap.add_argument("--preflight-only", action="store_true",
                    help="zero model work, zero ledger: verify hashes, outputs and protocol satisfiability, then exit")
    a = ap.parse_args(argv)
    try:
        target_proposal = a.proposal if a.proposal is not None else get_default_proposal_path()
        if a.preflight_only:
            plan = load_plan(target_proposal)
            load_fixtures(FIXTURES_DIR, plan)
            checks = preflight(plan, RealTeacherFactory(), a.predictions_dir, a.output)
            print(json.dumps({"preflight": "ok", "checks": checks}))
            return EXIT_OK
        ev, code = run_full_calibration(a.output, a.predictions_dir, a.task, round_=a.round,
                                        proposal_path=target_proposal)
        print(f"calibration status={ev['status']} failures={len(ev['failures'])} wall={ev['total_wall_seconds']}s")
        return code
    except PreflightError as e:
        print(f"PREFLIGHT FAILED (no model work done): {e}", file=sys.stderr)
        return EXIT_PREFLIGHT
    except ProtocolUnsatisfiable as e:
        print(f"PROTOCOL UNSATISFIABLE (no model work done): {e}", file=sys.stderr)
        return EXIT_UNSATISFIABLE


if __name__ == "__main__":
    raise SystemExit(main())
