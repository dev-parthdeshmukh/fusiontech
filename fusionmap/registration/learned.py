"""VoxelMorph-style learned deformable registration (ONNX runtime inference).

After rigid MI alignment, a 3-D U-Net looks at the MRI (fixed) and the rigidly aligned PET
(moving) and predicts a stationary velocity field in a single forward pass.  Integrating it
by *scaling and squaring* yields a diffeomorphic (fold-free) displacement — the
VoxelMorph-diff formulation (Dalca et al., 2019).  One pass takes well under a second,
versus tens of iterations for classical B-spline optimisation.

Grid contract (shared with ``training/``): inputs are sampled on a 2 mm canonical grid of
``CROP_SIZE_XYZ`` voxels centred on the head, normalised by the in-head 99th percentile, then
2x2x2 mean-pooled to the 4 mm network grid — PET resolves ~6 mm, so finer grids add cost, not
information.  The network outputs a velocity at half the network resolution (8 mm; VoxelMorph
``int_downsize=2``), channel order ``(dz, dy, dx)`` in those voxels; after integration the
displacement is upsampled to the 4 mm network grid, where it defines the transform.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from scipy import ndimage as ndi

from .. import imaging as im
from .classical import RegistrationResult, compose_with_field

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
VXM_ONNX = MODEL_DIR / "voxelmorph.onnx"
CROP_SPACING = 2.0
CROP_SIZE_XYZ = (96, 112, 96)
NET_POOL = 2  # 2 mm sampling -> 4 mm network grid (48 x 56 x 48, divisible by 8)
NET_SPACING = CROP_SPACING * NET_POOL
NET_SIZE_ZYX = tuple(s // NET_POOL for s in CROP_SIZE_XYZ[::-1])
INT_STEPS = 7


def available(path: Path = VXM_ONNX) -> bool:
    return Path(path).exists()


def model_card(path: Path = VXM_ONNX) -> dict | None:
    meta = path.with_suffix(".json")
    return json.loads(meta.read_text()) if meta.exists() else None


def is_beneficial(path: Path = VXM_ONNX) -> bool:
    """Only let 'auto' use the network if its held-out validation beat rigid-only alignment."""
    card = model_card(path)
    if not available(path) or not card:
        return False
    v = card.get("validation", {})
    try:
        return float(v["residual_error_voxelmorph_mm"]) < float(v["residual_error_rigid_only_mm"]) - 0.02
    except (KeyError, TypeError, ValueError):
        return False


def crop_grid(mri: sitk.Image, head_mask: np.ndarray) -> sitk.Image:
    com_zyx = ndi.center_of_mass(head_mask) if np.any(head_mask) else [(s - 1) / 2 for s in head_mask.shape]
    center = np.array(mri.TransformContinuousIndexToPhysicalPoint(tuple(float(v) for v in com_zyx[::-1])))
    size = np.array(CROP_SIZE_XYZ)
    origin = center - (size - 1) * CROP_SPACING / 2.0
    return im.empty_like_grid(origin, (CROP_SPACING,) * 3, size)


def normalise(a: np.ndarray, mask: np.ndarray) -> np.ndarray:
    sel = mask if np.any(mask) else a > 0
    s = float(np.percentile(a[sel], 99.0)) if np.any(sel) else 1.0
    return np.clip(a / max(s, 1e-6), 0, 2.0).astype(np.float32)


def network_inputs(mri: sitk.Image, pet: sitk.Image, rigid: sitk.Transform, grid: sitk.Image,
                   head_mask: np.ndarray) -> np.ndarray:
    fixed = im.arr(im.resample(mri, grid))
    moving = im.arr(im.resample(pet, grid, rigid))
    mask_img = im.like(head_mask.astype(np.uint8), mri, np.uint8)
    head = im.arr(sitk.Resample(mask_img, grid, sitk.Transform(), sitk.sitkNearestNeighbor, 0)) > 0
    return np.stack([normalise(fixed, head), normalise(moving, head)], 0)[None]


def pool(x: np.ndarray, f: int = NET_POOL) -> np.ndarray:
    """Block-mean pooling of the trailing three axes by ``f``."""
    *lead, Z, Y, X = x.shape
    return x.reshape(*lead, Z // f, f, Y // f, f, X // f, f).mean(axis=(-5, -3, -1))


def net_grid(crop: sitk.Image) -> sitk.Image:
    """The 4 mm grid whose voxel centres are the centres of the 2x2x2 pooled blocks."""
    origin = np.array(crop.GetOrigin()) + (NET_POOL - 1) / 2.0 * CROP_SPACING
    return im.empty_like_grid(origin, (NET_SPACING,) * 3, NET_SIZE_ZYX[::-1])


def integrate_velocity(vel_zyx: np.ndarray, steps: int = INT_STEPS) -> np.ndarray:
    """Scaling and squaring of a stationary velocity field ``[3, Z, Y, X]`` (voxel units)."""
    disp = vel_zyx.astype(np.float32) / (2.0**steps)
    grid = np.indices(disp.shape[1:], dtype=np.float32)
    for _ in range(steps):
        coords = grid + disp
        disp = disp + np.stack(
            [ndi.map_coordinates(disp[c], coords, order=1, mode="nearest") for c in range(3)], 0)
    return disp


def upsample_displacement(disp_half: np.ndarray, full_zyx) -> np.ndarray:
    """Half-resolution displacement (voxels) -> full grid, matching ``align_corners=True``."""
    half = disp_half.shape[1:]
    axes = [np.arange(f, dtype=np.float32) * (h - 1) / (f - 1) for f, h in zip(full_zyx, half)]
    coords = np.stack(np.meshgrid(*axes, indexing="ij"), 0)
    scale = [(f - 1) / (h - 1) for f, h in zip(full_zyx, half)]
    return np.stack([ndi.map_coordinates(disp_half[c], coords, order=1, mode="nearest") * scale[c]
                     for c in range(3)], 0)


def field_to_mm_xyz(disp_zyx_vox: np.ndarray, spacing: float = NET_SPACING) -> np.ndarray:
    """``[3, Z, Y, X]`` voxels (z, y, x)  ->  ``[Z, Y, X, 3]`` millimetres (x, y, z)."""
    return np.moveaxis(disp_zyx_vox[::-1], 0, -1).astype(np.float64) * spacing


@lru_cache(maxsize=2)
def _session(path: str):
    import onnxruntime as ort

    return ort.InferenceSession(path, providers=["CPUExecutionProvider"])


def register_voxelmorph(
    mri: sitk.Image,
    pet: sitk.Image,
    rigid: sitk.Transform,
    head_mask: np.ndarray,
    model_path: Path = VXM_ONNX,
    progress: Callable[[float, str], None] | None = None,
) -> RegistrationResult:
    if not available(model_path):
        raise FileNotFoundError(f"VoxelMorph model not found: {model_path} (run training/train_voxelmorph.py)")
    t0 = time.perf_counter()
    grid = crop_grid(mri, head_mask)
    x = pool(network_inputs(mri, pet, rigid, grid, head_mask)).astype(np.float32)
    if progress:
        progress(0.3, "VoxelMorph forward pass")
    vel = _session(str(model_path)).run(None, {"x": x})[0][0]
    if progress:
        progress(0.7, "integrating velocity field (scaling & squaring)")
    disp = upsample_displacement(integrate_velocity(vel), NET_SIZE_ZYX)
    field = field_to_mm_xyz(disp)
    tx = compose_with_field(rigid, field, net_grid(grid))
    mag = np.linalg.norm(field, axis=-1)
    jac = _min_jacobian(disp)
    return RegistrationResult(
        tx, "rigid-mi+voxelmorph", time.perf_counter() - t0, [],
        {"max_displacement_mm": float(mag.max()), "mean_displacement_mm": float(mag.mean()),
         "min_jacobian": jac, "folding_fraction": 0.0 if jac > 0 else None},
    )


def _min_jacobian(disp_zyx: np.ndarray) -> float:
    """Minimum Jacobian determinant of ``x + u(x)`` (> 0 everywhere means no folding)."""
    grads = [np.gradient(disp_zyx[c]) for c in range(3)]
    J = np.empty(disp_zyx.shape[1:] + (3, 3), np.float32)
    for i in range(3):
        for j in range(3):
            J[..., i, j] = grads[i][j] + (1.0 if i == j else 0.0)
    return float(np.linalg.det(J).min())
