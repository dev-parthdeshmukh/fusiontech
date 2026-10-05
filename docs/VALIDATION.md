# Validation methodology

## Why simulation

To *measure* registration accuracy you need to know where every voxel truly belongs. Real
PET/MRI pairs from separate scanners never come with that answer, which is precisely the problem
FusionMap solves. Hybrid PET-MRI data are aligned by hardware, but that alignment is exactly what we
have no access to.

So we validate the way PET physicists do (BrainWeb, Hoffman-phantom studies): with **digital
patients** whose ground truth we construct.

## The digital patient (`fusionmap/phantom.py`)

| Component | Model | Source / motivation |
|---|---|---|
| Anatomy | MNI ICBM152 2009a T1 template + grey/white-matter maps, warped by a random smooth field (2–6 mm) and ±5 % scaling | A different "patient" for every seed |
| Head | Meninges, skull with diploë, scalp, built from a distance map with random thickness | Gives the PET and MRI realistic head outlines |
| MRI | T1 post-contrast: tumour core hypointense, enhancing rim, peritumoural oedema, necrosis, bias field, Rician noise | Typical glioma/metastasis appearance |
| PET activity | FDG: GM 6.5, WM 2.4, CSF 0.3 SUV, tumour 10.5–16. FET: GM 1.3, WM 1.0, tumour 2.9–4.8. Heterogeneous uptake, necrotic cores | Wei et al. 2022 (FDG glioma SUV); Alongi et al. 2024 (amino-acid TBR) |
| Lesion kinds | Viable (MRI + PET), **MRI-occult** (PET only), **radionecrosis** (MRI only, PET-cold) | Tests that enhancement neither misses nor invents uptake |
| PET physics | 6 mm FWHM PSF, 2.5 mm voxels on a 300 × 300 × 230 mm FOV, count-dependent noise (GM SNR ≈ 10) with a 3 mm recon filter | Typical clinical brain PET |
| Mismatch | Head pose up to ±7° (pitch; ±4° roll/yaw) and ±12 mm per axis, plus a smooth 2.5 mm non-rigid component (MRI distortion / brain shift) | Catana et al. 2011 (±6 mm / ±6° head motion); the plan's "up to 15 mm" |

The ground-truth mapping `MRI point → PET point` is `R⁻¹(D⁻¹(p))`. FusionMap computes it by
fixed-point inversion of the distortion field and cross-checks it against ITK's
`InvertDisplacementField` to better than 0.05 mm (`tests/test_phantom.py`).

## Metrics (`fusionmap/metrics.py`)

| Metric | Definition | Why |
|---|---|---|
| **TRE** (mm) | ‖T_est(p) − T_true(p)‖ over 4,000 random brain points; also at tumour centres | The clinically meaningful registration error |
| **PSNR / SSIM / NMAE** | Enhanced (or registered) PET vs the ideal blur-free, noise-free PET, inside the brain | Same metrics as Chen et al. 2025 and Plasma-CycleGAN 2024 |
| **Lesion recovery (RC)** | SUVmax measured / SUVmax true, per PET-positive lesion | Partial-volume loss under-reports small tumours (RC < 1) |
| **Radionecrosis ratio** | Mean measured / mean true uptake inside the PET-cold lesion | > 1 means MRI structure was painted into PET |
| **Detection** | A hotspot (TBR ≥ 1.6) overlapping a PET-positive truth lesion; false positives = unmatched hotspots | What a reader would act on |
| **NMI, edge alignment** | Normalised mutual information and gradient-direction agreement, MRI vs PET | Ground-truth-free QA, reported for real patients too |

## Protocol (`fusionmap/benchmark.py`)

- Seeds **≥ 1000** are used. Training used seeds 0–199 (VoxelMorph) and 0–31 (enhancer), so no
  benchmark patient was seen during training.
- Tracers alternate FDG / FET. Each patient has 2–3 lesions with a 70 / 15 / 15 % mix of viable,
  MRI-occult and radionecrosis.
- Every registration method runs on the same patient. Every enhancement method runs on the
  same registered PET, the output of the best registration.
- Results are written to `docs/benchmark.json` and rendered in the README and on the web
  *Validation* page.

Reproduce: `fusionmap benchmark --cases 12` (≈ 15 min on a 4-core CPU).

## Limitations

1. **One anatomy family.** All phantoms derive from a single population template. Warping adds
   variety, but real patients vary more: atrophy, resection cavities, implants, motion artefacts.
2. **Simulation ≠ reconstruction.** PET noise is modelled in image space. Real OSEM
   reconstructions, attenuation/scatter errors and truncation artefacts are not simulated.
3. **The AI was trained in minutes on a CPU, on simulated data.** The numbers show that the method
   works; they are not clinical performance. Clinical use needs fine-tuning on paired data (TCIA)
   and prospective reader studies.
4. **Brain only.** The brain is nearly rigid. Lung and prostate deform far more, and there the
   deformable stage, not rigid MI, carries the load.
5. **Quantitative caveat.** AI-enhanced SUVs are model outputs. FusionMap therefore exports the
   *registered* PET (`PET_REG`) alongside the *enhanced* PET (`PET_AI`), so quantitative reads can
   always use the conventional image.
