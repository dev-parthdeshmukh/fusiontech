# What the literature told us — and where it lives in the code

FusionMap's design is driven by seven papers the team collected. Each entry lists the
finding we used and the exact place in the code where it shows up.

---

### 1. Nensa, Beiderwellen, Heusch, Wetter — *Clinical applications of PET/MRI: current status and future perspectives.* Diagn Interv Radiol 2014;20:438–447

**Findings used**

- The first PET/MRI solutions were *"software based co-registration and post-hoc fusion of
  independently acquired PET and MRI data"*. That is FusionMap's whole approach, now upgraded
  with AI.
- *"The high symmetry and extremely low deformability of the head facilitate post-hoc rigid
  motion correction and co-registration with software-based methods."*
- Retrospective (software) PET/MRI fusion for liver metastases of neuroendocrine tumours reached
  **91.2 % sensitivity vs 73.5 % for PET/CT** (Schreiter et al., cited there).
- The PET/MRI effective dose can be **~20 % of PET/CT** (Hirsch et al., paediatric oncology).
- PET/MRI is an *"expensive technology"* whose added value must justify the investment.

**Used in FusionMap**

- The brain-first scope, and rigid mutual-information alignment as the backbone of Step 1
  (`fusionmap/registration/classical.py`).
- The deformable stage (VoxelMorph) is kept for residual MRI distortion now, and for body sites
  on the roadmap.
- These figures support the "why PET + MRI" story on the *How it works* page.

### 2. Catana et al. — *MRI-assisted PET motion correction for neurologic studies in an integrated MR-PET scanner.* J Nucl Med 2011;52:154–161

**Findings used**

- Head motion during long PET studies blurs structures and reduces grey-matter uptake.
- In volunteers, motion stayed within roughly **±6 mm / ±6°**.
- Even a hardware MR-PET scanner needed the two volumes **co-registered with mutual
  information** (Vinci) to calibrate the PET-to-MRI offset.

**Used in FusionMap**

- Misalignment ranges in the phantom: up to ±7° rotation and ±12 mm translation, including the
  table offset between scanners (`fusionmap/phantom.py`).
- Mattes mutual information as the similarity metric.

### 3. Alongi et al. — *Artificial Intelligence Analysis Using MRI and PET Imaging in Gliomas: A Narrative Review.* Cancers 2024;16:407

**Findings used**

- 18F-FDG has *"limited clinical value in neuro-oncology for the lack of differentiation between
  tumor and normal brain tissue uptake"*.
- Amino-acid tracers (11C-MET, 18F-FET, 18F-FDOPA) give *"outstanding tumor-to-background
  contrast"*. RANO/EANO/EANM have published joint guidance on their use.
- A FET PET/MRI pipeline (Paprottka et al.) aligned the scans with *"a rigid, mutual
  information-driven registration with the open-source ANTs software"*.

**Used in FusionMap**

- Two tracer presets, `fdg` and `fet` (`TRACERS` in `fusionmap/phantom.py`).
- A biological-tumour-volume threshold of **TBR ≥ 1.6** (`fusionmap/analysis.py`).
- Rigid MI registration as the validated clinical baseline.

### 4. Wei, Ma, Yang, Lu, Xi — *Artificial Intelligence Algorithm-Based PET and MRI in the Treatment of Glioma Biopsy.* Comput Math Methods Med 2022

**Findings used**

- FDG SUV in glioma: **grade II/III 9.77 ± 4.87, grade IV 13.91 ± 1.83**. Lesion-to-contralateral
  ratio for grade IV was **2.68 ± 0.10**.
- Tumour was defined where uptake is *"obviously greater than peripheral normal gray matters"*.
- PET and MRI contours were compared to plan biopsy and treatment.

**Used in FusionMap**

- The viable-lesion FDG SUV range in the phantom (10.5–16).
- The hotspot rule: uptake relative to a normal-tissue background.
- Export of PET tumour contours as an **RT-STRUCT**, so planning systems can use them
  (`fusionmap/export/dicom.py`).

### 5. Chen et al. — *MRI-to-PET synthesis via deep learning for amyloid-β quantification in Alzheimer's disease.* Eur Radiol 2025

**Findings used**

- 3-D synthesis *"operates on the whole volume rather than 2D image slices, realistically
  reproducing minor discrepancies between neighboring image planes"*.
- Evaluation used SSIM (0.898), PSNR (34.7 dB), MAE and SUVR correlation.

**Used in FusionMap**

- The enhancer's **2.5-D input**: three neighbouring slices of both PET and MRI
  (`fusionmap/enhancement/ai.py`).
- The same validation metrics, SSIM / PSNR / MAE (`fusionmap/metrics.py`).

### 6. Chen et al. — *Plasma CycleGAN: Integrating Blood-based Biomarkers for Cross-modality Translation from MRI to PET.* Alzheimer's & Dementia 2024;20(S8):e095616

**Findings used**

- CycleGAN is *"the leading method"* for MRI-to-PET translation.
- Conditioning the generator on side information improves it (SSIM 0.72, PSNR 22.8 dB with
  MRI + Aβ42/40).

**Used in FusionMap**

- `training/train_cyclegan.py` is a **conditional CycleGAN**: both generators also see the MRI.
  It is for hospitals that have only *unpaired* data.
- The paired, MRI-guided ViT hybrid is the default because the team's notes (and its higher
  fidelity) favour it when paired data exist.

### 7. Yoon et al. — *Initial Results of Simultaneous PET/MRI Experiments with an MRI-Compatible Silicon Photomultiplier PET Scanner.* J Nucl Med 2012;53:608–614

**Findings used**

- Simultaneous PET/MRI needs MRI-compatible photodetectors (SiPM/APD), per-module RF shielding,
  temperature-compensated gain and interference testing.

**Used in FusionMap**

- This is the hardware-complexity half of the cost argument. FusionMap replaces it with software
  that runs on the hospital's existing PC.

---

### Team notes (`fusionmap.txt`)

| Note | Where it went |
|---|---|
| CT has limited soft-tissue contrast and a significant radiation dose | Why PET + MRI rather than PET-CT (*How it works*) |
| PET = metabolism (cancer detection/staging); MRI = soft tissue (brain, spinal cord, muscle) | The fusion rationale; PET is colour, MRI is greyscale |
| VoxelMorph: a CNN/U-Net predicts a deformation field that aligns *moving* to *fixed* | `training/nets.py::VoxelMorph`, `fusionmap/registration/learned.py` |
| ViT-based hybrids beat CycleGAN for high-fidelity synthesis; CycleGAN suits unpaired mapping | `HybridViTUNet` is the default enhancer; CycleGAN is the unpaired option |
