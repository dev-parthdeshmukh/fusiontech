"""Quantitative validation on held-out digital phantoms.

Seeds start at 1000, disjoint from every training seed, and alternate FDG / FET with a
mix of viable, MRI-occult and PET-negative (radionecrosis) lesions.  For each case every
registration method and every enhancement method is scored against the exact truth.
"""

from __future__ import annotations

import json
import platform
import time
from datetime import date
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from . import __version__
from . import imaging as im
from . import metrics as mt
from .analysis import find_hotspots
from .enhancement import ai as enh_ai
from .enhancement.classical import enhance_deconv
from .phantom import PhantomConfig, make_phantom
from .pipeline import working_grid
from .registration import bspline_mi, rigid_mi
from .registration import learned as vxm

REG_METHODS = ["naive", "rigid", "rigid+bspline", "rigid+voxelmorph"]
ENH_METHODS = ["none", "deconv", "vit"]


def _case(seed: int, spacing: float) -> dict:
    rng = np.random.default_rng(seed)
    cfg = PhantomConfig(seed=seed, tracer="fdg" if seed % 2 == 0 else "fet", lesion_mix="mixed",
                        n_lesions=int(rng.integers(2, 4)), mri_spacing=spacing)
    ph = make_phantom(cfg)
    mri_w, head = working_grid(ph.mri, spacing)
    mask_img = im.like(head.astype(np.uint8), mri_w, np.uint8)
    out: dict = {"seed": seed, "tracer": cfg.tracer, "lesions": [les.kind for les in ph.lesions], "reg": {}, "enh": {}}

    txs: dict[str, sitk.Transform | None] = {"naive": None}
    t = time.perf_counter()
    rr = rigid_mi(mri_w, ph.pet, fixed_mask=mask_img)
    txs["rigid"] = rr.transform
    times = {"naive": 0.0, "rigid": time.perf_counter() - t}
    t = time.perf_counter()
    txs["rigid+bspline"] = bspline_mi(mri_w, ph.pet, rr.transform, fixed_mask=mask_img, grid_spacing_mm=100.0).transform
    times["rigid+bspline"] = times["rigid"] + time.perf_counter() - t
    if vxm.available():
        t = time.perf_counter()
        txs["rigid+voxelmorph"] = vxm.register_voxelmorph(mri_w, ph.pet, rr.transform, head).transform
        times["rigid+voxelmorph"] = times["rigid"] + time.perf_counter() - t
    for k, tx in txs.items():
        tre = ph.tre(tx)
        out["reg"][k] = {"tre_mean_mm": tre["mean_mm"], "tre_p95_mm": tre["p95_mm"], "tre_max_mm": tre["max_mm"],
                         "lesion_tre_mm": float(np.mean(tre["lesion_mm"])) if tre["lesion_mm"] else None,
                         "seconds": round(times[k], 3)}

    best = "rigid+voxelmorph" if "rigid+voxelmorph" in txs else "rigid"
    pet_reg = im.resample(ph.pet, mri_w, txs[best])
    truth = im.arr(im.resample(ph.pet_truth, mri_w))
    labels = im.arr(sitk.Resample(ph.lesion_mask, mri_w, sitk.Transform(), sitk.sitkNearestNeighbor, 0)).astype(np.uint8)
    brain = im.arr(sitk.Resample(ph.brain_mask, mri_w, sitk.Transform(), sitk.sitkNearestNeighbor, 0)) > 0
    enhanced = {"none": pet_reg}
    etimes = {"none": 0.0}
    t = time.perf_counter()
    enhanced["deconv"] = enhance_deconv(pet_reg, mri_w, head, fwhm_mm=cfg.pet_fwhm_mm)
    etimes["deconv"] = time.perf_counter() - t
    if enh_ai.available():
        t = time.perf_counter()
        enhanced["vit"] = enh_ai.enhance_ai(pet_reg, mri_w, head)
        etimes["vit"] = time.perf_counter() - t
    for k, img in enhanced.items():
        a = im.arr(img)
        rc = mt.lesion_recovery(a, truth, labels, ph.lesions)
        hal = mt.hallucination(a, truth, labels, ph.lesions)
        spots, hot, _ = find_hotspots(img, head)
        det = mt.detection([s.to_dict() for s in spots], hot, labels, ph.lesions, spacing)
        out["enh"][k] = {**mt.image_quality(a, truth, brain), "rc": [r["rc"] for r in rc],
                         "hallucination": [h["ratio"] for h in hal], "detection": det,
                         "seconds": round(etimes[k], 3)}
    return out


