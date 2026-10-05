"""Generate training data from randomised digital phantoms.

    python -m training.make_data --kind enhancer --n 30 --out training/data/enhancer
    python -m training.make_data --kind vxm --n 200 --out training/data/vxm

Every sample is produced with the *same* preprocessing functions the runtime pipeline uses
(``fusionmap.enhancement.ai`` / ``fusionmap.registration.learned``), so there is no
train/inference skew.
"""

from __future__ import annotations

import argparse
import math
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from fusionmap import imaging as im
from fusionmap.phantom import PhantomConfig, make_phantom
from fusionmap.registration import learned


def random_config(seed: int, spacing: float) -> PhantomConfig:
    rng = np.random.default_rng(10_000 + seed)
    return PhantomConfig(
        seed=seed,
        tracer=str(rng.choice(["fdg", "fet"])),
        n_lesions=int(rng.integers(1, 5)),
        lesion_mix="mixed",
        rotation_deg=float(rng.uniform(3, 9)),
        translation_mm=float(rng.uniform(5, 15)),
        nonrigid_mm=float(rng.uniform(1.0, 4.0)),
        anatomy_mm=float(rng.uniform(2.0, 6.0)),
        mri_spacing=spacing,
        pet_spacing=float(rng.choice([2.0, 2.5, 3.0])),
        pet_fwhm_mm=float(rng.uniform(4.5, 7.5)),
        pet_snr=float(rng.uniform(6.0, 16.0)),
        mri_noise=float(rng.uniform(0.01, 0.035)),
    )


def perturbation(rng, center, sigma_mm: float, sigma_deg: float) -> sitk.Euler3DTransform:
    """Small rigid error about ``center`` emulating an imperfect upstream registration."""
    t = sitk.Euler3DTransform()
    t.SetCenter([float(c) for c in center])
    a = np.deg2rad(rng.normal(0, sigma_deg, 3))
    t.SetRotation(*[float(v) for v in a])
    t.SetTranslation([float(v) for v in rng.normal(0, sigma_mm, 3)])
    return t


def true_transform(ph, coarse_mm: float = 3.0) -> sitk.Transform:
    """Exact-enough MRI->PET ground truth: R^-1(D^-1(p)), field inverted on a coarse grid."""
    rigid = sitk.AffineTransform(3)
    rigid.SetMatrix(ph.rigid_matrix.ravel().tolist())
    rigid.SetTranslation(ph.rigid_offset.tolist())
    disp = sitk.GetImageFromArray(ph.nonrigid_field, isVector=True)
    disp.CopyInformation(ph.mri)
    coarse = im.isotropic_reference(ph.mri, coarse_mm)
    disp = sitk.Resample(disp, coarse, sitk.Transform(), sitk.sitkLinear, 0.0, sitk.sitkVectorFloat64)
    inv = sitk.InvertDisplacementField(disp, maximumNumberOfIterations=40, maxErrorToleranceThreshold=0.01,
                                       meanErrorToleranceThreshold=0.001, enforceBoundaryCondition=True)
    return sitk.CompositeTransform([rigid.GetInverse(), sitk.DisplacementFieldTransform(inv)])


def affine_parts(tx: sitk.Transform) -> tuple[np.ndarray, np.ndarray]:
    """Matrix/offset of an (affine) transform probed at four points: T(p) = A p + b."""
    b = np.array(tx.TransformPoint((0.0, 0.0, 0.0)))
    A = np.stack([np.array(tx.TransformPoint(tuple(e))) - b for e in np.eye(3)], 1)
    return A, b


def enhancer_sample(seed: int, out: Path) -> str:
    rng = np.random.default_rng(seed)
    ph = make_phantom(random_config(seed, 1.0))
    head = im.foreground_mask(ph.mri)
    center = np.mean(ph.eval_points, 0)
    tx = sitk.CompositeTransform([true_transform(ph), perturbation(rng, center, 0.4, 0.3)])
    pet_in_mri = im.arr(im.resample(ph.pet, ph.mri, tx))
    sl = im.bbox(head, margin=6)
    np.savez_compressed(
        out / f"enh_{seed:04d}.npz",
        pet=pet_in_mri[sl].astype(np.float16),
        mri=im.arr(ph.mri)[sl].astype(np.float16),
        truth=im.arr(ph.pet_truth)[sl].astype(np.float16),
        head=head[sl].astype(np.uint8),
        lesions=im.arr(ph.lesion_mask)[sl].astype(np.uint8),
        tracer=ph.config.tracer,
        fwhm=ph.config.pet_fwhm_mm,
    )
    return f"enh {seed}"


def vxm_sample(seed: int, out: Path) -> str:
    rng = np.random.default_rng(seed)
    ph = make_phantom(random_config(seed, 2.0))
    head = im.foreground_mask(ph.mri)
    grid = learned.crop_grid(ph.mri, head)
    center = np.mean(ph.eval_points, 0)
    rigid = sitk.AffineTransform(3)
    rigid.SetMatrix(ph.rigid_matrix.ravel().tolist())
    rigid.SetTranslation(ph.rigid_offset.tolist())
    # imperfect rigid estimate (MRI -> PET), as produced by the MI stage
    rigid_hat = sitk.CompositeTransform([rigid.GetInverse(), perturbation(rng, center, 0.5, 0.4)])
    x = learned.network_inputs(ph.mri, ph.pet, rigid_hat, grid, head)[0]
    # ground-truth displacement phi(p) - p with  rigid_hat(phi(p)) = T_gt(p)
    size = np.array(grid.GetSize())
    idx = np.stack(np.meshgrid(*[np.arange(n) for n in size[::-1]], indexing="ij"), -1).reshape(-1, 3)
    pts = np.array(grid.GetOrigin()) + idx[:, ::-1] * learned.CROP_SPACING
    target = ph.true_pet_points(pts)
    A, b = affine_parts(rigid_hat)
    phi = (target - b) @ np.linalg.inv(A).T
    disp_mm = (phi - pts).reshape(*size[::-1], 3)  # xyz mm on (z, y, x)
    disp_vox = np.moveaxis(disp_mm[..., ::-1] / learned.CROP_SPACING, -1, 0)  # (dz, dy, dx) voxels
    brain = im.arr(sitk.Resample(ph.brain_mask, grid, sitk.Transform(), sitk.sitkNearestNeighbor, 0)) > 0
    np.savez_compressed(out / f"vxm_{seed:04d}.npz", x=x.astype(np.float16), disp=disp_vox.astype(np.float16),
                        brain=brain.astype(np.uint8))
    return f"vxm {seed}"


def _run(args):
    kind, seed, out = args
    try:
        return enhancer_sample(seed, out) if kind == "enhancer" else vxm_sample(seed, out)
    except Exception as e:  # keep the batch going; report the failure
        return f"FAILED {kind} {seed}: {e!r}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["enhancer", "vxm"], required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    seeds = [s for s in range(a.start, a.start + a.n)
             if not (a.out / f"{'enh' if a.kind == 'enhancer' else 'vxm'}_{s:04d}.npz").exists()]
    t0 = time.time()
    sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(max(1, math.ceil(4 / a.workers)))
    with ProcessPoolExecutor(a.workers) as ex:
        for i, msg in enumerate(ex.map(_run, [(a.kind, s, a.out) for s in seeds])):
            print(f"[{i + 1}/{len(seeds)}] {msg}  ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
