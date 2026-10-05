"""Digital PET/MRI patient phantoms with exact ground truth.

Real paired PET/MRI data with *known* alignment does not exist — that is precisely the
problem FusionMap solves.  To measure accuracy honestly we simulate patients the way PET
physicists do (cf. BrainWeb / Hoffman-phantom studies):

* **Anatomy** — the MNI ICBM152 2009a T1 template and its grey/white-matter maps, warped by a
  random smooth deformation + scaling so every seed is a different "patient".
* **Tumours** — 1-3 irregular lesions with optional necrotic core, peritumoural oedema and a
  contrast-enhancing rim on the (post-gadolinium) T1 MRI.  Uptake ranges follow published
  glioma SUVs (Wei et al., 2022: FDG grade IV 13.9 ± 1.8) and amino-acid PET tumour-to-
  background ratios (Alongi et al., 2024).
* **PET physics** — scanner point-spread function (6 mm FWHM), coarse 2.5 mm voxels,
  count-dependent noise with a reconstruction post-filter.
* **Misalignment** — a different head pose in the PET scanner (rotation up to ±7°, translation
  up to ±12 mm; cf. Catana et al., 2011) plus a smooth non-rigid component (MRI geometric
  distortion / brain shift).

Because we generated the mismatch, we can report *target registration error in millimetres*
and *lesion SUV recovery* against the truth.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from scipy import ndimage as ndi

from . import imaging as im

TEMPLATE_DIR = Path(__file__).parent / "data" / "templates"


@dataclass(frozen=True)
class Tracer:
    key: str
    name: str
    gm: float
    wm: float
    csf: float
    skull: float
    scalp: float
    lesion: tuple[float, float]  # SUV range of viable tumour
    necrosis: float
    edema_factor: float


TRACERS: dict[str, Tracer] = {
    # 18F-FDG: high cortical glucose metabolism -> tumour must out-shine grey matter
    "fdg": Tracer("fdg", "18F-FDG", gm=6.5, wm=2.4, csf=0.3, skull=0.25, scalp=1.0,
                  lesion=(10.5, 16.0), necrosis=1.6, edema_factor=0.85),
    # 18F-FET amino-acid PET: low normal-brain background, tumour-to-background ~2-4
    "fet": Tracer("fet", "18F-FET", gm=1.3, wm=1.0, csf=0.35, skull=0.4, scalp=1.5,
                  lesion=(2.9, 4.8), necrosis=0.9, edema_factor=1.05),
}


@dataclass
class PhantomConfig:
    seed: int = 7
    tracer: str = "fdg"
    n_lesions: int | None = None  # None -> 1..3 at random
    lesion_mix: str = "active"  # active | mixed | showcase
    rotation_deg: float = 7.0  # max |angle| (pitch); roll/yaw use 60 %
    translation_mm: float = 12.0  # max |shift| per axis
    nonrigid_mm: float = 2.5  # peak residual non-rigid displacement
    anatomy_mm: float = 4.0  # inter-subject variability applied to the template
    mri_spacing: float = 1.0
    pet_spacing: float = 2.5
    pet_fwhm_mm: float = 6.0
    pet_snr: float = 10.0  # mean/std in grey matter of the reconstructed PET
    mri_noise: float = 0.02

    @classmethod
    def from_dict(cls, d: dict) -> PhantomConfig:
        keys = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in keys})


@dataclass
class Lesion:
    id: int
    center_mm: list[float]
    radius_mm: float
    suv_true: float
    necrotic: bool
    volume_ml: float = 0.0
    kind: str = "active"  # active | pet_only | mri_only


@dataclass
class Phantom:
    config: PhantomConfig
    mri: sitk.Image  # T1w post-contrast MRI on the patient grid
    pet: sitk.Image  # PET in its own scanner geometry (SUV)
    pet_truth: sitk.Image  # ideal activity on the MRI grid (no blur, no noise, aligned)
    lesion_mask: sitk.Image  # uint8 labels on the MRI grid
    brain_mask: sitk.Image
    lesions: list[Lesion]
    # ground-truth geometry: PET physical point q  ->  MRI physical point  D(R(q))
    rigid_matrix: np.ndarray  # 3x3 rotation of R
    rigid_offset: np.ndarray  # R(q) = M q + offset
    nonrigid_field: np.ndarray  # [z, y, x, 3] displacement (mm, xyz) on the MRI grid
    eval_points: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))

    # -- ground truth mapping MRI -> PET (what registration must recover) -------------
    def true_pet_points(self, pts_mri: np.ndarray) -> np.ndarray:
        """``T_gt(p) = R^-1(D^-1(p))`` for MRI physical points ``p`` (N x 3, mm)."""
        p = np.asarray(pts_mri, dtype=np.float64)
        x = p.copy()
        for _ in range(20):  # fixed-point inversion of x + u(x) = p
            x = p - _sample_field(self.nonrigid_field, self.mri, x)
        return (x - self.rigid_offset) @ np.linalg.inv(self.rigid_matrix).T

    def tre(self, transform: sitk.Transform | None, pts_mri: np.ndarray | None = None) -> dict:
        """Target registration error of an MRI->PET transform (identity = naive overlay)."""
        pts = self.eval_points if pts_mri is None else pts_mri
        truth = self.true_pet_points(pts)
        tx = transform if transform is not None else sitk.Transform(3, sitk.sitkIdentity)
        est = np.array([tx.TransformPoint(tuple(map(float, p))) for p in pts])
        err = np.linalg.norm(est - truth, axis=1)
        lesion_err = []
        if self.lesions:
            lc = np.array([les.center_mm for les in self.lesions])
            lt = self.true_pet_points(lc)
            le = np.array([tx.TransformPoint(tuple(map(float, p))) for p in lc])
            lesion_err = np.linalg.norm(le - lt, axis=1).tolist()
        return {
            "mean_mm": float(err.mean()),
            "median_mm": float(np.median(err)),
            "p95_mm": float(np.percentile(err, 95)),
            "max_mm": float(err.max()),
            "lesion_mm": [float(v) for v in lesion_err],
        }

    def summary(self) -> dict:
        tr = TRACERS[self.config.tracer]
        angles = _matrix_to_euler_deg(self.rigid_matrix)
        return {
            "config": asdict(self.config),
            "tracer": tr.name,
            "lesions": [asdict(les) for les in self.lesions],
            "misalignment": {
                "rotation_deg": angles,
                "translation_mm": [float(v) for v in self.rigid_offset_about_center()],
                "nonrigid_peak_mm": float(np.linalg.norm(self.nonrigid_field, axis=-1).max()),
            },
        }

    def rigid_offset_about_center(self) -> np.ndarray:
        c = np.mean(self.eval_points, axis=0) if len(self.eval_points) else np.zeros(3)
        return (self.rigid_matrix @ c + self.rigid_offset) - c

    def save(self, folder: Path) -> None:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        sitk.WriteImage(sitk.Cast(self.mri, sitk.sitkInt16), str(folder / "mri.nii.gz"))
        sitk.WriteImage(self.pet, str(folder / "pet.nii.gz"))
        sitk.WriteImage(self.pet_truth, str(folder / "truth_pet.nii.gz"))
        sitk.WriteImage(self.lesion_mask, str(folder / "truth_lesions.nii.gz"))
        sitk.WriteImage(self.brain_mask, str(folder / "truth_brain.nii.gz"))
        np.savez_compressed(
            folder / "truth_geometry.npz",
            rigid_matrix=self.rigid_matrix,
            rigid_offset=self.rigid_offset,
            nonrigid_field=self.nonrigid_field.astype(np.float32),
            eval_points=self.eval_points,
        )
        (folder / "truth.json").write_text(json.dumps(self.summary(), indent=2))

    @classmethod
    def load(cls, folder: Path) -> Phantom:
        folder = Path(folder)
        meta = json.loads((folder / "truth.json").read_text())
        geo = np.load(folder / "truth_geometry.npz")
        return cls(
            config=PhantomConfig.from_dict(meta["config"]),
            mri=im.to_float(sitk.ReadImage(str(folder / "mri.nii.gz"))),
            pet=im.to_float(sitk.ReadImage(str(folder / "pet.nii.gz"))),
            pet_truth=im.to_float(sitk.ReadImage(str(folder / "truth_pet.nii.gz"))),
            lesion_mask=sitk.ReadImage(str(folder / "truth_lesions.nii.gz")),
            brain_mask=sitk.ReadImage(str(folder / "truth_brain.nii.gz")),
            lesions=[Lesion(**d) for d in meta["lesions"]],
            rigid_matrix=geo["rigid_matrix"],
            rigid_offset=geo["rigid_offset"],
            nonrigid_field=geo["nonrigid_field"].astype(np.float64),
            eval_points=geo["eval_points"],
        )


# ----------------------------------------------------------------------------------------
# construction
# ----------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def templates() -> tuple[sitk.Image, sitk.Image, sitk.Image]:
    out = []
    for name in ("mni152_t1", "mni152_gm", "mni152_wm"):
        img = im.canonical(sitk.ReadImage(str(TEMPLATE_DIR / f"{name}.nii.gz")))
        out.append(img / 255.0)
    return tuple(out)  # type: ignore[return-value]


def make_phantom(cfg: PhantomConfig | None = None) -> Phantom:
    cfg = cfg or PhantomConfig()
    if cfg.tracer not in TRACERS:
        raise ValueError(f"unknown tracer {cfg.tracer!r}; choose from {sorted(TRACERS)}")
    tracer = TRACERS[cfg.tracer]
    rng = np.random.default_rng(cfg.seed)
    t1_t, gm_t, wm_t = templates()

    # ---- patient grid: template extent + room for skull and scalp (none below the cut) ----
    lo, hi = im.physical_bounds(t1_t)
    margin = 16.0
    lo = lo - np.array([margin, margin, 0.0])
    hi = hi + np.array([margin, margin, margin])
    sp = float(cfg.mri_spacing)
    size = np.ceil((hi - lo) / sp).astype(int) + 1
    grid = im.empty_like_grid(lo, (sp, sp, sp), size)

    # ---- anatomy: random smooth warp + scaling of the template ----
    center = np.array(t1_t.TransformContinuousIndexToPhysicalPoint([(s - 1) / 2 for s in t1_t.GetSize()]))
    scale = 1.0 + rng.uniform(-0.05, 0.05, 3)
    aff = sitk.AffineTransform(3)
    aff.SetCenter(center.tolist())
    aff.SetMatrix(np.diag(1.0 / scale).ravel().tolist())
    anat_field = _smooth_field(grid, cfg.anatomy_mm, 36.0, rng)
    anat = sitk.CompositeTransform([aff, _displacement_tx(anat_field, grid)])
    t1 = im.arr(im.resample(t1_t, grid, anat))
    gm = im.arr(im.resample(gm_t, grid, anat))
    wm = im.arr(im.resample(wm_t, grid, anat))

    # ---- tissue envelopes ----
    tissue = ndi.gaussian_filter(gm + wm, 1.0 / sp)
    env = ndi.binary_fill_holes(tissue > 0.25)
    env = im.largest_component(env)
    env_soft = ndi.gaussian_filter(env.astype(np.float32), 0.8 / sp)
    csf = np.clip(env_soft - gm - wm, 0, 1)
    dist = _distance_mm(~env, sp)
    wobble = _smooth_scalar(grid.GetSize()[::-1], 1.5, 30.0 / sp, rng)
    d = dist + wobble * (dist > 0)
    meninges = (d > 0) & (d <= 2.0)
    skull = (d > 2.0) & (d <= 8.0)
    diploe = (d > 4.0) & (d <= 6.0)
    scalp = (d > 8.0) & (d <= 13.0)

    # ---- lesions ----
    L, labels, lesions = _make_lesions(cfg, rng, grid, gm, wm, env, tracer)

    # ---- MRI: T1-weighted, post-contrast ----
    mri = t1.copy()
    mri *= 1.0 - 0.2 * L["mri_edema"] * np.clip(wm * 1.4, 0, 1)
    mri = mri * (1 - L["mri_core"]) + 0.42 * L["mri_core"]
    mri = mri * (1 - L["mri_necro"]) + 0.2 * L["mri_necro"]
    mri = mri * (1 - L["mri_rim"]) + 0.97 * L["mri_rim"]
    texture = _smooth_scalar(mri.shape, 1.0, 3.0 / sp, rng)
    mri[meninges] = 0.10
    mri[skull] = 0.05
    mri[diploe] = 0.20 + 0.04 * texture[diploe]
    mri[scalp] = 0.70 + 0.08 * texture[scalp]
    mri = ndi.gaussian_filter(mri, 0.45 / sp)
    head = (d <= 13.0) | env
    mri[~head] = 0.0
    bias = 1.0 + _smooth_scalar(mri.shape, 0.07, 80.0 / sp, rng)
    mri *= bias
    n1, n2 = rng.normal(0, cfg.mri_noise, (2, *mri.shape)).astype(np.float32)
    mri = np.sqrt((mri + n1) ** 2 + n2**2)  # Rician magnitude noise
    mri = np.clip(mri * 1000.0, 0, 4000).astype(np.float32)

    # ---- PET truth activity (SUV) on the patient grid ----
    act = tracer.gm * gm + tracer.wm * wm + tracer.csf * csf
    act[meninges] += tracer.csf
    act[skull] = tracer.skull
    act[scalp] = tracer.scalp * (1.0 + 0.15 * texture[scalp])
    act *= 1.0 + (tracer.edema_factor - 1.0) * L["pet_edema"]
    hetero = 1.0 + 0.12 * _smooth_scalar(act.shape, 1.0, 4.0 / sp, rng)
    act = act * (1 - L["pet_w"]) + L["pet_suv"] * hetero
    act = act * (1 - L["pet_necro"]) + tracer.necrosis * L["pet_necro"]
    act = act * (1 - L["pet_cold"]) + tracer.wm * 1.1 * L["pet_cold"]  # radionecrosis: no uptake
    act = np.clip(act, 0, None).astype(np.float32)
    for les in lesions:
        sel = labels == les.id
        les.suv_true = float(act[sel].max()) if np.any(sel) else les.suv_true

    mri_img = im.like(mri, grid)
    truth_img = im.like(act, grid)
    lesion_img = im.like(labels.astype(np.uint8), grid, np.uint8)
    brain_img = im.like(env.astype(np.uint8), grid, np.uint8)

    # ---- PET acquisition geometry: different head pose + non-rigid residual ----
    ang = np.deg2rad(rng.uniform(-1, 1, 3) * cfg.rotation_deg * np.array([1.0, 0.6, 0.6]))
    rot = _euler_matrix(*ang)
    trans = rng.uniform(-1, 1, 3) * cfg.translation_mm
    c_head = np.array(grid.TransformContinuousIndexToPhysicalPoint(
        ndi.center_of_mass(env)[::-1]))
    # R(q) = rot (q - c) + c + trans  -> PET scanner point to MRI point (pre-distortion)
    offset = c_head + trans - rot @ c_head
    rigid = sitk.AffineTransform(3)
    rigid.SetMatrix(rot.ravel().tolist())
    rigid.SetTranslation(offset.tolist())
    nr_field = _smooth_field(grid, cfg.nonrigid_mm, 55.0, rng)
    S = sitk.CompositeTransform([_displacement_tx(nr_field, grid), rigid])  # D(R(q))

    pet_sp = float(cfg.pet_spacing)
    pet_fov = np.array([300.0, 300.0, 230.0])
    pet_size = np.ceil(pet_fov / pet_sp).astype(int)
    pet_origin = c_head - (pet_size - 1) * pet_sp / 2.0
    pet_grid = im.empty_like_grid(pet_origin, (pet_sp,) * 3, pet_size)
    blurred = im.gaussian_fwhm(truth_img, cfg.pet_fwhm_mm)
    clean = im.arr(im.resample(blurred, pet_grid, S))
    # count statistics: noise variance proportional to activity, spatially correlated by recon
    gm_level = tracer.gm * 0.85
    k = cfg.pet_snr**2 / gm_level
    n = rng.normal(0, 1, clean.shape).astype(np.float32)
    n = ndi.gaussian_filter(n, (3.0 / 2.3548) / pet_sp)
    n /= n.std() + 1e-8
    pet = np.clip(clean + np.sqrt(np.clip(clean, 0, None) / k) * n, 0, None).astype(np.float32)
    pet_img = im.like(pet, pet_grid)

    # ---- evaluation points for TRE: brain voxels + lesion centres ----
    idx = np.argwhere(env)
    pick = idx[rng.choice(len(idx), size=min(4000, len(idx)), replace=False)]
    pts = np.array([grid.TransformContinuousIndexToPhysicalPoint(tuple(map(float, z[::-1]))) for z in pick])

    return Phantom(
        config=cfg, mri=mri_img, pet=pet_img, pet_truth=truth_img, lesion_mask=lesion_img,
        brain_mask=brain_img, lesions=lesions, rigid_matrix=rot, rigid_offset=offset,
        nonrigid_field=nr_field, eval_points=pts,
    )


def _make_lesions(cfg, rng, grid, gm, wm, env, tracer):
    """Place irregular tumours; returns soft weight maps for MRI and PET appearance.

    Lesion kinds
    ------------
    * ``active``   — enhancing on MRI and hypermetabolic on PET (viable tumour)
    * ``pet_only`` — MRI-occult infiltrative tumour: PET uptake, near-normal T1
    * ``mri_only`` — radionecrosis: enhancing rim on MRI but metabolically cold on PET
    The last two exist so we can prove the enhancer does not "paint" MRI anatomy into PET.
    """
    sp = float(cfg.mri_spacing)
    shape = gm.shape
    n = cfg.n_lesions if cfg.n_lesions is not None else int(rng.integers(1, 4))
    keys = ("mri_core", "mri_necro", "mri_rim", "mri_edema", "pet_w", "pet_suv", "pet_necro", "pet_cold",
            "pet_edema")
    L = {k: np.zeros(shape, np.float32) for k in keys}
    labels = np.zeros(shape, np.uint8)
    lesions: list[Lesion] = []
    inner = _distance_mm(env, sp)
    # tumours favour the grey/white junction and deep white matter, away from the surface
    cand = np.argwhere((inner > 22.0) & (wm > 0.35) & (gm > 0.05))
    if len(cand) == 0:
        cand = np.argwhere(inner > 15.0)
    zz, yy, xx = np.meshgrid(*[np.arange(-40, 41) * sp] * 3, indexing="ij")
    centers_vox: list[np.ndarray] = []
    for lid in range(1, n + 1):
        for _ in range(200):
            c = cand[rng.integers(len(cand))]
            if all(np.linalg.norm((c - o) * sp) > 38.0 for o in centers_vox):
                break
        centers_vox.append(c)
        kind = _pick_kind(cfg.lesion_mix, rng, lid)
        r = float(rng.uniform(5.5, 12.5))
        radii = r * rng.uniform(0.8, 1.2, 3)
        rot = _euler_matrix(*rng.uniform(-math.pi, math.pi, 3))
        necrotic = bool(r > 8.5 and rng.random() < 0.65)
        suv = float(rng.uniform(*tracer.lesion))
        half = int(math.ceil(min(40.0, r * 2.2 + 4) / sp))
        sl = tuple(slice(max(int(ci) - half, 0), min(int(ci) + half + 1, s)) for ci, s in zip(c, shape))
        local = tuple(slice(sl_i.start - int(ci) + 40, sl_i.stop - int(ci) + 40) for sl_i, ci in zip(sl, c))
        coords = np.stack([xx[local], yy[local], zz[local]], -1)  # mm offsets (x, y, z)
        q = coords @ rot  # rotate into lesion frame
        rho = np.sqrt(((q / radii) ** 2).sum(-1))
        bumpy = 1.0 + 0.14 * _smooth_scalar(rho.shape, 1.0, 3.0 / sp, rng)
        rho = rho * bumpy
        edge = 0.9 / r
        w = (1.0 / (1.0 + np.exp((rho - 1.0) / edge))) * env[sl]
        nec = (1.0 / (1.0 + np.exp((rho - 0.5) / edge))) if necrotic else np.zeros_like(w)
        rim = np.exp(-(((rho - 0.92) / 0.09) ** 2)) * w * (0.9 if necrotic else 0.55)
        ede = np.clip(1.0 / (1.0 + np.exp((rho - 1.9) / 0.15)) - w, 0, 1) * env[sl]

        def put(key, val, sl=sl):
            L[key][sl] = np.maximum(L[key][sl], val)

        if kind in ("active", "mri_only"):
            put("mri_core", w)
            put("mri_necro", nec)
            put("mri_rim", rim)
            put("mri_edema", ede)
        else:  # MRI-occult: only a faint T1 change
            put("mri_edema", 0.35 * (ede + w))
        if kind in ("active", "pet_only"):
            put("pet_w", w)
            L["pet_suv"][sl] = np.maximum(L["pet_suv"][sl], w * suv)
            put("pet_necro", nec)
            put("pet_edema", ede)
        else:
            put("pet_cold", w)
        lab = labels[sl]
        lab[(w > 0.5) & (lab == 0)] = lid
        center_mm = list(grid.TransformContinuousIndexToPhysicalPoint(tuple(map(float, c[::-1]))))
        vol = float((lab == lid).sum() * sp**3 / 1000.0)
        lesions.append(Lesion(id=lid, center_mm=[float(v) for v in center_mm], radius_mm=round(r, 2),
                              suv_true=suv, necrotic=necrotic, volume_ml=round(vol, 2), kind=kind))
    return L, labels, lesions


def _pick_kind(mix: str, rng, lid: int) -> str:
    if mix == "active":
        return "active"
    if mix == "mixed":
        u = rng.random()
        return "active" if u < 0.7 else ("pet_only" if u < 0.85 else "mri_only")
    if mix == "showcase":  # demo: one of each, in a fixed order
        return ("active", "mri_only", "pet_only")[(lid - 1) % 3]
    raise ValueError(f"unknown lesion_mix {mix!r}")


# ----------------------------------------------------------------------------------------
# small numerical helpers
# ----------------------------------------------------------------------------------------


def _euler_matrix(ax: float, ay: float, az: float) -> np.ndarray:
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def _matrix_to_euler_deg(m: np.ndarray) -> list[float]:
    ay = math.asin(-max(-1.0, min(1.0, m[2, 0])))
    ax = math.atan2(m[2, 1], m[2, 2])
    az = math.atan2(m[1, 0], m[0, 0])
    return [round(math.degrees(a), 3) for a in (ax, ay, az)]


def _smooth_scalar(shape, amplitude: float, corr_vox: float, rng) -> np.ndarray:
    """Smooth zero-mean random field scaled to ``max|f| = amplitude``."""
    corr = max(float(corr_vox), 1.0)
    coarse_shape = tuple(int(math.ceil(s / corr)) + 3 for s in shape)
    coarse = sitk.GetImageFromArray(rng.normal(0, 1, coarse_shape).astype(np.float32))
    coarse.SetSpacing((corr,) * 3)
    coarse.SetOrigin((-corr,) * 3)
    ref = sitk.Image([int(s) for s in shape[::-1]], sitk.sitkFloat32)  # unit spacing, origin 0
    if corr >= 8.0:  # cubic onto an intermediate grid, then cheap linear upsampling
        step = corr / 4.0
        mid = sitk.Image([int(math.ceil(s / step)) + 2 for s in shape[::-1]], sitk.sitkFloat32)
        mid.SetSpacing((step,) * 3)
        mid.SetOrigin((-step,) * 3)
        coarse = sitk.Resample(coarse, mid, sitk.Transform(), sitk.sitkBSpline, 0.0, sitk.sitkFloat32)
        interp = sitk.sitkLinear
    else:
        interp = sitk.sitkBSpline
    f = sitk.GetArrayFromImage(sitk.Resample(coarse, ref, sitk.Transform(), interp, 0.0, sitk.sitkFloat32))
    f = f - f.mean()
    peak = np.abs(f).max() + 1e-8
    return (f / peak * amplitude).astype(np.float32)


def _distance_mm(mask: np.ndarray, spacing: float) -> np.ndarray:
    """Euclidean distance (mm) from each foreground voxel of ``mask`` to the background."""
    img = sitk.GetImageFromArray((~mask).astype(np.uint8))
    img.SetSpacing((spacing,) * 3)
    d = sitk.SignedMaurerDistanceMap(img, insideIsPositive=False, squaredDistance=False, useImageSpacing=True)
    return np.clip(sitk.GetArrayFromImage(d), 0, None).astype(np.float32)


def _smooth_field(ref: sitk.Image, amplitude_mm: float, ctrl_mm: float, rng) -> np.ndarray:
    """Smooth random displacement field ``[z, y, x, 3]`` (mm, xyz order), peak = amplitude."""
    shape = ref.GetSize()[::-1]
    sp = np.array(ref.GetSpacing())
    comps = [_smooth_scalar(shape, 1.0, ctrl_mm / sp.mean(), rng) for _ in range(3)]
    f = np.stack(comps, -1)
    mag = np.linalg.norm(f, axis=-1).max() + 1e-8
    return (f / mag * amplitude_mm).astype(np.float64)


def _displacement_tx(field_zyx3: np.ndarray, ref: sitk.Image) -> sitk.DisplacementFieldTransform:
    vec = sitk.GetImageFromArray(field_zyx3.astype(np.float64), isVector=True)
    vec.CopyInformation(ref)
    return sitk.DisplacementFieldTransform(vec)


def _sample_field(field_zyx3: np.ndarray, ref: sitk.Image, pts: np.ndarray) -> np.ndarray:
    """Trilinear sample of a displacement field at physical points (N x 3)."""
    origin = np.array(ref.GetOrigin())
    sp = np.array(ref.GetSpacing())
    ijk = (pts - origin) / sp  # (x, y, z) continuous index
    coords = [ijk[:, 2], ijk[:, 1], ijk[:, 0]]
    return np.stack(
        [ndi.map_coordinates(field_zyx3[..., c], coords, order=1, mode="nearest") for c in range(3)], -1
    )
