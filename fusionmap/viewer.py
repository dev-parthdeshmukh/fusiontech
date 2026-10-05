"""Compact viewer assets: 8-bit volumes (gzip) + manifest, and a rotating-MIP sprite."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from scipy import ndimage as ndi
from skimage import io as skio

from .fusion import lut


def write_u8(path: Path, a: np.ndarray, lo: float, hi: float) -> dict:
    q = np.clip((a - lo) / max(hi - lo, 1e-9) * 255.0, 0, 255).round().astype(np.uint8)
    path.write_bytes(gzip.compress(np.ascontiguousarray(q).tobytes(), compresslevel=6))
    return {"file": path.name, "lo": float(lo), "hi": float(hi)}


def write_labels(path: Path, a: np.ndarray) -> dict:
    path.write_bytes(gzip.compress(np.ascontiguousarray(a.astype(np.uint8)).tobytes(), compresslevel=6))
    return {"file": path.name, "lo": 0.0, "hi": 255.0, "labels": True}


def write_manifest(folder: Path, ref: sitk.Image, volumes: dict[str, dict], extra: dict | None = None) -> dict:
    size = list(ref.GetSize())
    manifest = {
        "shape_zyx": size[::-1],
        "spacing_xyz": [float(s) for s in ref.GetSpacing()],
        "origin_xyz": [float(o) for o in ref.GetOrigin()],
        "orientation": "LPS, identity direction cosines",
        "volumes": volumes,
        **(extra or {}),
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def mip_sprite(pet: np.ndarray, spacing_mm: float, path: Path, frames: int = 36, colormap: str = "hot",
               vmax: float | None = None, threshold: float | None = None) -> dict:
    """Rotating maximum-intensity projection (the classic nuclear-medicine 3-D display).

    Normal uptake is drawn in greyscale; uptake above the tumour threshold in colour, so lesions
    pop out of the brain silhouette.
    """
    factor = min(1.0, spacing_mm / 2.0)
    small = ndi.zoom(pet, factor, order=1) if factor < 1 else pet
    vmax = vmax or float(np.percentile(small, 99.95)) or 1.0
    table = lut(colormap).astype(np.float32)
    thr = float(threshold) if threshold is not None else 0.6 * vmax
    tiles = []
    for i in range(frames):
        ang = 360.0 * i / frames
        rot = ndi.rotate(small, ang, axes=(1, 2), reshape=False, order=1, mode="constant", cval=0.0)
        proj = rot.max(axis=1)[::-1]  # (z, x) with superior up
        g = np.clip(proj / max(thr, 1e-6), 0, 1)[..., None] * 200.0
        t = np.clip((proj - thr) / max(vmax - thr, 1e-6), 0, 1)
        col = table[(t * 255).astype(np.uint8)]
        a = np.clip(t * 3.0, 0, 1)[..., None]
        tiles.append(np.clip(g * (1 - a) + col * a, 0, 255).astype(np.uint8))
    h, w = tiles[0].shape[:2]
    sheet = np.concatenate(tiles, axis=1)
    skio.imsave(path, sheet, check_contrast=False)
    return {"file": path.name, "frames": frames, "frame_width": int(w), "frame_height": int(h)}
