"""Clinical read-out of the fused study: PET hotspots with standard nuclear-medicine metrics.

Tumour volumes are defined by a tumour-to-background ratio (TBR) threshold of 1.6, the
RANO/EANO/EANM-recommended biological tumour volume criterion for amino-acid brain PET,
and a reasonable "uptake clearly above normal grey matter" rule for FDG (cf. Wei et al.,
2022).  Each hotspot reports SUVmax, SUVpeak (1 ml sphere), SUVmean, metabolic tumour
volume (MTV), total lesion glycolysis/activity (TLG = SUVmean x MTV), TBRmax and location.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import SimpleITK as sitk
from scipy import ndimage as ndi

from . import imaging as im

TBR_THRESHOLD = 1.6
MIN_VOLUME_ML = 0.15


@dataclass
class Hotspot:
    id: int
    suv_max: float
    suv_peak: float
    suv_mean: float
    mtv_ml: float
    tlg: float
    tbr_max: float
    peak_mm: list[float]
    centroid_mm: list[float]
    peak_index_zyx: list[int]
    side: str
    bbox_zyx: list[list[int]]

    def to_dict(self) -> dict:
        return asdict(self)


def background_level(pet: np.ndarray, head: np.ndarray, spacing_mm: float = 1.0) -> float:
    """Reference uptake of normal tissue: upper-quartile uptake inside the brain envelope."""
    inner = ndi.binary_erosion(head, iterations=max(int(round(14.0 / spacing_mm)), 1))
    sel = inner if inner.sum() > 1000 else head
    vals = pet[sel]
    vals = vals[vals > np.percentile(vals, 20)]
    return float(np.percentile(vals, 75)) if vals.size else 1.0


def find_hotspots(pet_img: sitk.Image, head: np.ndarray, tbr: float = TBR_THRESHOLD,
                  min_ml: float = MIN_VOLUME_ML, max_spots: int = 12) -> tuple[list[Hotspot], np.ndarray, float]:
    """Detect PET hotspots on the MRI grid. Returns hotspots, a label volume and the background."""
    pet = im.arr(pet_img)
    sp = np.array(pet_img.GetSpacing())
    vml = im.voxel_volume_ml(pet_img)
    bg = background_level(pet, head, float(sp.mean()))
    inner = ndi.binary_erosion(head, iterations=max(int(round(10.0 / sp.mean())), 1))
    cand = (pet >= tbr * bg) & inner
    lab, n = ndi.label(cand, structure=np.ones((3, 3, 3)))
    spots: list[Hotspot] = []
    out = np.zeros(pet.shape, np.uint8)
    if n == 0:
        return spots, out, bg
    sizes = ndi.sum(np.ones_like(pet), lab, index=np.arange(1, n + 1))
    maxes = ndi.maximum(pet, lab, index=np.arange(1, n + 1))
    order = np.argsort(-np.asarray(maxes))
    midline_x = float(im.index_to_mm(pet_img, ndi.center_of_mass(head))[0])
    r_peak = (3.0 / (4 * np.pi)) ** (1 / 3) * 10.0  # radius (mm) of a 1 ml sphere = 6.2 mm
    for rank in order:
        cid = int(rank) + 1
        if sizes[rank] * vml < min_ml:
            continue
        sel = lab == cid
        sl = ndi.find_objects(sel.astype(np.uint8))[0]
        vals = pet[sel]
        peak_local = np.unravel_index(np.argmax(np.where(sel[sl], pet[sl], -np.inf)), pet[sl].shape)
        peak_idx = [int(p + s.start) for p, s in zip(peak_local, sl)]
        suv_peak = _sphere_mean(pet, peak_idx, r_peak, sp)
        mtv = float(sel.sum() * vml)
        mean = float(vals.mean())
        com = ndi.center_of_mass(sel)
        centroid = im.index_to_mm(pet_img, com)
        peak_mm = im.index_to_mm(pet_img, peak_idx)
        side = "left" if centroid[0] > midline_x + 3 else ("right" if centroid[0] < midline_x - 3 else "midline")
        hid = len(spots) + 1
        out[sel] = hid
        spots.append(Hotspot(
            id=hid, suv_max=round(float(vals.max()), 3), suv_peak=round(suv_peak, 3), suv_mean=round(mean, 3),
            mtv_ml=round(mtv, 3), tlg=round(mean * mtv, 3), tbr_max=round(float(vals.max()) / bg, 3),
            peak_mm=[round(v, 2) for v in peak_mm], centroid_mm=[round(v, 2) for v in centroid],
            peak_index_zyx=peak_idx, side=side, bbox_zyx=[[s.start, s.stop] for s in sl]))
        if len(spots) >= max_spots:
            break
    return spots, out, bg


def _sphere_mean(pet: np.ndarray, center_zyx, radius_mm: float, spacing_xyz: np.ndarray) -> float:
    sz, sy, sx = spacing_xyz[::-1]
    rz, ry, rx = (int(np.ceil(radius_mm / s)) for s in (sz, sy, sx))
    z, y, x = center_zyx
    zs = slice(max(z - rz, 0), min(z + rz + 1, pet.shape[0]))
    ys = slice(max(y - ry, 0), min(y + ry + 1, pet.shape[1]))
    xs = slice(max(x - rx, 0), min(x + rx + 1, pet.shape[2]))
    gz, gy, gx = np.meshgrid(np.arange(zs.start, zs.stop) - z, np.arange(ys.start, ys.stop) - y,
                             np.arange(xs.start, xs.stop) - x, indexing="ij")
    m = (gz * sz) ** 2 + (gy * sy) ** 2 + (gx * sx) ** 2 <= radius_mm**2
    return float(pet[zs, ys, xs][m].mean())
