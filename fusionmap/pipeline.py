"""The FusionMap pipeline: load -> register -> enhance -> fuse & analyse -> export -> validate."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from . import DISCLAIMER, __version__
from . import imaging as im
from . import metrics as mt
from .analysis import TBR_THRESHOLD, find_hotspots
from .enhancement import ai as enh_ai
from .enhancement.classical import enhance_deconv
from .export.dicom import export_bundle
from .fusion import FusionSettings, auto_mri_window, fuse
from .io import Scan, summarize_image
from .phantom import Phantom
from .registration import bspline_mi, normalized_mutual_information, rigid_mi, transform_to_dict
from .registration import edge_alignment as edge_score
from .registration import learned as vxm
from .viewer import mip_sprite, write_labels, write_manifest, write_u8

STEPS = [
    ("load", "Load & standardise"),
    ("register", "Register PET to MRI"),
    ("enhance", "Enhance PET"),
    ("fuse", "Fuse & analyse"),
    ("export", "Export DICOM"),
    ("validate", "Validate vs ground truth"),
]

Emit = Callable[[dict], None]


@dataclass
class PipelineOptions:
    registration: str = "auto"  # auto | rigid | rigid+bspline | rigid+voxelmorph | none
    enhancement: str = "auto"  # auto | vit | deconv | none
    colormap: str = "hot"
    pet_fwhm_mm: float = 6.0
    working_spacing_mm: float = 1.0
    export_dicom: bool = True
    tracer: str | None = None

    @classmethod
    def from_dict(cls, d: dict | None) -> PipelineOptions:
        d = d or {}
        keys = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in keys and v is not None})

    def resolved_registration(self) -> str:
        if self.registration == "auto":
            return "rigid+voxelmorph" if vxm.available() else "rigid+bspline"
        return self.registration

    def resolved_enhancement(self) -> str:
        if self.enhancement == "auto":
            return "vit" if enh_ai.available() else "deconv"
        return self.enhancement


class Reporter:
    def __init__(self, emit: Emit | None):
        self.emit = emit or (lambda e: None)
        self.t0 = time.perf_counter()
        self.timings: dict[str, float] = {}

    @contextmanager
    def step(self, name: str):
        label = dict(STEPS).get(name, name)
        t = time.perf_counter()
        self.emit({"type": "step", "step": name, "label": label, "status": "running", "progress": 0.0})
        try:
            yield lambda frac, msg="": self.emit({"type": "progress", "step": name, "progress": float(frac),
                                                  "message": msg})
        except Exception as e:
            self.emit({"type": "step", "step": name, "label": label, "status": "error", "message": str(e)})
            raise
        dt = time.perf_counter() - t
        self.timings[name] = round(dt, 3)
        self.emit({"type": "step", "step": name, "label": label, "status": "done", "progress": 1.0,
                   "seconds": round(dt, 3)})

    def skip(self, name: str, why: str):
        self.emit({"type": "step", "step": name, "label": dict(STEPS).get(name, name), "status": "skipped",
                   "message": why})


def working_grid(mri: sitk.Image, spacing: float) -> tuple[sitk.Image, np.ndarray]:
    """MRI resampled to an isotropic canonical grid and cropped to the head (+4 mm)."""
    sp = np.array(mri.GetSpacing())
    identity = np.allclose(np.array(mri.GetDirection()), np.eye(3).ravel(), atol=1e-4)
    iso = mri if (identity and np.allclose(sp, spacing, rtol=0.02)) else im.resample(
        mri, im.isotropic_reference(mri, spacing), interpolator=sitk.sitkBSpline)
    iso = sitk.Clamp(im.to_float(iso), lowerBound=0.0)
    head = im.foreground_mask(iso)
    sl = im.bbox(head, margin=int(round(4.0 / spacing)))
    return im.crop(iso, sl), head[sl]


def run_pipeline(case_dir: Path, mri_scan: Scan, pet_scan: Scan, opts: PipelineOptions | None = None,
                 emit: Emit | None = None, phantom: Phantom | None = None) -> dict:
    opts = opts or PipelineOptions()
    case_dir = Path(case_dir)
    work, viewer, exports = (case_dir / d for d in ("work", "viewer", "exports"))
    for d in (work, viewer, exports):
        d.mkdir(parents=True, exist_ok=True)
    R = Reporter(emit)
    report: dict = {"version": __version__, "disclaimer": DISCLAIMER, "options": asdict(opts)}
    tracer = opts.tracer or (phantom.config.tracer if phantom else None)

    # 1 ── load & standardise ───────────────────────────────────────────────────────────
    with R.step("load") as p:
        mri = im.canonical(mri_scan.image)
        pet = im.canonical(pet_scan.image)
        p(0.3, "resampling MRI to the 1 mm fusion grid")
        mri_w, head = working_grid(mri, opts.working_spacing_mm)
        p(0.7, "naive overlay (scanner coordinates)")
        pet_naive = im.resample(pet, mri_w)
        mri_a, naive_a = im.arr(mri_w), im.arr(pet_naive)
        report["inputs"] = {"mri": {**summarize_image(mri), "meta": mri_scan.meta.to_dict()},
                            "pet": {**summarize_image(pet), "meta": pet_scan.meta.to_dict()},
                            "fusion_grid": summarize_image(mri_w)}
        sitk.WriteImage(mri_w, str(work / "mri.nii.gz"))

    # 2 ── register ─────────────────────────────────────────────────────────────────────
    method = opts.resolved_registration()
    reg: dict = {"method": method}
    mask_img = im.like(head.astype(np.uint8), mri_w, np.uint8)
    with R.step("register") as p:
        if method == "none":
            final_tx: sitk.Transform = sitk.Transform(3, sitk.sitkIdentity)
            rigid_tx = final_tx
        else:
            p(0.02, "moments initialisation + rigid mutual information")
            rr = rigid_mi(mri_w, pet, fixed_mask=mask_img, progress=lambda f, m: p(0.6 * f, m))
            rigid_tx = final_tx = rr.transform
            reg["rigid"] = {"seconds": round(rr.seconds, 3), **rr.params, **transform_to_dict(rr.transform)}
            reg["mi_trace"] = [round(v, 5) for v in rr.metric_trace[:: max(1, len(rr.metric_trace) // 120)]]
            if method == "rigid+voxelmorph":
                p(0.65, "VoxelMorph deformable refinement")
                dr = vxm.register_voxelmorph(mri_w, pet, rr.transform, head, progress=lambda f, m: p(0.65 + 0.3 * f, m))
                final_tx = dr.transform
                reg["deformable"] = {"model": "VoxelMorph-diff (ONNX)", "seconds": round(dr.seconds, 3), **dr.params}
            elif method == "rigid+bspline":
                p(0.65, "B-spline mutual-information refinement")
                dr = bspline_mi(mri_w, pet, rr.transform, fixed_mask=mask_img, grid_spacing_mm=100.0,
                                progress=lambda f, m: p(0.65 + 0.3 * f, m))
                final_tx = dr.transform
                reg["deformable"] = {"model": "B-spline FFD (100 mm grid)", "seconds": round(dr.seconds, 3),
                                     **dr.params}
        pet_reg = im.resample(pet, mri_w, final_tx)
        reg_a = im.arr(pet_reg)
        reg["nmi_before"] = round(normalized_mutual_information(mri_a, naive_a, head), 5)
        reg["nmi_after"] = round(normalized_mutual_information(mri_a, reg_a, head), 5)
        reg["edge_alignment_before"] = round(edge_score(mri_a, naive_a, head), 4)
        reg["edge_alignment_after"] = round(edge_score(mri_a, reg_a, head), 4)
        try:
            sitk.WriteTransform(final_tx, str(work / "transform.h5"))
        except RuntimeError:
            pass
        sitk.WriteImage(pet_reg, str(work / "pet_registered.nii.gz"))
    report["registration"] = reg

    # 3 ── enhance ──────────────────────────────────────────────────────────────────────
    emethod = opts.resolved_enhancement()
    enh: dict = {"method": emethod}
    if emethod == "none":
        R.skip("enhance", "enhancement disabled")
        enh_img = pet_reg
    else:
        with R.step("enhance") as p:
            t = time.perf_counter()
            if emethod == "vit":
                enh_img = enh_ai.enhance_ai(pet_reg, mri_w, head, progress=p)
                card = enh_ai.model_card()
                enh["model"] = card.get("name") if card else "HybridViTUNet"
            else:
                p(0.1, f"Richardson-Lucy deconvolution (PSF {opts.pet_fwhm_mm:.1f} mm) + MRI-guided filter")
                enh_img = enhance_deconv(pet_reg, mri_w, head, fwhm_mm=opts.pet_fwhm_mm)
            enh["seconds"] = round(time.perf_counter() - t, 3)
            sitk.WriteImage(enh_img, str(work / "pet_enhanced.nii.gz"))
    enh_a = im.arr(enh_img)
    report["enhancement"] = enh

    # 4 ── fuse & analyse ───────────────────────────────────────────────────────────────
    with R.step("fuse") as p:
        p(0.1, f"hotspot detection (TBR >= {TBR_THRESHOLD})")
        spots, hot_labels, bg = find_hotspots(enh_img, head)
        top = max([s.suv_max for s in spots] + [float(np.percentile(enh_a[head], 99.9))])
        thr = bg * 1.15
        settings = FusionSettings(colormap=opts.colormap, pet_range=(thr, top), opacity=0.8,
                                  mri_window=auto_mri_window(mri_a, head))
        p(0.4, "colour fusion")
        rgb = fuse(mri_a, enh_a, settings, head)
        p(0.6, "viewer volumes + rotating MIP")
        pet_hi = float(max(top, np.percentile(reg_a[head], 99.95), np.percentile(naive_a[head], 99.95)))
        lo_m, hi_m = settings.mri_window
        vols = {
            "mri": {**write_u8(viewer / "mri.u8.gz", mri_a, lo_m, hi_m), "kind": "mri"},
            "pet_naive": {**write_u8(viewer / "pet_naive.u8.gz", naive_a, 0.0, pet_hi), "kind": "pet"},
            "pet_registered": {**write_u8(viewer / "pet_registered.u8.gz", reg_a, 0.0, pet_hi), "kind": "pet"},
            "pet_enhanced": {**write_u8(viewer / "pet_enhanced.u8.gz", enh_a, 0.0, pet_hi), "kind": "pet"},
            "hotspots": {**write_labels(viewer / "hotspots.u8.gz", hot_labels), "kind": "labels"},
        }
        mip = mip_sprite(enh_a, opts.working_spacing_mm, viewer / "mip.png", colormap=opts.colormap, vmax=top, threshold=thr)
        sitk.WriteImage(im.like(hot_labels, mri_w, np.uint8), str(work / "hotspots.nii.gz"))
        report["analysis"] = {"background_suv": round(bg, 4), "tbr_threshold": TBR_THRESHOLD,
                              "display": {"pet_threshold": round(thr, 4), "pet_max": round(top, 4)},
                              "hotspots": [s.to_dict() for s in spots]}

    # 5 ── export ───────────────────────────────────────────────────────────────────────
    if opts.export_dicom:
        with R.step("export") as p:
            p(0.1, "writing MR, PET, fused RGB and RT-STRUCT series")
            manifest = export_bundle(exports / "fusionmap_dicom.zip", mri_w, mri_a, reg_a,
                                     enh_a if emethod != "none" else None, rgb, hot_labels, mri_scan.meta, tracer)
            sitk.WriteImage(enh_img, str(exports / "pet_fused_grid.nii.gz"))
            sitk.WriteImage(mri_w, str(exports / "mri_fused_grid.nii.gz"))
            report["export"] = manifest
    else:
        R.skip("export", "DICOM export disabled")

    # 6 ── validate against phantom ground truth ────────────────────────────────────────
    truth_vols = {}
    if phantom is not None:
        with R.step("validate") as p:
            report["validation"] = validate(phantom, mri_w, rigid_tx, final_tx, reg_a, enh_a, emethod, spots,
                                            hot_labels, p)
            tr = im.arr(im.resample(phantom.pet_truth, mri_w))
            truth_vols["truth_pet"] = {**write_u8(viewer / "truth_pet.u8.gz", tr, 0.0, pet_hi), "kind": "pet"}
            lab = im.arr(sitk.Resample(phantom.lesion_mask, mri_w, sitk.Transform(), sitk.sitkNearestNeighbor, 0))
            truth_vols["truth_lesions"] = {**write_labels(viewer / "truth_lesions.u8.gz", lab), "kind": "labels"}
    else:
        R.skip("validate", "no ground truth for real patients — see GT-free QA metrics")

    write_manifest(viewer, mri_w, {**vols, **truth_vols}, {"mip": mip, "colormap": opts.colormap})
    report["timings_s"] = R.timings
    report["total_seconds"] = round(time.perf_counter() - R.t0, 3)
    (case_dir / "report.json").write_text(json.dumps(report, indent=2, default=_json_default))
    R.emit({"type": "complete", "total_seconds": report["total_seconds"]})
    return report


def validate(ph: Phantom, ref: sitk.Image, rigid_tx, final_tx, reg_a, enh_a, emethod, spots, hot_labels, p) -> dict:
    out: dict = {}
    p(0.05, "target registration error")
    out["tre_naive"] = ph.tre(None)
    out["tre_rigid"] = ph.tre(rigid_tx)
    out["tre_final"] = ph.tre(final_tx)
    p(0.4, "image quality vs ideal PET")
    truth = im.arr(im.resample(ph.pet_truth, ref))
    labels = im.arr(sitk.Resample(ph.lesion_mask, ref, sitk.Transform(), sitk.sitkNearestNeighbor, 0)).astype(np.uint8)
    brain = im.arr(sitk.Resample(ph.brain_mask, ref, sitk.Transform(), sitk.sitkNearestNeighbor, 0)) > 0
    out["quality_registered"] = mt.image_quality(reg_a, truth, brain)
    out["quality_enhanced"] = mt.image_quality(enh_a, truth, brain) if emethod != "none" else None
    p(0.7, "lesion SUV recovery and hallucination check")
    out["recovery_registered"] = mt.lesion_recovery(reg_a, truth, labels, ph.lesions)
    out["recovery_enhanced"] = mt.lesion_recovery(enh_a, truth, labels, ph.lesions)
    out["hallucination_registered"] = mt.hallucination(reg_a, truth, labels, ph.lesions)
    out["hallucination_enhanced"] = mt.hallucination(enh_a, truth, labels, ph.lesions)
    out["detection"] = mt.detection([s.to_dict() for s in spots], hot_labels, labels, ph.lesions,
                                    float(np.mean(ref.GetSpacing())))
    out["phantom"] = ph.summary()
    return out


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)
