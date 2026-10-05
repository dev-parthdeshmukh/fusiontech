# Training the AI models

Both networks train **on a 4-core CPU in under an hour**. No GPU is needed, and the outputs
are ONNX files in `fusionmap/models/`, which the app loads with ONNX Runtime.

```bash
pip install -e ".[train]"                       # adds PyTorch + ONNX
make data                                        # ~15 min: 200 VoxelMorph pairs + 32 enhancer patients
python -m training.train_enhancer --iters 3000   # ~20 min
python -m training.train_voxelmorph --iters 12000  # ~20 min
make benchmark                                   # validation table -> docs/benchmark.json
```

## Data: randomised digital patients

`training/make_data.py` draws a random configuration for every seed:

- FDG or FET tracer
- 1–4 lesions mixed as viable, MRI-occult and radionecrosis
- 3–9° / 5–15 mm head-pose mismatch and 1–4 mm non-rigid distortion
- 2–6 mm anatomical variability
- 2.0–3.0 mm PET voxels, 4.5–7.5 mm PSF and SNR 6–16

Each sample is then built with **the same preprocessing functions the runtime uses**.

| Dataset | Seeds | Content |
|---|---|---|
| `training/data/vxm/` | 0–199 (last 16 = validation) | 2 mm crop of MRI + rigidly aligned PET (with ±0.5 mm / ±0.4° residual rigid error), ground-truth displacement |
| `training/data/enhancer/` | 0–31 (last 3 = validation) | 1 mm head crop: registered PET (±0.4 mm / ±0.3° residual), MRI, ideal PET, lesion labels |

The benchmark uses seeds ≥ 1000, so no benchmark patient was ever seen during training.

## ViT-hybrid enhancer (`training/train_enhancer.py`)

- **Architecture.** A U-Net with four stride-2 levels (base 24 channels). The bottleneck is a
  4-layer Vision Transformer: dimension 128, 4 heads, convolutional positional encoding. The head
  is zero-initialised and residual, so the untrained network is the identity: it starts from the
  PET as acquired and learns only the correction. 2.45 M parameters.
- **Input.** Three neighbouring slices of PET and of MRI (2.5-D).
- **Loss.** Lesion-weighted L1 (×6 inside and around tumours) plus 0.5 × gradient-L1 for edges.
- **Sampling.** 45 % of crops are centred on lesions. Flips and an MRI contrast γ-jitter are
  applied.
- **Why both PET and MRI.** The MRI supplies tissue boundaries. The PET supplies how much uptake
  there is. Training lesions include MRI-occult tumours and PET-cold radionecrosis, so copying the
  MRI is penalised.

## VoxelMorph-diff (`training/train_voxelmorph.py`)

- **Architecture.** A 3-D U-Net on a 4 mm grid: encoder (16, 32, 32), decoder (32, 32), final
  (32, 16). It predicts a stationary velocity at 8 mm, which 7 scaling-and-squaring steps
  integrate into a diffeomorphic displacement.
- **Loss.** End-point error against the simulated truth, plus 0.1 × (−mutual information)
  between the MRI and the warped PET, plus a diffusion regulariser. VoxelMorph explicitly supports
  auxiliary losses. The MI term keeps the model image-driven, as it must be on real data.
- **Why a 4 mm grid.** PET resolves only about 6 mm. Coarser sampling makes each iteration about
  8× cheaper, which buys the 10× more iterations that sub-voxel motion estimation needs on a CPU.

## Conditional CycleGAN (`training/train_cyclegan.py`)

This is for hospitals with **unpaired** data: routine PET from their own scanner and sharp PET
from elsewhere.

- **Generators.** Lightweight ViT-hybrids taking (PET, MRI) as input.
- **Discriminators.** PatchGAN.
- **Losses.** LSGAN + cycle (λ = 10) + identity (λ = 5).

The exported generator has the same I/O style as the enhancer.

## Fine-tuning on real data (TCIA)

Real paired data can replace the phantoms. The trainers only need arrays in the
`enh_*.npz` / `vxm_*.npz` format:

1. Register each real PET/MRI pair with `fusionmap run` (rigid MI) and keep
   `work/pet_registered.nii.gz` and `work/mri.nii.gz`.
2. **Enhancer.** Use a high-resolution PET as `truth` where available, e.g. brain-dedicated PET
   or a reconstruction with PSF modelling. Otherwise train the CycleGAN on unpaired sets.
3. **VoxelMorph.** Drop the field term (`--lambda-mi 1`, no `disp` supervision). The MI + diffusion
   loss is the classic unsupervised VoxelMorph objective.
