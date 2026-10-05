"""MRI-guided PET enhancement with a hybrid CNN / Vision-Transformer U-Net (ONNX runtime).

Why a ViT hybrid: convolutions capture local edges, while self-attention at the bottleneck
captures global structure (symmetry, distant uptake context).  For high-fidelity medical
synthesis where global structure matters, ViT-hybrid models outperform CycleGAN-style
purely convolutional generators (see docs/LITERATURE.md); CycleGAN remains the tool of
choice for *unpaired* domain mapping and is provided in ``training/train_cyclegan.py``.

Input contract (shared with ``training/``):  2.5-D stacks of ``CONTEXT`` neighbouring slices
on each side — the PET resampled onto the MRI grid and the MRI itself — each normalised by
a robust in-head percentile.  The network predicts the sharp PET of the centre slice.
Using neighbouring planes keeps adjacent slices consistent (Chen et al., 2025, motivate
3-D-aware synthesis for exactly this reason).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from scipy import ndimage as ndi

from .. import imaging as im

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
ENHANCER_ONNX = MODEL_DIR / "enhancer_vit.onnx"
CONTEXT = 1  # slices on each side
IN_CHANNELS = 2 * (2 * CONTEXT + 1)
MULTIPLE = 16


def normalisation(pet: np.ndarray, mri: np.ndarray, head: np.ndarray) -> tuple[float, float]:
    sel = head if np.any(head) else np.ones_like(pet, bool)
    ps = float(np.percentile(pet[sel], 99.5))
    ms = float(np.percentile(mri[sel], 99.0))
    return max(ps, 1e-6), max(ms, 1e-6)


def slab(vol: np.ndarray, k: int) -> np.ndarray:
    """``2*CONTEXT+1`` slices centred on ``k`` with edge replication -> [C, H, W]."""
    idx = np.clip(np.arange(k - CONTEXT, k + CONTEXT + 1), 0, vol.shape[0] - 1)
    return vol[idx]


def stack_inputs(pet_n: np.ndarray, mri_n: np.ndarray, k: int) -> np.ndarray:
    return np.concatenate([slab(pet_n, k), slab(mri_n, k)], 0).astype(np.float32)


def padded_crop(head: np.ndarray, margin: int = 4) -> tuple[slice, slice, slice, tuple[int, int]]:
    """Head bounding box with in-plane size padded up to a multiple of ``MULTIPLE``."""
    zs, ys, xs = im.bbox(head, margin=margin)
    H, W = ys.stop - ys.start, xs.stop - xs.start
    Hp = int(np.ceil(H / MULTIPLE) * MULTIPLE)
    Wp = int(np.ceil(W / MULTIPLE) * MULTIPLE)
    return zs, ys, xs, (Hp, Wp)


@lru_cache(maxsize=2)
def _session(path: str):
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])


def model_card(path: Path = ENHANCER_ONNX) -> dict | None:
    meta = path.with_suffix(".json")
    if meta.exists():
        return json.loads(meta.read_text())
    return None


def available(path: Path = ENHANCER_ONNX) -> bool:
    return Path(path).exists()


def enhance_ai(
    pet_in_mri: sitk.Image,
    mri: sitk.Image,
    head_mask: np.ndarray,
    model_path: Path = ENHANCER_ONNX,
    batch: int = 8,
    progress: Callable[[float, str], None] | None = None,
) -> sitk.Image:
    """Run the ViT-hybrid enhancer slice-by-slice over the head; returns SUV on the MRI grid."""
    if not available(model_path):
        raise FileNotFoundError(f"enhancer model not found: {model_path} (run training/train_enhancer.py)")
    sess = _session(str(model_path))
    pet = im.arr(pet_in_mri)
    mri_a = im.arr(mri)
    ps, ms = normalisation(pet, mri_a, head_mask)
    pet_n = pet / ps
    mri_n = np.clip(mri_a / ms, 0, 2.0)
    zs, ys, xs, (Hp, Wp) = padded_crop(head_mask)
    H, W = ys.stop - ys.start, xs.stop - xs.start
    out = pet.copy()
    ks = list(range(zs.start, zs.stop))
    for b0 in range(0, len(ks), batch):
        kb = ks[b0 : b0 + batch]
        x = np.zeros((len(kb), IN_CHANNELS, Hp, Wp), np.float32)
        for i, k in enumerate(kb):
            x[i, :, :H, :W] = stack_inputs(pet_n, mri_n, k)[:, ys, xs]
        y = sess.run(None, {"x": x})[0]
        for i, k in enumerate(kb):
            out[k, ys, xs] = y[i, 0, :H, :W] * ps
        if progress:
            progress((b0 + len(kb)) / len(ks), f"ViT-hybrid enhancer · slice {b0 + len(kb)}/{len(ks)}")
    out = np.clip(out, 0, None)
    keep = ndi.binary_dilation(head_mask, iterations=3)
    out = np.where(keep, out, 0.0).astype(np.float32)
    return im.like(out, pet_in_mri)
