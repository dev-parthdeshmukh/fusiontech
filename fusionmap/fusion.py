"""Step 3 — colour-coded PET-on-MRI fusion.

The MRI supplies anatomy as greyscale; the PET is mapped through a colour table and blended
on top wherever uptake exceeds a threshold, with opacity rising smoothly with uptake.
The same colour tables are served to the web viewer (``/api/colormaps``) so what the
clinician sees on screen is exactly what is burned into the exported DICOM.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# control points: (position 0..1, r, g, b)
COLORMAPS: dict[str, list[tuple[float, int, int, int]]] = {
    "hot": [(0.0, 0, 0, 0), (0.35, 200, 0, 0), (0.65, 255, 150, 0), (0.85, 255, 235, 60), (1.0, 255, 255, 255)],
    "inferno": [(0.0, 0, 0, 4), (0.2, 50, 10, 94), (0.4, 120, 28, 109), (0.6, 188, 55, 84), (0.8, 245, 125, 21),
                (1.0, 252, 255, 164)],
    "rainbow": [(0.0, 0, 0, 0), (0.15, 80, 0, 160), (0.3, 0, 60, 255), (0.45, 0, 200, 220), (0.6, 0, 220, 60),
                (0.75, 255, 230, 0), (0.9, 255, 60, 0), (1.0, 255, 255, 255)],
    "cividis": [(0.0, 0, 34, 78), (0.25, 66, 77, 107), (0.5, 124, 123, 120), (0.75, 188, 175, 111),
                (1.0, 255, 234, 70)],
    "gray": [(0.0, 0, 0, 0), (1.0, 255, 255, 255)],
}


def lut(name: str, n: int = 256) -> np.ndarray:
    pts = COLORMAPS.get(name, COLORMAPS["hot"])
    pos = np.array([p[0] for p in pts])
    rgb = np.array([p[1:] for p in pts], dtype=np.float32)
    x = np.linspace(0, 1, n)
    out = np.stack([np.interp(x, pos, rgb[:, c]) for c in range(3)], -1)
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def all_luts() -> dict[str, list[list[int]]]:
    return {k: lut(k).tolist() for k in COLORMAPS}


@dataclass
class FusionSettings:
    colormap: str = "hot"
    mri_window: tuple[float, float] | None = None  # (low, high) in MRI units; None = auto
    pet_range: tuple[float, float] | None = None  # (threshold, max) in SUV; None = auto
    opacity: float = 0.75


def auto_pet_range(pet: np.ndarray, mask: np.ndarray | None = None) -> tuple[float, float]:
    vals = pet[mask] if mask is not None and np.any(mask) else pet[pet > 0]
    if vals.size == 0:
        return 0.0, 1.0
    hi = float(np.percentile(vals, 99.9))
    lo = float(np.percentile(vals, 60))
    return lo, max(hi, lo + 1e-3)


def auto_mri_window(mri: np.ndarray, mask: np.ndarray | None = None) -> tuple[float, float]:
    vals = mri[mask] if mask is not None and np.any(mask) else mri[mri > 0]
    if vals.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(vals, [1, 99.5])
    return float(lo), float(max(hi, lo + 1e-3))


def fuse(mri: np.ndarray, pet: np.ndarray, settings: FusionSettings | None = None,
         mask: np.ndarray | None = None) -> np.ndarray:
    """Return an RGB uint8 array ``[..., 3]`` with PET blended onto greyscale MRI."""
    s = settings or FusionSettings()
    lo_m, hi_m = s.mri_window or auto_mri_window(mri, mask)
    thr, top = s.pet_range or auto_pet_range(pet, mask)
    gray = np.clip((mri - lo_m) / (hi_m - lo_m), 0, 1)
    t = np.clip((pet - thr) / (top - thr), 0, 1)
    idx = np.round(t * 255).astype(np.int32)
    color = lut(s.colormap)[idx].astype(np.float32) / 255.0
    alpha = (s.opacity * np.clip(t * 4.0, 0, 1))[..., None]  # fade in just above threshold
    rgb = gray[..., None] * (1 - alpha) + color * alpha
    return np.clip(np.round(rgb * 255), 0, 255).astype(np.uint8)


def checkerboard(a: np.ndarray, b: np.ndarray, tile: int = 16) -> np.ndarray:
    """Interleave two equally-shaped 2-D/3-D arrays in a checkerboard (registration QA)."""
    idx = np.indices(a.shape[-2:]) // tile
    m = ((idx[0] + idx[1]) % 2).astype(bool)
    return np.where(m, a, b)
