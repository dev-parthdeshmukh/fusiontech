"""Multi-modal registration with Mattes mutual information (SimpleITK).

Mutual information is the reference criterion for PET<->MRI alignment: it does not assume the
two scanners share an intensity relationship (grey matter is *dark* on T1 but *bright* on
FDG-PET) — it only assumes the joint histogram is sharpest when anatomy lines up.
The same criterion is used by the integrated PET/MR literature (Catana et al., 2011) and by
FET-PET/MRI glioma pipelines (Paprottka et al., via Alongi et al., 2024).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import SimpleITK as sitk

from .. import imaging as im

Progress = Callable[[float, str], None]


@dataclass
class RegistrationResult:
    transform: sitk.Transform  # fixed (MRI) physical point -> moving (PET) physical point
    method: str
    seconds: float
    metric_trace: list[float] = field(default_factory=list)  # MI per iteration (higher = better)
    params: dict = field(default_factory=dict)


def _prep(img: sitk.Image) -> sitk.Image:
    return im.to_float(img)


def rigid_mi(
    fixed: sitk.Image,
    moving: sitk.Image,
    fixed_mask: sitk.Image | None = None,
    seed: int = 1234,
    progress: Progress | None = None,
    initial: sitk.Transform | None = None,
) -> RegistrationResult:
    """6-DOF rigid registration, multi-resolution, Mattes MI, moments initialisation."""
    t0 = time.perf_counter()
    fixed, moving = _prep(fixed), _prep(moving)
    if initial is None:
        initial = sitk.CenteredTransformInitializer(
            fixed, moving, sitk.Euler3DTransform(), sitk.CenteredTransformInitializerFilter.MOMENTS)
    tx = sitk.Euler3DTransform(initial) if isinstance(initial, sitk.Euler3DTransform) else sitk.Euler3DTransform(
        sitk.Euler3DTransform(initial))

    reg = sitk.ImageRegistrationMethod()
    reg.SetMetricAsMattesMutualInformation(numberOfHistogramBins=48)
    reg.SetMetricSamplingStrategy(reg.RANDOM)
    reg.SetMetricSamplingPercentage(0.12, seed)
    if fixed_mask is not None:
        reg.SetMetricFixedMask(fixed_mask)
    reg.SetInterpolator(sitk.sitkLinear)
    reg.SetOptimizerAsRegularStepGradientDescent(
        learningRate=2.0, minStep=1e-3, numberOfIterations=250, relaxationFactor=0.6,
        gradientMagnitudeTolerance=1e-8)
    reg.SetOptimizerScalesFromPhysicalShift()
    shrink, smooth = _pyramid(fixed, [4.0, 2.0, 1.5], [3.0, 1.5, 0.75])
    reg.SetShrinkFactorsPerLevel(shrink)
    reg.SetSmoothingSigmasPerLevel(smooth)
    reg.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    reg.SetInitialTransform(tx, inPlace=True)

    trace: list[float] = []
    level = {"n": 0}

    def on_iter():
        trace.append(-float(reg.GetMetricValue()))
        if progress and len(trace) % 5 == 0:
            frac = min(0.98, (level["n"] + min(len(trace) / 150.0, 1.0) * 0.3) / len(shrink))
            progress(frac, f"rigid MI level {level['n'] + 1}/{len(shrink)} · MI={trace[-1]:.3f}")

    def on_level():
        level["n"] = int(reg.GetCurrentLevel())

    reg.AddCommand(sitk.sitkIterationEvent, on_iter)
    reg.AddCommand(sitk.sitkMultiResolutionIterationEvent, on_level)
    reg.Execute(fixed, moving)

    rx, ry, rz = (math.degrees(a) for a in (tx.GetAngleX(), tx.GetAngleY(), tx.GetAngleZ()))
    params = {
        "rotation_deg": [round(rx, 3), round(ry, 3), round(rz, 3)],
        "translation_mm": [round(float(v), 3) for v in tx.GetTranslation()],
        "stop": reg.GetOptimizerStopConditionDescription(),
        "iterations": len(trace),
    }
    return RegistrationResult(sitk.Euler3DTransform(tx), "rigid-mi", time.perf_counter() - t0, trace, params)


def bspline_mi(
    fixed: sitk.Image,
    moving: sitk.Image,
    initial: sitk.Transform,
    fixed_mask: sitk.Image | None = None,
    grid_spacing_mm: float = 50.0,
    seed: int = 1234,
    progress: Progress | None = None,
) -> RegistrationResult:
    """Free-form B-spline deformation on top of a rigid result (classical deformable baseline)."""
    t0 = time.perf_counter()
    fixed, moving = _prep(fixed), _prep(moving)
    phys = np.array(fixed.GetSize()) * np.array(fixed.GetSpacing())
    mesh = [max(int(round(p / grid_spacing_mm)), 1) for p in phys]
    bsp = sitk.BSplineTransformInitializer(fixed, mesh, order=3)

    reg = sitk.ImageRegistrationMethod()
    reg.SetMetricAsMattesMutualInformation(numberOfHistogramBins=48)
    reg.SetMetricSamplingStrategy(reg.RANDOM)
    reg.SetMetricSamplingPercentage(0.08, seed)
    if fixed_mask is not None:
        reg.SetMetricFixedMask(fixed_mask)
    reg.SetInterpolator(sitk.sitkLinear)
    reg.SetOptimizerAsLBFGSB(gradientConvergenceTolerance=1e-5, numberOfIterations=60,
                             maximumNumberOfCorrections=5, maximumNumberOfFunctionEvaluations=400)
    shrink, smooth = _pyramid(fixed, [4.0, 2.0], [2.0, 1.0])
    reg.SetShrinkFactorsPerLevel(shrink)
    reg.SetSmoothingSigmasPerLevel(smooth)
    reg.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    reg.SetMovingInitialTransform(initial)
    reg.SetInitialTransform(bsp, inPlace=True)
    trace: list[float] = []

    def on_iter():
        trace.append(-float(reg.GetMetricValue()))
        if progress and len(trace) % 4 == 0:
            progress(min(0.98, len(trace) / 120.0), f"B-spline MI · MI={trace[-1]:.3f}")

    reg.AddCommand(sitk.sitkIterationEvent, on_iter)
    reg.Execute(fixed, moving)
    composite = sitk.CompositeTransform([initial, bsp])  # initial(bspline(p))
    return RegistrationResult(composite, "rigid-mi+bspline", time.perf_counter() - t0, trace,
                              {"mesh": mesh, "iterations": len(trace)})


def _pyramid(fixed: sitk.Image, target_mm: list[float], sigma_mm: list[float]):
    """Shrink factors that bring the fixed image to roughly ``target_mm`` voxels per level."""
    sp = float(np.mean(fixed.GetSpacing()))
    shrink = [max(int(round(t / sp)), 1) for t in target_mm]
    out_s, out_g = [], []
    for s, g in zip(shrink, sigma_mm):
        if out_s and s >= out_s[-1]:
            continue
        out_s.append(s)
        out_g.append(g)
    return out_s, out_g


def compose_with_field(rigid: sitk.Transform, field_zyx3_mm: np.ndarray, ref: sitk.Image) -> sitk.Transform:
    """``rigid(p + u(p))`` with ``u`` a displacement field (xyz mm) sampled on ``ref``."""
    vec = sitk.GetImageFromArray(field_zyx3_mm.astype(np.float64), isVector=True)
    vec.CopyInformation(ref)
    return sitk.CompositeTransform([rigid, sitk.DisplacementFieldTransform(vec)])


def transform_to_dict(tx: sitk.Transform) -> dict:
    """Serializable summary of the rigid part of a (possibly composite) transform."""
    t = tx
    if isinstance(tx, sitk.CompositeTransform) and tx.GetNumberOfTransforms() > 0:
        t = tx.GetNthTransform(0)
    try:
        e = sitk.Euler3DTransform(t)
        return {
            "rotation_deg": [round(math.degrees(a), 3) for a in (e.GetAngleX(), e.GetAngleY(), e.GetAngleZ())],
            "translation_mm": [round(float(v), 3) for v in e.GetTranslation()],
            "center_mm": [round(float(v), 3) for v in e.GetCenter()],
            "matrix": [round(float(v), 6) for v in e.GetMatrix()],
        }
    except (RuntimeError, TypeError):
        return {"type": t.GetName()}
