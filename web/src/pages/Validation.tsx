import { useEffect, useState } from "react";
import { api } from "../api";
import { BarList, PairedDots } from "../components/charts";
import { f1, f2, f3, METHOD_LABEL, pct } from "../lib/format";
import type { Health } from "../types";

interface Agg {
  mean: number;
  std: number;
  median: number;
  n: number;
}
interface Bench {
  date: string;
  cases: number;
  seeds: [number, number];
  machine: string;
  wall_seconds: number;
  summary: {
    registration: Record<string, { tre_mean_mm: Agg; tre_p95_mm: Agg; lesion_tre_mm: Agg | null; seconds: Agg; cases_under_2mm: number }>;
    enhancement: Record<
      string,
      {
        psnr_db: Agg;
        ssim: Agg;
        nmae: Agg;
        lesion_rc: Agg | null;
        lesion_rc_abs_error: Agg | null;
        hallucination_ratio: Agg | null;
        sensitivity: number;
        false_positives_per_case: number;
        seconds: Agg;
      }
    >;
  };
  per_case: {
    seed: number;
    tracer: string;
    lesions: string[];
    reg: Record<string, { tre_mean_mm: number; seconds: number }>;
    enh: Record<string, { psnr_db: number; ssim: number }>;
  }[];
}

const REG_ORDER = ["naive", "rigid", "rigid+bspline", "rigid+voxelmorph"];
const ENH_ORDER = ["none", "deconv", "vit"];

