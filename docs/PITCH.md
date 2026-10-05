# FusionMap: pitch, demo script and judge Q&A

## The 3-minute pitch

**[0:00, the hook]** A tumour that is 15 millimetres away from where the radiotherapist thinks it is
will not be cured. That is the error you get today when a doctor in a district cancer centre puts a
PET scan next to an MRI scan and compares them by eye.

**[0:20, the problem]** PET shows where cancer is *alive*. MRI shows *exactly where* it is in the
anatomy. The machine that does both at once, an integrated PET-MRI, costs 4 to 6 million dollars,
so India has about ten of them. Yet more than 700 cancer centres already own a PET scanner *and* an
MRI. They have the data. What they lack is the fusion.

**[0:45, the solution]** FusionMap is software that does that fusion in three steps, in about a
minute, on the hospital's existing computer:

1. **It fixes the mismatch.** Mutual-information registration plus a VoxelMorph neural network
   bring the alignment error from about 10 mm down to under 1 mm.
2. **It sharpens the blurry PET.** An MRI-guided Vision-Transformer U-Net recovers the tumour
   brightness that scanner blur hides. PSNR goes up by about 10 dB.
3. **It writes one colour-coded DICOM.** It also writes the tumour contours as an RT-STRUCT, and
   pushes everything straight into the hospital PACS and the treatment-planning system.

**[1:20, live demo]** (see the script below)

**[2:20, why believe us]** We didn't just make pictures. Real patients never come with the right
answer, so we built digital patients where we *know* the truth, and we measure the error in
millimetres. Every patient also contains a trap: an MRI-visible radionecrosis with *no* uptake. An
AI that just copies the MRI would light it up. Ours doesn't. Every design decision traces back to a
published study.

**[2:45, the ask]** It costs ₹40–60 thousand to build, needs zero new hardware, and could bring
PET-MRI-grade precision to 700+ centres and 6–8 lakh patients a year. Our next step is fine-tuning
on real paired scans from The Cancer Imaging Archive and running a reader study with nuclear
medicine physicians.

---

## Live demo script (about 60 seconds)

**Before the talk:** run `fusionmap serve` (or `docker compose up`). The showcase patient is
processed automatically on first start. Open `http://localhost:8000`.

1. **Workspace → Compare → Alignment.** Move the mouse across the axial view. *"Left: the two scans
   overlaid as the scanners left them. The tumour glow is off the MRI lesion. Right: after
   FusionMap. It sits on it."* Point at the hero number on the right (e.g. *8.5 → 0.6 mm*) and the
   green *"inside a 2 mm radiotherapy margin"* line.
2. **Compare → Sharpening.** *"Left: the PET as acquired, blurry. Right: AI-enhanced. Small tumours
   get their true brightness back."* Open the **Enhance** tab and show the recovery chart.
3. **Overview → Ground truth check.** *"The viable tumour: found. The tumour you cannot see on MRI
   at all: found, because PET shows it. The radionecrosis that looks like tumour on MRI: correctly
   NOT flagged."*
4. **Tumours tab.** Click a tumour and the viewer jumps to it. Read out *SUVmax, MTV, TBR*.
5. **Export tab → Send to PACS.** With docker compose, the study appears in Orthanc on `:8042`.
   Then open the **printable report**.
6. Optional live run: **Demo patient → random seed → Run FusionMap**, and watch the steps tick.
   The whole run takes about a minute; narrate it over the stepper.

Keyboard: `1–4` switch view modes; `↑ ↓` or the mouse wheel scroll slices; click to navigate.

---

## Judge Q&A

**"Is this validated on real patients?"**
Not yet, and we say so on every screen. Real PET/MRI pairs from separate scanners have no ground
truth for alignment, so we validate on simulated patients built from the MNI152 brain, where we
know the exact answer, plus ground-truth-free metrics (mutual information, edge alignment) that work
on real data. The DICOM import path, including SUV conversion from Bq/ml, is tested end to end.
Next is fine-tuning on TCIA data and a reader study.

**"Why not just buy PET-CT?"**
CT gives poor soft-tissue contrast in the brain and adds radiation dose. PET/MRI dose can be
about 20 % of PET/CT (Nensa 2014). Many centres also already have the MRI.

**"Doesn't the AI just copy the MRI into the PET?"**
That is exactly the failure mode we test for. Every simulated patient includes a radionecrosis,
which enhances on MRI but has no PET uptake, and an MRI-occult tumour, which has PET uptake but no
MRI sign. We report the "radionecrosis ratio" (should be about 1) and detection of the MRI-occult
tumour. FusionMap also always exports the conventional registered PET alongside the AI PET, so a
physician can read quantitative SUVs from the unmodified image.

**"Why VoxelMorph if the brain is rigid?"**
Rigid mutual information does most of the work in the brain, and we say so. VoxelMorph corrects the
residual non-rigid part: MRI geometric distortion and brain shift. It runs in under a second and is
diffeomorphic; we report the Jacobian to prove there is no folding. For body sites (lung, prostate)
it becomes the main event.

**"Why a ViT hybrid instead of CycleGAN?"**
With paired data, a supervised ViT hybrid gives higher fidelity. Attention captures global structure
while convolutions keep detail. CycleGAN is for *unpaired* data, and we ship a conditional CycleGAN
trainer for hospitals in that situation.

**"Does it need a GPU or the cloud?"**
No. Inference is ONNX Runtime on CPU, and a full study takes about a minute. Patient data never
leaves the hospital. We even trained the models on a 4-core CPU.

**"How does it fit into hospital workflow?"**
It reads DICOM from both scanners and writes standard DICOM back: an MR reference series, the
quantitative PET (SUV), the AI PET, the colour fusion and an RT-STRUCT, all sharing one Frame of
Reference. It C-STOREs to the PACS. Planning systems import the RT-STRUCT directly.

**"What is the regulatory path?"**
In India it is software as a medical device under CDSCO, which requires clinical evaluation. Step
one is a retrospective reader study comparing FusionMap to hybrid PET-MRI where available.

**"Where do the numbers in your problem statement come from?"**
They are the team's market research: the cost of hybrid scanners, the centre counts and the
patient numbers. The alignment, quality and detection numbers are the ones *we measured*; see
`docs/benchmark.json`.
