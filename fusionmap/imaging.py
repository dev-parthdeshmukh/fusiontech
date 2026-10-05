"""Small, dependable helpers around SimpleITK images.

Conventions used across FusionMap
---------------------------------
* Physical space is DICOM patient space (LPS: +x = patient Left, +y = Posterior, +z = Superior).
* Arrays obtained from SimpleITK are indexed ``[z, y, x]``.
* "Working grid" volumes are canonical: identity direction cosines, LPS-aligned axes,
  so ``array[k, j, i]`` sits at ``origin + (i, j, k) * spacing``.
"""

from __future__ import annotations

import numpy as np
import SimpleITK as sitk
from scipy import ndimage as ndi


def arr(img: sitk.Image) -> np.ndarray:
    """Copy of the voxel data as a float32 ``[z, y, x]`` array."""
    return sitk.GetArrayFromImage(img).astype(np.float32, copy=False)


def like(a: np.ndarray, reference: sitk.Image, dtype=None) -> sitk.Image:
    """Wrap ``a`` as an image with the geometry of ``reference``."""
    if dtype is not None:
        a = a.astype(dtype, copy=False)
    out = sitk.GetImageFromArray(a)
    out.CopyInformation(reference)
    return out


def to_float(img: sitk.Image) -> sitk.Image:
    return sitk.Cast(img, sitk.sitkFloat32)


def canonical(img: sitk.Image) -> sitk.Image:
    """Reorient so the array axes are aligned with LPS (no voxel resampling)."""
    img = to_float(img)
    if img.GetDimension() != 3:
        raise ValueError(f"expected a 3-D volume, got {img.GetDimension()}-D")
    try:
        return sitk.DICOMOrient(img, "LPS")
    except RuntimeError:  # oblique acquisitions: keep geometry, resampling handles it
        return img


def resample(
    img: sitk.Image,
    reference: sitk.Image,
    transform: sitk.Transform | None = None,
    interpolator: int = sitk.sitkLinear,
    default: float = 0.0,
) -> sitk.Image:
    """Resample ``img`` onto ``reference``.

    ``transform`` maps *reference* physical points to *img* physical points (ITK convention).
    """
    tx = transform if transform is not None else sitk.Transform(3, sitk.sitkIdentity)
    return sitk.Resample(img, reference, tx, interpolator, default, sitk.sitkFloat32)


def empty_like_grid(origin, spacing, size) -> sitk.Image:
    ref = sitk.Image([int(s) for s in size], sitk.sitkFloat32)
    ref.SetOrigin([float(o) for o in origin])
    ref.SetSpacing([float(s) for s in spacing])
    ref.SetDirection((1, 0, 0, 0, 1, 0, 0, 0, 1))
    return ref


def physical_bounds(img: sitk.Image) -> tuple[np.ndarray, np.ndarray]:
    """Axis-aligned physical bounding box of the voxel centres of ``img``."""
    size = np.array(img.GetSize())
    corners = []
    for cx in (0, size[0] - 1):
        for cy in (0, size[1] - 1):
            for cz in (0, size[2] - 1):
                corners.append(img.TransformContinuousIndexToPhysicalPoint((float(cx), float(cy), float(cz))))
    c = np.array(corners)
    return c.min(0), c.max(0)


def isotropic_reference(img: sitk.Image, spacing: float = 1.0, max_voxels: int = 24_000_000) -> sitk.Image:
    """Canonical (identity-direction) grid with isotropic spacing covering ``img``."""
    lo, hi = physical_bounds(img)
    extent = hi - lo
    while True:
        size = np.maximum(np.ceil(extent / spacing).astype(int) + 1, 1)
        if np.prod(size) <= max_voxels:
            break
        spacing *= 1.15
    return empty_like_grid(lo, (spacing,) * 3, size)


def gaussian_fwhm(img: sitk.Image, fwhm_mm: float) -> sitk.Image:
    if fwhm_mm <= 0:
        return img
    sigma = float(fwhm_mm) / 2.3548
    return sitk.SmoothingRecursiveGaussian(to_float(img), sigma)


