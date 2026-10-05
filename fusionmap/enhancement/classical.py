"""Classical PET sharpening baseline: Richardson-Lucy deconvolution + MRI-guided filtering.

PET images are blurred by the scanner point-spread function (~4-7 mm FWHM), which spills
activity out of small lesions ("partial-volume effect") and under-reports their SUVmax.
Deconvolving with the known PSF restores contrast but amplifies noise, so the result is
smoothed with an edge-preserving guided filter that takes its edges from the MRI.
"""

from __future__ import annotations

import numpy as np
import SimpleITK as sitk
from scipy import ndimage as ndi

from .. import imaging as im


def richardson_lucy(pet: sitk.Image, fwhm_mm: float = 5.0, iterations: int = 8,
                    mask: np.ndarray | None = None) -> sitk.Image:
    """Damped Richardson-Lucy deconvolution with a Gaussian PSF (values stay >= 0)."""
    obs = np.clip(im.arr(pet), 0, None)
    sel = mask if mask is not None and np.any(mask) else obs > 0
    peak = float(np.percentile(obs[sel], 99.9)) if np.any(sel) else float(obs.max() or 1.0)
    eps = 1e-3 * peak

    def blur(a):
        return im.arr(im.gaussian_fwhm(im.like(a, pet), fwhm_mm))

    est = obs + eps
    for _ in range(int(iterations)):
        ratio = np.clip(obs / (blur(est) + eps), 0.2, 5.0)  # damping keeps noise from exploding
        est = est * blur(ratio)
    return im.like(est.astype(np.float32), pet)


def guided_filter(src: np.ndarray, guide: np.ndarray, radius: int = 2, eps: float = 1e-3) -> np.ndarray:
    """He et al. guided filter in 3-D (box windows of side ``2r+1``)."""
    size = 2 * int(radius) + 1

    def box(x):
        return ndi.uniform_filter(x, size=size, mode="nearest")

    g = guide.astype(np.float32)
    p = src.astype(np.float32)
    mean_g, mean_p = box(g), box(p)
    cov_gp = box(g * p) - mean_g * mean_p
    var_g = box(g * g) - mean_g**2
    a = cov_gp / (var_g + eps)
    b = mean_p - a * mean_g
    return box(a) * g + box(b)


def enhance_deconv(
    pet_in_mri: sitk.Image,
    mri: sitk.Image,
    head_mask: np.ndarray | None = None,
    fwhm_mm: float = 6.0,
    iterations: int = 8,
) -> sitk.Image:
    """PSF deconvolution followed by MRI-guided denoising; returns SUV on the MRI grid.

    ``fwhm_mm`` is the scanner resolution; the deconvolution kernel is damped to 85 % of it
    because noise makes full-width deconvolution overshoot lesion SUVmax.
    """
    rl = im.arr(richardson_lucy(pet_in_mri, 0.85 * fwhm_mm, iterations, head_mask))
    m = im.arr(mri)
    lo, hi = im.robust_range(m, head_mask)
    guide = np.clip((m - lo) / (hi - lo + 1e-6), 0, 1.5)
    sel = head_mask if head_mask is not None and np.any(head_mask) else rl > 0
    scale = max(float(np.percentile(rl[sel], 99.5)), 1e-6)
    radius = int(round(1.0 / float(np.mean(pet_in_mri.GetSpacing()))))  # ~1 mm half-window, whatever the grid
    out = guided_filter(rl / scale, guide, radius=radius, eps=2e-3) * scale if radius > 0 else rl
    out = np.clip(out, 0, None)
    if head_mask is not None:
        out = np.where(ndi.binary_dilation(head_mask, iterations=3), out, 0.0)
    return im.like(out.astype(np.float32), pet_in_mri)
