import { ArrowRight, Brain, Cpu, FileCheck2, Hospital, IndianRupee, Microscope, Ruler, ScanLine, Sparkles, Wand2 } from "lucide-react";

const LIT: [string, string, string][] = [
  [
    "Nensa et al., Diagn Interv Radiol 2014 — Clinical PET/MRI review",
    "“The high symmetry and extremely low deformability of the head facilitate post-hoc rigid co-registration with software-based methods.” Retrospective PET/MRI fusion reached 91.2 % sensitivity vs 73.5 % for PET/CT in liver metastases.",
    "Brain-first scope; rigid MI as the backbone of Step 1",
  ],
  [
    "Catana et al., J Nucl Med 2011 — MRI-assisted PET motion correction",
    "Head motion of up to ~±6 mm / ±6° during PET blurs structures and lowers grey-matter uptake; the two scanners were co-registered with mutual information.",
    "Mismatch ranges of the phantom; mutual information as the similarity metric",
  ],
  [
    "Alongi et al., Cancers 2024 — AI with MRI and PET in gliomas",
    "FDG has limited value in neuro-oncology because normal brain uptake is high; amino-acid tracers (FET, MET, FDOPA) give outstanding tumour-to-background contrast. FET PET/MRI pipelines use rigid MI registration.",
    "FDG and FET tracer presets; TBR ≥ 1.6 tumour-volume criterion",
  ],
  [
    "Wei et al., Comput Math Methods Med 2022 — CNN-based PET+MRI in glioma",
    "FDG SUV of grade II/III vs IV glioma: 9.77 ± 4.87 vs 13.91 ± 1.83; tumour = uptake clearly above normal grey matter; PET + MRI fusion used to construct tumour contours.",
    "Lesion SUV ranges; hotspot rule; RT-STRUCT contour export",
  ],
  [
    "Chen et al., Eur Radiol 2025 — 3-D MRI-to-PET synthesis (ShareGAN)",
    "Whole-volume synthesis reproduces consistency between neighbouring planes; evaluated with SSIM, PSNR, MAE and SUVR agreement.",
    "2.5-D input (three neighbouring slices); SSIM / PSNR / MAE validation",
  ],
  [
    "Chen et al., Alzheimer’s & Dementia 2024 — Plasma CycleGAN",
    "CycleGAN is the leading MRI→PET translation baseline; conditioning on extra information improves synthesis (SSIM 0.72, PSNR 22.8 dB).",
    "Conditional (MRI-guided) generator; CycleGAN trainer for unpaired data",
  ],
  [
    "Yoon et al., J Nucl Med 2012 — SiPM-based simultaneous PET/MRI",
    "Simultaneous PET/MRI needs MRI-compatible photodetectors, RF shielding and interference engineering.",
    "Why hybrid hardware is expensive — and why software fusion matters",
  ],
];

