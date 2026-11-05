# vjepa2-mlx

Pure [MLX](https://github.com/ml-explore/mlx) port of **V-JEPA 2** (2.1 and 2.0)
image/video models for Apple Silicon — **inference and training**.

> Port of [facebookresearch/vjepa2](https://github.com/facebookresearch/vjepa2)
> (`app/vjepa_2_1/` + `src/`), MIT-licensed. Original weights © Meta Platforms, Inc.

This is a full port, not inference-only: the 2.1 and 2.0 ViT encoders, the 2.1
predictor (world-model), the eval preprocessor, the downstream attentive-probe
classifiers, and the complete JEPA training stack (single-device **and**
multi-device via `mx.distributed`) with a real video data pipeline.

## Status

The port is **functionally complete and parity-locked** against the upstream
PyTorch reference. File paths and class names mirror upstream 1:1 (isomorphic
port — see `INTERFACE.md`).

| Component | State | Parity vs PyTorch (real weights) |
|---|---|---|
| 3D RoPE attention / blocks / patch-embed | ✅ | per-module ≤ 5e-5 |
| **2.1 ViT encoder** (`models/vision_transformer.py`) | ✅ | full fwd < 1e-3; **per-block ≤ 6.6e-5** (rel) |
| **2.1 predictor** (`models/predictor.py`) | ✅ | x_pred 1.2e-4 / x_ctx 2.9e-4; **per-block ≤ 1.7e-5** |
| Eval preprocessor (`preprocess.py`) | ✅ | bit-identical |
| **2.0 ViT encoder** (`v2/models/`) | ✅ | per-module ≤ 5e-5; **per-block ≤ 5.2e-5** |
| Attentive classifier probe (SSv2/Diving48/EK100) | ✅ | SSv2 e2e logits 3.3e-5, **argmax agrees** |
| JEPA training (schedulers, loss, EMA, masking) | ✅ | one-step bit-level |
| Video data pipeline (decode/transform/dataset/loader) | ✅ | real-mp4 → train, loss decreases |
| Distributed training (`training/distributed.py`) | ✅ | 2-rank cross-rank param diff 0.0 |
| Weight conversion | ✅ | mlx-forge recipes (see below) |

Tests: **122 passing** (parity + smoke) plus a real 2-rank distributed launch
test. Parity tests treat PyTorch as an optional dev dependency.

## Layout

```
packages/vjepa2-core-mlx/src/vjepa2_core_mlx/
├── models/                     # V-JEPA 2.1 line
│   ├── vision_transformer.py   # VisionTransformer encoder + vit_*_rope()
│   ├── predictor.py            # world-model predictor
│   └── utils/{modules.py, patch_embed.py}
├── v2/models/                  # V-JEPA 2.0 line (different RoPE convention)
│   ├── vision_transformer.py
│   ├── attentive_pooler.py     # AttentivePooler / AttentiveClassifier probes
│   └── utils/{modules.py, patch_embed.py}
├── training/                   # JEPA training
│   ├── schedulers.py, loss.py, trainer.py, distributed.py
│   ├── masks/multiseq_multiblock3d.py
│   └── data/{decoder.py, transforms.py, video_dataset.py, loader.py}
├── preprocess.py               # eval transform (resize/crop/normalize)
├── masks/utils.py, utils/{weights.py, tensors.py}
tests/{parity,smoke,distributed}/
```

## Quick start

```bash
# install the workspace (uv recommended)
uv pip install -e packages/vjepa2-core-mlx

# run the MLX-only smoke tests
python -m pytest tests/smoke -q

# run parity tests (requires the [parity] extra: torch + numpy)
uv pip install -e "packages/vjepa2-core-mlx[parity]"
python -m pytest tests/parity -q
```

Load a converted 2.1 encoder:

```python
from vjepa2_core_mlx.utils.weights import from_pretrained

encoder = from_pretrained("/path/to/converted-mlx-weights")  # dir of safetensors
feats = encoder(clip)   # clip: (B, C, T, H, W) channels-first
```

Weights are converted from the released Meta checkpoints with the `mlx-forge`
recipes `vjepa2-vit-l-rope` (2.1 encoder + predictor) and `vjepa2-vitl` (2.0
encoder + SSv2/Diving48/EK100 probes). `from_pretrained()` defaults to the
published [`dgrauet/vjepa-2.1-vitl-mlx`](https://huggingface.co/dgrauet/vjepa-2.1-vitl-mlx)
repo (encoder + predictor, F32); pass a local converted directory or another
repo id to override.

## License

MIT (see `LICENSE`). Preserves Meta's upstream MIT license.