export function Validation({ health }: { health: Health | null }) {
  const [b, setB] = useState<Bench | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api
      .benchmark()
      .then((d) => setB(d as unknown as Bench))
      .catch((e) => setErr(String(e)));
  }, []);

  const reg = b?.summary.registration ?? {};
  const enh = b?.summary.enhancement ?? {};
  const regKeys = REG_ORDER.filter((k) => reg[k]);
  const enhKeys = ENH_ORDER.filter((k) => enh[k]);
  // highlight what the pipeline actually runs: VoxelMorph only when its validation gate passes
  const bestReg = health?.models.voxelmorph.used_by_auto && reg["rigid+voxelmorph"] ? "rigid+voxelmorph" : reg.rigid ? "rigid" : regKeys[0];
  const bestEnh = enhKeys.filter((k) => k !== "none").sort((a, c) => enh[c].psnr_db.mean - enh[a].psnr_db.mean)[0];

  return (
    <div className="page">
      <div className="page-inner">
        <h1>Validation on held-out simulated patients</h1>
        <p className="lead">
          Real PET/MRI pairs with a <i>known</i> correct alignment do not exist, which is exactly the problem FusionMap solves.
          So we validate the way PET physicists do: digital patients built from the MNI152 brain with tumours, scanner blur,
          noise and a different head pose in each scanner. Because we created the mismatch, we can measure the error in
          millimetres.
        </p>
        {err && (
          <div className="alert err" style={{ marginTop: 16 }}>
            No benchmark yet — run <code className="mono">fusionmap benchmark --cases 12</code>. ({err})
          </div>
        )}
        {b && bestReg && (
          <>
            <div className="compare" style={{ marginTop: 22 }}>
              <div className="card">
                <div className="sec">Mean alignment error, {b.cases} patients</div>
                <div className="big num">
                  {f1(reg.naive?.tre_mean_mm.mean)} mm <span className="muted">→</span> {f2(reg[bestReg].tre_mean_mm.mean)} mm
                </div>
                <div className="note">
                  {METHOD_LABEL[bestReg]} · {pct(reg[bestReg].cases_under_2mm)} of patients with 95th-percentile error under 2 mm
                </div>
              </div>
              {bestEnh && (
                <div className="card">
                  <div className="sec">PET fidelity vs ideal (PSNR)</div>
                  <div className="big num">
                    {f1(enh.none?.psnr_db.mean)} dB <span className="muted">→</span> {f1(enh[bestEnh].psnr_db.mean)} dB
                  </div>
                  <div className="note">
                    {METHOD_LABEL[bestEnh]} · SSIM {f3(enh.none?.ssim.mean)} → {f3(enh[bestEnh].ssim.mean)} · lesion detection{" "}
                    {pct(enh[bestEnh].sensitivity)}
                  </div>
                </div>
              )}
            </div>

            <h2>Step 1 — registration accuracy</h2>
            <div className="cards2">
              <div className="card">
                <h4 style={{ fontSize: 14, marginBottom: 2 }}>Target registration error (mean over brain, mm)</h4>
                <div className="note" style={{ marginBottom: 8 }}>Bars = mean across patients, whiskers = ±1 SD. Lower is better.</div>
                <BarList
                  unit=" mm"
                  data={regKeys.map((k) => ({
                    label: METHOD_LABEL[k],
                    value: reg[k].tre_mean_mm.mean,
                    err: reg[k].tre_mean_mm.std,
                    emphasis: k === bestReg,
                  }))}
                />
              </div>
              <div className="card">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Method</th>
                      <th>Mean</th>
                      <th>p95</th>
                      <th>At lesions</th>
                      <th>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {regKeys.map((k) => (
                      <tr key={k} className={k === bestReg ? "best" : ""}>
                        <td>{METHOD_LABEL[k]}</td>
                        <td>{f2(reg[k].tre_mean_mm.mean)}</td>
                        <td>{f2(reg[k].tre_p95_mm.mean)}</td>
                        <td>{f2(reg[k].lesion_tre_mm?.mean)}</td>
                        <td>{f1(reg[k].seconds.mean)} s</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="note">
                  The brain is nearly rigid, so mutual-information rigid alignment does the work (Nensa et al., 2014). The learned
                  VoxelMorph stage matches it but does not beat it on these phantoms (the residual ~1 mm is below PET resolution), so
                  the default pipeline runs rigid MI; B-spline over-fits PET noise. All errors in millimetres.
                </p>
              </div>
            </div>

            <h2>Step 2 — PET enhancement</h2>
            <div className="card">
              <table className="table">
                <thead>
                  <tr>
                    <th>Method</th>
                    <th>PSNR dB ↑</th>
                    <th>SSIM ↑</th>
                    <th>NMAE ↓</th>
                    <th>Lesion RC (1 = ideal)</th>
                    <th>|RC − 1| ↓</th>
                    <th>Radionecrosis ratio (1 = ideal)</th>
                    <th>Sensitivity</th>
                    <th>FP / patient</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {enhKeys.map((k) => {
                    const e = enh[k];
                    return (
                      <tr key={k} className={k === bestEnh ? "best" : ""}>
                        <td>{METHOD_LABEL[k]}</td>
                        <td>{f2(e.psnr_db.mean)}</td>
                        <td>{f3(e.ssim.mean)}</td>
                        <td>{f3(e.nmae.mean)}</td>
                        <td>
                          {f2(e.lesion_rc?.mean)} ± {f2(e.lesion_rc?.std)}
                        </td>
                        <td>{f3(e.lesion_rc_abs_error?.mean)}</td>
                        <td>{f2(e.hallucination_ratio?.mean)}</td>
                        <td>{pct(e.sensitivity)}</td>
                        <td>{f2(e.false_positives_per_case)}</td>
                        <td>{f1(e.seconds.mean)} s</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="note">
                RC = measured / true lesion SUVmax: scanner blur makes small tumours look colder (RC &lt; 1). The radionecrosis ratio
                checks that enhancement does not invent uptake in MRI-visible but PET-negative tissue. Metrics follow the MRI→PET
                synthesis literature (SSIM / PSNR / MAE: Chen et al. 2025; Plasma-CycleGAN 2024).
              </p>
            </div>

            <h2>Per patient</h2>
            <div className="cards2" style={{ marginBottom: 12 }}>
              <div className="card">
                <h4 style={{ fontSize: 14, marginBottom: 6 }}>Alignment error per patient (mm)</h4>
                <PairedDots
                  data={b.per_case.map((c) => ({ label: `#${c.seed}`, a: c.reg.naive?.tre_mean_mm ?? 0, b: c.reg[bestReg]?.tre_mean_mm ?? 0 }))}
                  aLabel="No registration"
                  bLabel={METHOD_LABEL[bestReg]}
                  reference={2}
                  refLabel="2 mm margin"
                  digits={2}
                />
              </div>
              {bestEnh && (
                <div className="card">
                  <h4 style={{ fontSize: 14, marginBottom: 6 }}>PET fidelity per patient (PSNR, dB)</h4>
                  <PairedDots
                    data={b.per_case.map((c) => ({ label: `#${c.seed}`, a: c.enh.none?.psnr_db ?? 0, b: c.enh[bestEnh]?.psnr_db ?? 0 }))}
                    aLabel="Registered PET"
                    bLabel={METHOD_LABEL[bestEnh]}
                    reference={30}
                    refLabel="30 dB"
                    digits={1}
                  />
                </div>
              )}
            </div>
            <div className="card" style={{ overflowX: "auto" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Seed</th>
                    <th>Tracer</th>
                    <th>Lesions</th>
                    {regKeys.map((k) => (
                      <th key={k}>TRE {METHOD_LABEL[k]}</th>
                    ))}
                    {enhKeys.map((k) => (
                      <th key={k}>PSNR {METHOD_LABEL[k]}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.per_case.map((c) => (
                    <tr key={c.seed}>
                      <td>{c.seed}</td>
                      <td>{c.tracer.toUpperCase()}</td>
                      <td style={{ textAlign: "right" }}>{c.lesions.map((l) => (l === "active" ? "V" : l === "pet_only" ? "O" : "N")).join(" ")}</td>
                      {regKeys.map((k) => (
                        <td key={k}>{f2(c.reg[k]?.tre_mean_mm)}</td>
                      ))}
                      {enhKeys.map((k) => (
                        <td key={k}>{f2(c.enh[k]?.psnr_db)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="note">Lesions: V viable · O MRI-occult · N radionecrosis. Seeds ≥ 1000 never seen in training.</p>
            </div>
            <p className="footer-note">
              Benchmark run {b.date} on {b.machine}, {b.cases} patients (seeds {b.seeds[0]}–{b.seeds[1]}), {f1(b.wall_seconds / 60)} min
              wall time on CPU.
            </p>
          </>
        )}

        <h2>The AI models</h2>
        <div className="cards2">
          {(["voxelmorph", "enhancer"] as const).map((k) => {
            const m = health?.models[k];
            const card = m?.card;
            return (
              <div className="card" key={k}>
                <h4 style={{ fontSize: 15 }}>{card?.name ?? (k === "voxelmorph" ? "VoxelMorph" : "ViT-hybrid enhancer")}</h4>
                {card ? (
                  <>
                    <p className="note">{card.architecture}</p>
                    <dl className="kv">
                      <dt>Parameters</dt>
                      <dd>{card.parameters.toLocaleString()}</dd>
                      {Object.entries(card.training)
                        .filter(([, v]) => typeof v !== "object")
                        .slice(0, 5)
                        .map(([key, v]) => (
                          <FragmentRow key={key} k={key} v={String(v)} />
                        ))}
                    </dl>
                  </>
                ) : (
                  <p className="note">Not trained in this deployment — the pipeline falls back to the classical method.</p>
                )}
              </div>
            );
          })}
        </div>

        <h2>Limitations — read before trusting a number</h2>
        <ul className="sec" style={{ maxWidth: 820 }}>
          <li>All quantitative results are on simulated brain phantoms derived from one population template (MNI152). Real patients vary more.</li>
          <li>The AI models were trained on CPU in minutes on simulated data; production use requires fine-tuning on paired clinical data (e.g. TCIA) and prospective validation.</li>
          <li>Body sites (lung, prostate) deform far more than the brain; the deformable stage would carry much more of the load there.</li>
          <li>FusionMap is a research prototype. It is not a medical device and must not be used for diagnosis or treatment planning.</li>
        </ul>
      </div>
    </div>
  );
}

function FragmentRow({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt>{k.replace(/_/g, " ")}</dt>
      <dd>{v}</dd>
    </>
  );
}