export function About() {
  return (
    <div className="page">
      <div className="page-inner">
        <div className="chip" style={{ marginBottom: 14 }}>
          <Sparkles size={13} /> Team Code Blooded · AI in Healthcare / Medical Imaging
        </div>
        <h1>PET-MRI precision without the $4–6 million machine</h1>
        <p className="lead">
          FusionMap is an AI software pipeline that virtually combines separately acquired PET and MRI scans into a single,
          colour-coded DICOM image — for any hospital that already owns both machines, with zero new hardware.
        </p>

        <h2>The problem</h2>
        <div className="cards3">
          <div className="stepcard">
            <IndianRupee size={20} color="var(--pet)" />
            <h3>Hybrid scanners are unaffordable</h3>
            <p>Integrated PET-MRI machines cost $4–6 million. Precision cancer imaging stays confined to a handful of elite hospitals.</p>
          </div>
          <div className="stepcard">
            <Hospital size={20} color="var(--mri)" />
            <h3>The scanners already exist</h3>
            <p>700+ cancer centres outside metro cities own both a PET scanner and an MRI — just not in one gantry.</p>
          </div>
          <div className="stepcard">
            <Ruler size={20} color="var(--serious)" />
            <h3>Eyeballing two scans misleads</h3>
            <p>Comparing the scans side-by-side by hand leaves the tumour misplaced by up to ~15 mm — enough to miss it with radiotherapy and burn healthy tissue.</p>
          </div>
        </div>
        <p className="cite">Figures from the team’s problem statement.</p>

        <h2>Why PET + MRI (and not PET-CT)?</h2>
        <div className="cards3">
          <div className="stepcard">
            <ScanLine size={20} color="var(--pet)" />
            <h3>PET shows function</h3>
            <p>Metabolic activity — where the tumour is <i>alive</i>. Used to detect, stage and monitor cancer. But blurry (≈ 4–7 mm).</p>
          </div>
          <div className="stepcard">
            <Brain size={20} color="var(--mri)" />
            <h3>MRI shows anatomy</h3>
            <p>Superior soft-tissue contrast for brain, spinal cord and muscle — without ionising radiation.</p>
          </div>
          <div className="stepcard">
            <Microscope size={20} color="var(--muted)" />
            <h3>CT falls short</h3>
            <p>CT offers limited soft-tissue contrast and adds a significant radiation dose; PET/MRI dose can be ~20 % of PET/CT (Nensa et al., 2014).</p>
          </div>
        </div>

        <h2>How FusionMap works</h2>
        <div className="card" style={{ padding: 18 }}>
          <div className="row wrap" style={{ gap: 10, justifyContent: "center", alignItems: "stretch" }}>
            <Flow t="Inputs" d="MRI DICOM + PET DICOM from two scanners, different days, different coordinates" c="var(--muted)" />
            <ArrowRight size={18} className="muted" style={{ alignSelf: "center" }} />
            <Flow t="1 · Register" d="Mutual-information rigid alignment → VoxelMorph deformable refinement (diffeomorphic)" c="var(--mri)" />
            <ArrowRight size={18} className="muted" style={{ alignSelf: "center" }} />
            <Flow t="2 · Enhance" d="MRI-guided ViT-hybrid U-Net sharpens the blurry PET; uptake from PET, edges from MRI" c="var(--warning)" />
            <ArrowRight size={18} className="muted" style={{ alignSelf: "center" }} />
            <Flow t="3 · Fuse" d="Colour-coded PET-on-MRI, SUV tumour volumes, RT-STRUCT contours" c="var(--pet)" />
            <ArrowRight size={18} className="muted" style={{ alignSelf: "center" }} />
            <Flow t="PACS / TPS" d="Standard DICOM bundle, C-STORE to PACS; contours import into treatment planning" c="var(--good-ink)" />
          </div>
        </div>

        <div className="cards3" style={{ marginTop: 12 }}>
          <div className="stepcard">
            <div className="n">STEP 1</div>
            <h3>Fix the positional mismatch</h3>
            <p>
              Moments initialisation, then multi-resolution rigid registration maximising Mattes mutual information — robust even
              though grey matter is dark on T1 but bright on FDG. A VoxelMorph-diff network then predicts a fold-free deformation
              in a single pass for residual MRI distortion.
            </p>
          </div>
          <div className="stepcard">
            <div className="n">STEP 2</div>
            <h3>Sharpen the blurry PET</h3>
            <p>
              A hybrid U-Net with a Vision-Transformer bottleneck reads the PET together with the co-registered MRI. Convolutions
              keep local detail, attention captures global structure — the property that makes ViT hybrids beat CycleGAN for
              high-fidelity medical synthesis. Small lesions regain the SUVmax that blur stole from them.
            </p>
          </div>
          <div className="stepcard">
            <div className="n">STEP 3</div>
            <h3>One colour-coded DICOM</h3>
            <p>
              PET is colour-mapped over greyscale MRI. FusionMap writes MR, registered PET, AI-enhanced PET, the RGB fusion and an
              RT-STRUCT of PET tumour volumes — all sharing one Frame of Reference — and can push them to the PACS.
            </p>
          </div>
        </div>

        <h2>Engineering choices</h2>
        <div className="cards2">
          <div className="stepcard">
            <Cpu size={18} color="var(--accent)" />
            <h3>Runs on the hospital’s existing PC</h3>
            <p>Models ship as ONNX and run on CPU through ONNX Runtime; the whole study processes in about a minute. No GPU, no cloud upload of patient data.</p>
          </div>
          <div className="stepcard">
            <FileCheck2 size={18} color="var(--accent)" />
            <h3>Standards, not screenshots</h3>
            <p>PET is stored as quantitative SUVbw (Units GML) with per-slice rescale; contours as closed planar RT-STRUCT ROIs referencing the MR slices.</p>
          </div>
          <div className="stepcard">
            <Wand2 size={18} color="var(--accent)" />
            <h3>Honest AI</h3>
            <p>Every simulated patient includes an MRI-occult tumour and a PET-cold radionecrosis, so we can prove the enhancer neither misses uptake nor paints MRI anatomy into PET.</p>
          </div>
          <div className="stepcard">
            <Ruler size={18} color="var(--accent)" />
            <h3>Measured, not claimed</h3>
            <p>Digital phantoms with exact ground truth give alignment error in millimetres and SUV recovery per lesion. See the Validation page.</p>
          </div>
        </div>

        <h2>What the literature told us</h2>
        <div className="card" style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Paper</th>
                <th style={{ textAlign: "left" }}>Finding</th>
                <th style={{ textAlign: "left" }}>Used in FusionMap for</th>
              </tr>
            </thead>
            <tbody>
              {LIT.map(([p, f, u]) => (
                <tr key={p}>
                  <td style={{ minWidth: 200, verticalAlign: "top" }}>
                    <b>{p}</b>
                  </td>
                  <td style={{ textAlign: "left", verticalAlign: "top", color: "var(--text-2)" }}>{f}</td>
                  <td style={{ textAlign: "left", verticalAlign: "top" }}>{u}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>Cost and impact</h2>
        <div className="compare">
          <div className="card">
            <div className="sec">Hybrid PET-MRI scanner</div>
            <div className="big">$4–6 million</div>
            <div className="note">per site, plus installation and shielding</div>
          </div>
          <div className="card">
            <div className="sec">FusionMap build (team estimate)</div>
            <div className="big">₹40,000–60,000</div>
            <div className="note">mostly GPU compute for training; frameworks, TCIA datasets and tools are free</div>
          </div>
        </div>
        <p style={{ marginTop: 12 }}>
          Extending precision imaging from ~10 elite hospitals to 700+ oncology centres could improve treatment accuracy for the
          6–8 lakh cancer patients treated each year in India — fewer healthy cells damaged during radiotherapy, faster recovery,
          better outcomes. <span className="muted">(Team estimates.)</span>
        </p>

        <h2>Roadmap</h2>
        <div className="cards3">
          <div className="stepcard">
            <div className="n">NEXT</div>
            <h3>Fine-tune on real pairs</h3>
            <p>Brain, lung and prostate PET + MRI collections from The Cancer Imaging Archive; the training scripts take real NIfTI/DICOM pairs.</p>
          </div>
          <div className="stepcard">
            <div className="n">THEN</div>
            <h3>Body sites</h3>
            <p>Lung and prostate deform with breathing and bladder filling — the deformable stage carries the load; PSMA-PET for prostate.</p>
          </div>
          <div className="stepcard">
            <div className="n">LATER</div>
            <h3>Clinical pathway</h3>
            <p>PACS plug-in (OHIF extension), reader studies with nuclear medicine physicians, CDSCO software-as-a-medical-device route.</p>
          </div>
        </div>

        <h2>Team Code Blooded</h2>
        <div className="row wrap" style={{ gap: 10 }}>
          {["Atharva Jadhav", "Anushka Ghodekar", "Rohan Leo"].map((n) => (
            <span key={n} className="chip" style={{ fontSize: 13, padding: "6px 12px" }}>
              {n}
            </span>
          ))}
        </div>

        <p className="footer-note">
          FusionMap is a research prototype and not a medical device. It must not be used for diagnosis or treatment decisions.
          MNI ICBM152 2009a template © McConnell Brain Imaging Centre, Montreal Neurological Institute (used under its permissive licence).
        </p>
      </div>
    </div>
  );
}

function Flow({ t, d, c }: { t: string; d: string; c: string }) {
  return (
    <div style={{ flex: "1 1 150px", maxWidth: 200, border: "1px solid var(--border)", borderTop: `3px solid ${c}`, borderRadius: 10, padding: "10px 12px", background: "var(--panel-2)" }}>
      <div style={{ fontWeight: 700, fontSize: 13.5 }}>{t}</div>
      <div className="note" style={{ marginTop: 4 }}>
        {d}
      </div>
    </div>
  );
}
