"""FusionMap — AI software PET/MRI fusion.

Three steps turn two separately acquired scans into one clinically useful image:

1. **Register**  — correct the positional mismatch between the PET and MRI scans
   (mutual-information rigid alignment + VoxelMorph-style deformable refinement).
2. **Enhance**   — sharpen the blurry, noisy PET using the MRI anatomy as a guide
   (hybrid CNN/Vision-Transformer U-Net, with a classical deconvolution fallback).
3. **Fuse**      — merge both into a single colour-coded DICOM that drops straight into
   the hospital PACS, plus an RT-STRUCT of the PET-defined tumour volume.

RESEARCH PROTOTYPE — NOT FOR CLINICAL OR DIAGNOSTIC USE.
"""

__version__ = "1.0.0"

DISCLAIMER = "FusionMap research prototype - not for clinical or diagnostic use"
