"""Validation metrics against phantom ground truth.

Image-quality metrics match those used in the MRI->PET synthesis literature (SSIM, PSNR,
MAE — Chen et al., 2025; Plasma CycleGAN, 2024) so numbers are comparable in kind, plus the
quantities that matter clinically: lesion SUVmax recovery, detection, and *hallucination*
(false uptake created inside PET-negative, MRI-visible lesions).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage as ndi
from skimage.metrics import structural_similarity

from .phantom import Lesion


def psnr(est: np.ndarray, truth: np.ndarray, mask: np.ndarray) -> float:
    peak = float(truth[mask].max())
    mse = float(((est - truth)[mask] ** 2).mean())
    return 10 * math.log10(peak**2 / max(mse, 1e-12))


def nmae(est: np.ndarray, truth: np.ndarray, mask: np.ndarray) -> float:
    """Mean absolute error normalised by the truth's in-mask maximum (0 = perfect)."""
    return float(np.abs(est - truth)[mask].mean() / max(float(truth[mask].max()), 1e-6))


def ssim_slices(est: np.ndarray, truth: np.ndarray, mask: np.ndarray, step: int = 2) -> float:
    """Mean 2-D SSIM over axial slices that contain the mask (every ``step``-th)."""
    rng = float(truth[mask].max() - truth[mask].min())
    zs = np.where(mask.any((1, 2)))[0][::step]
    if len(zs) == 0:
        return float("nan")
    ys, xs = np.where(mask.any(0))
    sl = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
    vals = [structural_similarity(truth[k][sl], est[k][sl], data_range=rng) for k in zs]
    return float(np.mean(vals))


def lesion_recovery(est: np.ndarray, truth: np.ndarray, labels: np.ndarray, lesions: list[Lesion]) -> list[dict]:
    """Per-lesion SUVmax recovery coefficient (measured max / true max) for PET-positive lesions."""
    out = []
    for les in lesions:
        if les.kind == "mri_only":
            continue
        m = labels == les.id
        if not np.any(m):
            continue
        m2 = ndi.binary_dilation(m, iterations=2)
        t = float(truth[m].max())
        out.append({"id": les.id, "kind": les.kind, "suv_true": round(t, 3),
                    "suv_measured": round(float(est[m2].max()), 3),
                    "rc": round(float(est[m2].max()) / t, 4), "volume_ml": les.volume_ml})
    return out


def hallucination(est: np.ndarray, truth: np.ndarray, labels: np.ndarray, lesions: list[Lesion]) -> list[dict]:
    """Uptake inside PET-negative (MRI-only) lesions relative to the truth (1.0 = faithful)."""
    out = []
    for les in lesions:
        if les.kind != "mri_only":
            continue
        m = labels == les.id
        if not np.any(m):
            continue
        out.append({"id": les.id, "suv_true_mean": round(float(truth[m].mean()), 3),
                    "suv_measured_mean": round(float(est[m].mean()), 3),
                    "ratio": round(float(est[m].mean()) / max(float(truth[m].mean()), 1e-6), 4)})
    return out


def image_quality(est: np.ndarray, truth: np.ndarray, mask: np.ndarray) -> dict:
    return {"psnr_db": round(psnr(est, truth, mask), 3), "ssim": round(ssim_slices(est, truth, mask), 4),
            "nmae": round(nmae(est, truth, mask), 5)}


def detection(hotspots: list[dict], hotspot_labels: np.ndarray, truth_labels: np.ndarray, lesions: list[Lesion],
              spacing_mm: float) -> dict:
    """Match detected hotspots to PET-positive truth lesions."""
    positives = [les for les in lesions if les.kind != "mri_only"]
    matched, dice, loc = set(), [], []
    hits = 0
    for les in positives:
        tm = truth_labels == les.id
        if not np.any(tm):
            continue
        overl = hotspot_labels[tm]
        ids = [int(i) for i in np.unique(overl) if i > 0]
        if not ids:
            continue
        hits += 1
        hid = max(ids, key=lambda i: int((overl == i).sum()))
        matched.add(hid)
        hm = hotspot_labels == hid
        dice.append(2 * float((hm & tm).sum()) / float(hm.sum() + tm.sum()))
        c1 = np.array(ndi.center_of_mass(hm))
        c2 = np.array(ndi.center_of_mass(tm))
        loc.append(float(np.linalg.norm((c1 - c2) * spacing_mm)))
    fp = [h["id"] for h in hotspots if h["id"] not in matched]
    return {
        "pet_positive_lesions": len(positives),
        "detected": hits,
        "sensitivity": round(hits / len(positives), 4) if positives else None,
        "false_positives": len(fp),
        "mean_dice": round(float(np.mean(dice)), 4) if dice else None,
        "mean_centroid_error_mm": round(float(np.mean(loc)), 3) if loc else None,
    }