def _agg(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {"mean": round(float(np.mean(vals)), 4), "std": round(float(np.std(vals)), 4),
            "median": round(float(np.median(vals)), 4), "n": len(vals)}


def summarise(cases: list[dict]) -> dict:
    reg = {}
    for m in REG_METHODS:
        rows = [c["reg"][m] for c in cases if m in c["reg"]]
        if rows:
            reg[m] = {"tre_mean_mm": _agg([r["tre_mean_mm"] for r in rows]),
                      "tre_p95_mm": _agg([r["tre_p95_mm"] for r in rows]),
                      "lesion_tre_mm": _agg([r["lesion_tre_mm"] for r in rows]),
                      "seconds": _agg([r["seconds"] for r in rows]),
                      "cases_under_2mm": round(float(np.mean([r["tre_p95_mm"] < 2.0 for r in rows])), 4)}
    enh = {}
    for m in ENH_METHODS:
        rows = [c["enh"][m] for c in cases if m in c["enh"]]
        if rows:
            rcs = [v for r in rows for v in r["rc"]]
            hal = [v for r in rows for v in r["hallucination"]]
            det = [r["detection"] for r in rows]
            n_pos = sum(d["pet_positive_lesions"] for d in det)
            enh[m] = {"psnr_db": _agg([r["psnr_db"] for r in rows]), "ssim": _agg([r["ssim"] for r in rows]),
                      "nmae": _agg([r["nmae"] for r in rows]), "lesion_rc": _agg(rcs),
                      "lesion_rc_abs_error": _agg([abs(v - 1) for v in rcs]),
                      "hallucination_ratio": _agg(hal),
                      "sensitivity": round(sum(d["detected"] for d in det) / max(n_pos, 1), 4),
                      "false_positives_per_case": round(float(np.mean([d["false_positives"] for d in det])), 3),
                      "seconds": _agg([r["seconds"] for r in rows])}
    return {"registration": reg, "enhancement": enh}


def run_benchmark(n_cases: int = 10, start_seed: int = 1000, out: Path | None = None, spacing: float = 1.0) -> dict:
    cases = []
    t0 = time.perf_counter()
    for i, seed in enumerate(range(start_seed, start_seed + n_cases)):
        t = time.perf_counter()
        cases.append(_case(seed, spacing))
        c = cases[-1]
        print(f"[{i + 1}/{n_cases}] seed {seed} ({c['tracer']}, {c['lesions']}): TRE "
              + " | ".join(f"{k} {v['tre_mean_mm']:.2f}" for k, v in c["reg"].items())
              + "  PSNR " + " | ".join(f"{k} {v['psnr_db']:.2f}" for k, v in c["enh"].items())
              + f"  ({time.perf_counter() - t:.0f}s)", flush=True)
    res = {
        "fusionmap_version": __version__,
        "date": str(date.today()),
        "machine": f"{platform.machine()} / {platform.python_version()}",
        "cases": n_cases,
        "seeds": [start_seed, start_seed + n_cases - 1],
        "grid_mm": spacing,
        "models": {"voxelmorph": vxm.model_card(), "enhancer": enh_ai.model_card()},
        "summary": summarise(cases),
        "per_case": cases,
        "wall_seconds": round(time.perf_counter() - t0, 1),
    }
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=2))
    return res