def robust_range(a: np.ndarray, mask: np.ndarray | None = None, lo: float = 0.5, hi: float = 99.5):
    vals = a[mask > 0] if mask is not None and np.any(mask) else a[a > 0] if np.any(a > 0) else a.ravel()
    if vals.size == 0:
        return 0.0, 1.0
    p_lo, p_hi = np.percentile(vals, [lo, hi])
    if p_hi <= p_lo:
        p_hi = p_lo + 1e-6
    return float(p_lo), float(p_hi)


def largest_component(mask: np.ndarray) -> np.ndarray:
    lab, n = ndi.label(mask)
    if n <= 1:
        return mask.astype(bool)
    counts = np.bincount(lab.ravel())
    counts[0] = 0
    return lab == int(np.argmax(counts))


def foreground_mask(img: sitk.Image, closing_mm: float = 4.0) -> np.ndarray:
    """Head/body mask from an MRI or PET volume (Otsu + morphology + hole filling)."""
    a = arr(img)
    if not np.any(a > 0):
        return np.zeros(a.shape, bool)
    sm = arr(sitk.SmoothingRecursiveGaussian(to_float(img), float(np.mean(img.GetSpacing()))))
    lo, hi = robust_range(sm, lo=1, hi=99.5)
    clipped = np.clip(sm, lo, hi)
    thr = _otsu(clipped[clipped > lo]) if np.any(clipped > lo) else hi * 0.1
    m = like((sm > max(thr * 0.5, lo)).astype(np.uint8), img, np.uint8)
    radius = [max(int(round(closing_mm / s)), 1) for s in img.GetSpacing()]
    m = sitk.BinaryMorphologicalClosing(m, radius, sitk.sitkBall)  # multi-threaded
    m = sitk.RelabelComponent(sitk.ConnectedComponent(m), sortByObjectSize=True) == 1
    m = sitk.GetArrayFromImage(sitk.BinaryFillhole(m)).astype(bool)
    for k in range(m.shape[0]):  # slice-wise fill closes the open bottom of a head
        m[k] = ndi.binary_fill_holes(m[k])
    return m


def _otsu(values: np.ndarray, bins: int = 256) -> float:
    hist, edges = np.histogram(values, bins=bins)
    hist = hist.astype(np.float64)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers) / np.maximum(w0, 1e-12)
    m1 = (np.sum(hist * centers) - np.cumsum(hist * centers)) / np.maximum(w1, 1e-12)
    between = w0 * w1 * (m0 - m1) ** 2
    return float(centers[int(np.argmax(between))])


def bbox(mask: np.ndarray, margin: int = 0) -> tuple[slice, slice, slice]:
    idx = np.argwhere(mask)
    if idx.size == 0:
        return tuple(slice(0, s) for s in mask.shape)  # type: ignore[return-value]
    lo = np.maximum(idx.min(0) - margin, 0)
    hi = np.minimum(idx.max(0) + margin + 1, mask.shape)
    return tuple(slice(int(a), int(b)) for a, b in zip(lo, hi))  # type: ignore[return-value]


def crop(img: sitk.Image, sl: tuple[slice, slice, slice]) -> sitk.Image:
    """Crop with ``[z, y, x]`` slices, preserving physical geometry."""
    zs, ys, xs = sl
    index = [xs.start, ys.start, zs.start]
    size = [xs.stop - xs.start, ys.stop - ys.start, zs.stop - zs.start]
    return sitk.RegionOfInterest(img, size, index)


def mm_to_index(img: sitk.Image, point_mm) -> tuple[int, int, int]:
    """Physical point -> nearest ``(z, y, x)`` array index."""
    i, j, k = img.TransformPhysicalPointToIndex([float(v) for v in point_mm])
    return int(k), int(j), int(i)


def index_to_mm(img: sitk.Image, zyx) -> list[float]:
    z, y, x = (float(v) for v in zyx)
    return list(img.TransformContinuousIndexToPhysicalPoint((x, y, z)))


def voxel_volume_ml(img: sitk.Image) -> float:
    return float(np.prod(img.GetSpacing())) / 1000.0
