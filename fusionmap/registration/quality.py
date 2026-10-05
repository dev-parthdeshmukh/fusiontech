"""Ground-truth-free alignment quality measures (usable on real patients)."""

from __future__ import annotations

import numpy as np


def normalized_mutual_information(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None,
                                  bins: int = 64) -> float:
    """Studholme NMI = (H(A) + H(B)) / H(A, B); 1 = independent, 2 = identical."""
    if mask is not None:
        a, b = a[mask], b[mask]
    a = a.ravel()
    b = b.ravel()
    if a.size > 400_000:
        idx = np.random.default_rng(0).choice(a.size, 400_000, replace=False)
        a, b = a[idx], b[idx]
    ha, _, _ = np.histogram2d(a, b, bins=bins)
    p = ha / max(ha.sum(), 1)
    pa, pb = p.sum(1), p.sum(0)

    def H(x):
        x = x[x > 0]
        return float(-(x * np.log(x)).sum())

    hab = H(p.ravel())
    return (H(pa) + H(pb)) / hab if hab > 0 else 1.0


def edge_alignment(mri: np.ndarray, pet: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Mean |cos| between MRI and PET gradient directions where both have structure (0..1)."""
    gm = np.stack(np.gradient(mri.astype(np.float32)), 0)
    gp = np.stack(np.gradient(pet.astype(np.float32)), 0)
    nm = np.linalg.norm(gm, axis=0)
    npet = np.linalg.norm(gp, axis=0)
    sel = (nm > np.percentile(nm, 80)) & (npet > np.percentile(npet, 80))
    if mask is not None:
        sel &= mask
    if not np.any(sel):
        return 0.0
    cos = np.abs((gm[:, sel] * gp[:, sel]).sum(0)) / (nm[sel] * npet[sel] + 1e-8)
    return float(cos.mean())
