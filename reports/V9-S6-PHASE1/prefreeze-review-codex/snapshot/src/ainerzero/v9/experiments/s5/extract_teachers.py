"""S5 教师特征抽取（V-JEPA 2.1 与 Depth Anything V2 Small）。

依据：`reports/V9-S5-DESIGN/DESIGN-r1.md` §2、§3、§6、§7；预处理照摸底脚本
`reports/V9-S5-DESIGN/tier1-explore/explore_s5a.py` 第 2、3 节。

输入是物化目录（P229 的 `materialize.py` 写出）：
- `world_XXXX/clip_YY.npy`：uint8 [16, 224, 224, 3]；
- `world_XXXX/da2_YY.npy`：uint8 [8, 392, 518, 3]，只有 pool 有（每个管长的第二帧，焦距 196）；
- `manifest.json`。

输出：
- V-JEPA：`world_XXXX/clip_YY.vjepa.npy`，fp16 [1568, 1024]；
- DA2：`world_XXXX/da2_YY.da2.npy`，fp16 [8, 56, 56]（输出图取中间 392 列，按面积平均缩到 56×56）；
- `progress.jsonl`：每写完一段追加一行（相对路径、SHA256、耗时、时间）；
- `manifest.json`：输入清单 SHA、教师权重 SHA、代码身份、环境版本、预处理参数、耗时。

本文件本身只用 NumPy；真教师在 `make_vjepa()` / `make_da2()` 里才导入，必须在教师环境下跑：
  envs/teachers/.venv-t4/bin/python -I src/ainerzero/v9/experiments/s5/extract_teachers.py \\
      --teacher vjepa --in <分区目录> --out <输出目录>
真教师模式先拿 `artifacts/locks/m0-worker.lock`（非阻塞 flock），拿不到退出码 75，拿到之前不写任何文件。
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

ROOT = Path(__file__).resolve().parents[5]
LOCK = ROOT / "artifacts/locks/m0-worker.lock"
EXIT_LOCK_BUSY = 75

VJEPA_DIR = ROOT / "artifacts/teachers/t4-approved/b0674736bad10eb16bd765942a9065e7e2ee9a54"
DA2_PKG = ROOT / "artifacts/teachers/t4-approved/cfef6f6f2a70783dedc0bfae40cecbc2052285d3/DepthAnythingV2SmallF16.mlpackage"
# Weight SHA256 as recorded in reports/V9-S5-INVENTORY/REPORT.md section 1 (T4-approved revisions).
VJEPA_SHA = {
    "encoder.safetensors": "7a68c25e3515108f81a88c3157ab5aa41322e0b49faf135c35cca147130c8e19",
    "predictor.safetensors": "c601a96f4bdb852ade8c5334b0a8e1beaa7461b60566387ad7a134ee437c2bf7",
    "config.json": "36a174637ddd2976efbe3e166e2c54359afbe2f4cbff67573f71f0691634eb96",
    "split_model.json": "8681855d8bf614758fec95dde10f017a1171ecc232130ae8a3de2f4a4df1a2c5",
}
DA2_SHA = {
    "Data/com.apple.CoreML/weights/weight.bin": "fa60d9b6a155734f59029ebb882fd54e549bfaee3539c1a9cbd2cbbab64a0fed",
    "Data/com.apple.CoreML/model.mlmodel": "44ac97a3efcfd52113183fb2862ff59cd0368e9ec2e30a90a54980dd11407042",
}

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
CLIP_SHAPE = (16, 224, 224, 3)
VJEPA_OUT = (1568, 1024)
DA2_IN = (8, 392, 518, 3)
DA2_CROP = (63, 455)          # middle 392 of 518 columns; matches render.da2_center_crop
DA2_OUT_HW = 56
DA2_RESAMPLE = "PIL.Image.BOX (area average)"
REGISTERED_PARTITIONS = frozenset({"s5p1-final", "s5p1-final-shift"})
SUFFIX = {"vjepa": ".vjepa.npy", "da2": ".da2.npy"}
PREFIX = {"vjepa": "clip_", "da2": "da2_"}


# --- preprocessing / postprocessing (pure NumPy) --------------------------------------------
def vjepa_input(clip: np.ndarray) -> np.ndarray:
    """uint8 [16, 224, 224, 3] -> float32 [1, 3, 16, 224, 224], /255 then ImageNet mean/std."""
    if clip.shape != CLIP_SHAPE or clip.dtype != np.uint8:
        raise ValueError(f"expected uint8 {CLIP_SHAPE}, got {clip.dtype} {clip.shape}")
    mean = np.asarray(IMAGENET_MEAN, dtype=np.float32)[:, None, None, None]
    std = np.asarray(IMAGENET_STD, dtype=np.float32)[:, None, None, None]
    x = (clip.transpose(3, 0, 1, 2).astype(np.float32) / 255.0 - mean) / std
    return x[None]


def da2_target(depth: np.ndarray) -> np.ndarray:
    """DA2 output float [392, 518] -> fp16 [56, 56]: middle 392 columns, area-average resize."""
    from PIL import Image

    if depth.shape != (DA2_IN[1], DA2_IN[2]):
        raise ValueError(f"expected DA2 output {(DA2_IN[1], DA2_IN[2])}, got {depth.shape}")
    crop = np.ascontiguousarray(depth[:, DA2_CROP[0]:DA2_CROP[1]].astype(np.float32))
    img = Image.fromarray(crop, mode="F").resize((DA2_OUT_HW, DA2_OUT_HW), Image.BOX)
    return np.asarray(img, dtype=np.float32).astype(np.float16)


# --- bookkeeping -------------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def verify_weights(base: Path, expected: dict[str, str]) -> dict[str, str]:
    got = {}
    for rel, want in expected.items():
        sha = sha256_file(base / rel)
        if sha != want:
            raise RuntimeError(f"teacher weight SHA mismatch: {base / rel}: {sha} != {want}")
        got[rel] = sha
    return got


def code_identity() -> dict[str, str]:
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001 - identity is best effort; the file SHA below is authoritative
        head = ""
    return {"git_head": head, "extract_teachers.py": sha256_file(Path(__file__))}


def iter_items(in_dir: Path, teacher: str, worlds: tuple[int, int] | None) -> Iterator[tuple[Path, str]]:
    """Yield (input .npy path, output relative path) in world/clip order."""
    for wdir in sorted(p for p in in_dir.iterdir() if p.is_dir() and p.name.startswith("world_")):
        w = int(wdir.name.split("_")[1])
        if worlds is not None and not (worlds[0] <= w < worlds[1]):
            continue
        for src in sorted(wdir.glob(f"{PREFIX[teacher]}[0-9][0-9].npy")):
            yield src, f"{wdir.name}/{src.stem}{SUFFIX[teacher]}"


def _read_ledger(path: Path) -> dict[str, str]:
    ledger: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                ledger[rec["file"]] = rec["sha256"]
    return ledger


# --- core loop ----------------------------------------------------------------------------------
def run(teacher: str, in_dir: Path, out_dir: Path, fn: Callable[[np.ndarray], np.ndarray], *,
        worlds: tuple[int, int] | None = None, extra_manifest: dict | None = None) -> dict:
    """Apply `fn` (input array -> fp16 output) to every item; resumable, tamper-checked."""
    if teacher not in SUFFIX:
        raise ValueError(f"unknown teacher {teacher!r}")
    in_manifest = in_dir / "manifest.json"
    meta = json.loads(in_manifest.read_text(encoding="utf-8"))
    if meta.get("partition") in REGISTERED_PARTITIONS:
        raise PermissionError(f"{meta.get('partition')} is a registered partition; teachers are not extracted for it")
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = out_dir / "progress.jsonl"
    ledger = _read_ledger(ledger_path)
    for rel, sha in ledger.items():                          # files we wrote earlier must be intact
        p = out_dir / rel
        if not p.exists() or sha256_file(p) != sha:
            raise RuntimeError(f"tampered or missing output: {rel}")
    want_shape = VJEPA_OUT if teacher == "vjepa" else (8, DA2_OUT_HW, DA2_OUT_HW)
    times, n_done, n_skip = [], 0, 0
    t_all = time.perf_counter()
    for src, rel in iter_items(in_dir, teacher, worlds):
        dst = out_dir / rel
        if rel in ledger:
            n_skip += 1
            continue
        if dst.exists():
            raise RuntimeError(f"output exists but is not in the ledger: {rel}")
        t0 = time.perf_counter()
        y = np.asarray(fn(np.load(src)))
        if y.shape != want_shape or y.dtype != np.float16:
            raise RuntimeError(f"{rel}: teacher output {y.dtype} {y.shape}, expected float16 {want_shape}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        with open(tmp, "wb") as f:
            np.save(f, y)
        os.replace(tmp, dst)
        dt = time.perf_counter() - t0
        sha = sha256_file(dst)
        with open(ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"file": rel, "sha256": sha, "seconds": dt, "at": time.time()}) + "\n")
        times.append(dt)
        n_done += 1
    manifest = {
        "teacher": teacher,
        "input_dir": str(in_dir),
        "input_manifest_sha256": sha256_file(in_manifest),
        "partition": meta.get("partition"),
        "worlds": list(worlds) if worlds else None,
        "written": n_done, "skipped_already_done": n_skip,
        "seconds_total": time.perf_counter() - t_all,
        "seconds_median_per_item": float(np.median(times)) if times else None,
        "code": code_identity(),
        "preprocess": ({"mean": IMAGENET_MEAN, "std": IMAGENET_STD, "layout": "[1,3,16,224,224] float32",
                        "output": "fp16 [1568,1024]"} if teacher == "vjepa" else
                       {"crop_columns": list(DA2_CROP), "resize": DA2_RESAMPLE, "output": "fp16 [8,56,56]"}),
        "ledger_sha256": sha256_file(ledger_path) if ledger_path.exists() else None,
    }
    if extra_manifest:
        manifest.update(extra_manifest)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


# --- real teachers (teacher environment only) ---------------------------------------------------
def make_vjepa() -> tuple[Callable[[np.ndarray], np.ndarray], dict]:
    shas = verify_weights(VJEPA_DIR, VJEPA_SHA)
    import mlx.core as mx
    import vjepa2_core_mlx.utils.weights as weights

    enc = weights.from_pretrained(VJEPA_DIR, img_size=(224, 224), num_frames=16)

    def fn(clip: np.ndarray) -> np.ndarray:
        y = enc(mx.array(vjepa_input(clip)))
        mx.eval(y)
        return np.array(y[0], dtype=np.float32).astype(np.float16)

    return fn, {"teacher_weights_sha256": shas, "mlx_version": mx.__version__}


def make_da2() -> tuple[Callable[[np.ndarray], np.ndarray], dict]:
    shas = verify_weights(DA2_PKG, DA2_SHA)
    import coremltools as ct
    from PIL import Image

    model = ct.models.MLModel(str(DA2_PKG), compute_units=ct.ComputeUnit.CPU_AND_NE)

    def one(frame: np.ndarray) -> np.ndarray:
        pr = model.predict({"image": Image.fromarray(frame)})
        if len(pr) != 1:
            raise RuntimeError(f"DA2 returned {sorted(pr)}; expected exactly one output")
        out = next(iter(pr.values()))
        out = np.asarray(out.convert("F") if hasattr(out, "convert") else out, dtype=np.float32).squeeze()
        return da2_target(out)

    def fn(frames: np.ndarray) -> np.ndarray:
        if frames.shape != DA2_IN or frames.dtype != np.uint8:
            raise ValueError(f"expected uint8 {DA2_IN}, got {frames.dtype} {frames.shape}")
        return np.stack([one(f) for f in frames])

    return fn, {"teacher_weights_sha256": shas, "coremltools_version": ct.__version__}


FACTORIES: dict[str, Callable[[], tuple[Callable[[np.ndarray], np.ndarray], dict]]] = {
    "vjepa": make_vjepa, "da2": make_da2}


def acquire_lock(path: Path):
    fh = open(path, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def main(argv: list[str] | None = None, *, lock_path: Path = LOCK,
         factories: dict | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--teacher", required=True, choices=sorted(SUFFIX))
    ap.add_argument("--in", dest="in_dir", required=True)
    ap.add_argument("--out", dest="out_dir", required=True)
    ap.add_argument("--worlds", default=None, help="a:b, half-open")
    a = ap.parse_args(argv)
    worlds = tuple(int(v) for v in a.worlds.split(":")) if a.worlds else None
    lock = acquire_lock(Path(lock_path))                     # lock first; nothing is written before this
    if lock is None:
        print("lock busy", flush=True)
        return EXIT_LOCK_BUSY
    try:
        fn, extra = (factories or FACTORIES)[a.teacher]()
        m = run(a.teacher, Path(a.in_dir), Path(a.out_dir), fn, worlds=worlds, extra_manifest=extra)
        print(json.dumps({k: m[k] for k in ("teacher", "partition", "written", "skipped_already_done",
                                             "seconds_total", "seconds_median_per_item")}), flush=True)
        return 0
    finally:
        lock.close()


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    sys.exit(main())
