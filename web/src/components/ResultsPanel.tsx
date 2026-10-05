import { AlertTriangle, CheckCircle2, Download, FileText, Network, Send, ShieldCheck, XCircle } from "lucide-react";
import { useState } from "react";
import { api, exportUrl } from "../api";
import { f1, f2, f3, KIND_LABEL, METHOD_LABEL, pct } from "../lib/format";
import type { CaseSummary, Health, Hotspot, Report } from "../types";
import { BarList, LineChart, PairedDots, ToleranceMeter } from "./charts";

type Tab = "overview" | "hotspots" | "registration" | "enhancement" | "export";
const TAB_LABEL: Record<Tab, string> = {
  overview: "Overview",
  hotspots: "Tumours",
  registration: "Align",
  enhancement: "Enhance",
  export: "Export",
};

interface Props {
  c: CaseSummary;
  health: Health | null;
  report: Report;
  selected: number | null;
  onSelect: (h: Hotspot) => void;
}

export function ResultsPanel({ c, health, report, selected, onSelect }: Props) {
  const [tab, setTab] = useState<Tab>("overview");
  const v = report.validation;
  return (
    <aside className="results">
      <div className="tabs" role="tablist">
        {(["overview", "hotspots", "registration", "enhancement", "export"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)} role="tab" aria-selected={tab === t}>
            {TAB_LABEL[t]}
          </button>
        ))}
      </div>
      {tab === "overview" && <Overview report={report} onSelect={onSelect} selected={selected} />}
      {tab === "hotspots" && <Hotspots report={report} onSelect={onSelect} selected={selected} />}
      {tab === "registration" && <Registration report={report} />}
      {tab === "enhancement" && <Enhancement report={report} />}
      {tab === "export" && <Export c={c} report={report} health={health} />}
      {!v && tab === "overview" && (
        <div className="section">
          <div className="alert info">
            Real patient: no ground truth exists, so accuracy is judged by ground-truth-free QA (mutual information, edge
            alignment). Validated accuracy figures come from the phantom benchmark on the Validation page.
          </div>
        </div>
      )}
    </aside>
  );
}

function Overview({ report, onSelect, selected }: { report: Report; onSelect: (h: Hotspot) => void; selected: number | null }) {
  const v = report.validation;
  const reg = report.registration;
  const spots = report.analysis.hotspots;
  return (
    <>
      <div className="hero-kpi">
        {v ? (
          <>
            <div className="lbl">PET ↔ MRI alignment error (target registration error, mean)</div>
            <div className="big num">
              <span className="from">{f1(v.tre_naive.mean_mm)}</span>
              <span className="arrow">→</span>
              {f2(v.tre_final.mean_mm)} <span style={{ fontSize: 20, fontWeight: 600 }}>mm</span>
            </div>
            <ToleranceMeter before={v.tre_naive.mean_mm} after={v.tre_final.mean_mm} tolerance={2} />
            <div className="note">
              {v.tre_final.p95_mm < 2 ? (
                <span className="status good">
                  <CheckCircle2 size={14} /> 95% of brain within {f2(v.tre_final.p95_mm)} mm — inside a 2 mm radiotherapy margin
                </span>
              ) : (
                <span className="status warn">
                  <AlertTriangle size={14} /> p95 {f2(v.tre_final.p95_mm)} mm — review alignment
                </span>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="lbl">Alignment quality (normalised mutual information)</div>
            <div className="big num">
              <span className="from">{f3(reg.nmi_before)}</span>
              <span className="arrow">→</span>
              {f3(reg.nmi_after)}
            </div>
            <div className="note">Higher = sharper joint MRI/PET histogram = better aligned anatomy.</div>
          </>
        )}
      </div>
      <div className="section">
        <div className="tiles">
          <div className="tile">
            <div className="lbl">PET tumour volumes</div>
            <div className="val num">{spots.length}</div>
            <div className="sub">TBR ≥ {report.analysis.tbr_threshold} vs background SUV {f2(report.analysis.background_suv)}</div>
          </div>
          <div className="tile">
            <div className="lbl">Highest SUVmax</div>
            <div className="val num">{spots.length ? f2(Math.max(...spots.map((s) => s.suv_max))) : "–"}</div>
            <div className="sub">{report.enhancement.method === "vit" ? "on AI-enhanced PET" : `on ${METHOD_LABEL[report.enhancement.method] ?? report.enhancement.method} PET`}</div>
          </div>
          {v ? (
            <>
              <div className="tile">
                <div className="lbl">Lesions detected</div>
                <div className="val num">
                  {v.detection.detected}/{v.detection.pet_positive_lesions}
                </div>
                <div className="sub">{v.detection.false_positives} false positive{v.detection.false_positives === 1 ? "" : "s"}</div>
              </div>
              <div className="tile">
                <div className="lbl">Image fidelity (PSNR)</div>
                <div className="val num">
                  {f1(v.quality_enhanced?.psnr_db ?? v.quality_registered.psnr_db)} dB
                </div>
                <div className="sub">from {f1(v.quality_registered.psnr_db)} dB before enhancement</div>
              </div>
            </>
          ) : (
            <>
              <div className="tile">
                <div className="lbl">Edge alignment</div>
                <div className="val num">{f3(reg.edge_alignment_after)}</div>
                <div className="sub">from {f3(reg.edge_alignment_before)}</div>
              </div>
              <div className="tile">
                <div className="lbl">Registration</div>
                <div className="val" style={{ fontSize: 15 }}>{METHOD_LABEL[reg.method] ?? reg.method}</div>
              </div>
            </>
          )}
          <div className="tile">
            <div className="lbl">Processing time</div>
            <div className="val num">{f1(report.total_seconds)} s</div>
            <div className="sub">CPU only · no GPU needed</div>
          </div>
          <div className="tile">
            <div className="lbl">Hardware cost</div>
            <div className="val">₹0</div>
            <div className="sub">vs $4–6 M hybrid PET-MRI</div>
          </div>
        </div>
      </div>
      {v && <LesionTruth report={report} />}
      {spots.length > 0 && (
        <div className="section">
          <h3>Tumour volumes</h3>
          <div className="stack">
            {spots.slice(0, 4).map((h) => (
              <HotspotRow key={h.id} h={h} on={selected === h.id} onClick={() => onSelect(h)} />
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function LesionTruth({ report }: { report: Report }) {
  const v = report.validation!;
  const rc = new Map(v.recovery_enhanced.map((r) => [r.id, r]));
  const hal = new Map(v.hallucination_enhanced.map((h) => [h.id, h]));
  const detected = v.detection.detected;
  return (
    <div className="section">
      <h3>Ground truth check</h3>
      <div className="stack">
        {v.phantom.lesions.map((l) => {
          const r = rc.get(l.id);
          const h = hal.get(l.id);
          const ok = l.kind === "mri_only" ? (h ? h.ratio < 1.25 : true) : Boolean(r);
          return (
            <div key={l.id} className="card" style={{ padding: "9px 11px" }}>
              <div className="row between">
                <b style={{ fontSize: 13 }}>Lesion {l.id}</b>
                <span className={`status ${ok ? "good" : "bad"}`}>
                  {ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                  {l.kind === "mri_only" ? (ok ? "correctly not flagged" : "false uptake") : ok ? "found" : "missed"}
                </span>
              </div>
              <div className="note">
                {KIND_LABEL[l.kind]} · {f1(l.volume_ml)} ml
                {r && ` · SUVmax ${f2(r.suv_measured)} vs true ${f2(r.suv_true)}`}
                {h && ` · mean SUV ${f2(h.suv_measured_mean)} vs true ${f2(h.suv_true_mean)}`}
              </div>
            </div>
          );
        })}
        <div className="note">
          {detected}/{v.detection.pet_positive_lesions} PET-positive lesions detected. The MRI-only radionecrosis tests that the
          AI takes <i>uptake</i> from PET and only <i>edges</i> from MRI.
        </div>
      </div>
    </div>
  );
}

function HotspotRow({ h, on, onClick }: { h: Hotspot; on: boolean; onClick: () => void }) {
  return (
    <button className={`hs ${on ? "on" : ""}`} onClick={onClick}>
      <div className="badge">{h.id}</div>
      <div>
        <div style={{ fontWeight: 600 }}>
          SUVmax <span className="num">{f2(h.suv_max)}</span> · TBR <span className="num">{f2(h.tbr_max)}</span>
        </div>
        <div className="note num">
          {h.side} · MTV {f2(h.mtv_ml)} ml · SUVpeak {f2(h.suv_peak)}
        </div>
      </div>
      <span className="note">go →</span>
    </button>
  );
}

function Hotspots({ report, onSelect, selected }: { report: Report; onSelect: (h: Hotspot) => void; selected: number | null }) {
  const spots = report.analysis.hotspots;
  return (
    <div className="section">
      <h3>PET biological tumour volumes</h3>
      <p className="note" style={{ marginTop: 0 }}>
        Threshold TBR ≥ {report.analysis.tbr_threshold} (RANO / EANO / EANM biological tumour volume criterion for amino-acid
        PET) against background SUV {f2(report.analysis.background_suv)}. Exported as an RT-STRUCT for treatment planning.
      </p>
      <div className="stack">
        {spots.length === 0 && <div className="note">No uptake above threshold.</div>}
        {spots.map((h) => (
          <HotspotRow key={h.id} h={h} on={selected === h.id} onClick={() => onSelect(h)} />
        ))}
      </div>
      {spots.length > 0 && (
        <table className="table" style={{ marginTop: 12 }}>
          <thead>
            <tr>
              <th>#</th>
              <th>SUVmax</th>
              <th>SUVmean</th>
              <th>MTV ml</th>
              <th>TLG</th>
            </tr>
          </thead>
          <tbody>
            {spots.map((h) => (
              <tr key={h.id}>
                <td>{h.id}</td>
                <td>{f2(h.suv_max)}</td>
                <td>{f2(h.suv_mean)}</td>
                <td>{f2(h.mtv_ml)}</td>
                <td>{f1(h.tlg)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Registration({ report }: { report: Report }) {
  const r = report.registration;
  const v = report.validation;
  return (
    <>
      <div className="section">
        <h3>Step 1 · {METHOD_LABEL[r.method] ?? r.method}</h3>
        <dl className="kv">
          {r.rigid && (
            <>
              <dt>Rotation (x, y, z)</dt>
              <dd>{r.rigid.rotation_deg.map((a) => f2(a)).join(", ")}°</dd>
              <dt>Translation</dt>
              <dd>{r.rigid.translation_mm.map((a) => f1(a)).join(", ")} mm</dd>
              <dt>Rigid MI time</dt>
              <dd>
                {f2(r.rigid.seconds)} s · {r.rigid.iterations} it
              </dd>
            </>
          )}
          {r.deformable && (
            <>
              <dt>Deformable</dt>
              <dd>{r.deformable.model}</dd>
              <dt>Deformable time</dt>
              <dd>{f2(r.deformable.seconds)} s</dd>
              {r.deformable.max_displacement_mm != null && (
                <>
                  <dt>Max / mean warp</dt>
                  <dd>
                    {f2(r.deformable.max_displacement_mm)} / {f2(r.deformable.mean_displacement_mm)} mm
                  </dd>
                </>
              )}
              {r.deformable.min_jacobian != null && (
                <>
                  <dt>Min Jacobian</dt>
                  <dd>
                    {f3(r.deformable.min_jacobian)}{" "}
                    {r.deformable.min_jacobian > 0 ? (
                      <span className="status good">
                        <ShieldCheck size={13} /> no folding
                      </span>
                    ) : (
                      <span className="status bad">folding</span>
                    )}
                  </dd>
                </>
              )}
            </>
          )}
          <dt>NMI (GT-free)</dt>
          <dd>
            {f3(r.nmi_before)} → <b>{f3(r.nmi_after)}</b>
          </dd>
          <dt>Edge alignment</dt>
          <dd>
            {f3(r.edge_alignment_before)} → <b>{f3(r.edge_alignment_after)}</b>
          </dd>
        </dl>
      </div>
      {r.mi_trace && r.mi_trace.length > 2 && (
        <div className="section">
          <h3>Mutual information during optimisation</h3>
          <LineChart values={r.mi_trace} yLabel="Mattes MI" />
          <div className="note">Multi-resolution (coarse → fine) gradient descent; jumps mark pyramid levels.</div>
        </div>
      )}
      {v && (
        <div className="section">
          <h3>Target registration error (vs truth)</h3>
          <BarList
            unit=" mm"
            data={[
              { label: "Naive overlay", value: v.tre_naive.mean_mm },
              { label: "Rigid MI", value: v.tre_rigid.mean_mm },
              { label: METHOD_LABEL[r.method] ?? "Final", value: v.tre_final.mean_mm, emphasis: true },
            ]}
          />
          <dl className="kv" style={{ marginTop: 10 }}>
            <dt>Final p95 / max</dt>
            <dd>
              {f2(v.tre_final.p95_mm)} / {f2(v.tre_final.max_mm)} mm
            </dd>
            <dt>At lesion centres</dt>
            <dd>{v.tre_final.lesion_mm.map((x) => f2(x)).join(", ")} mm</dd>
            <dt>Simulated mismatch</dt>
            <dd>
              {v.phantom.misalignment.rotation_deg.map((x) => f1(x)).join(", ")}° ·{" "}
              {v.phantom.misalignment.translation_mm.map((x) => f1(x)).join(", ")} mm
            </dd>
          </dl>
        </div>
      )}
    </>
  );
}

function Enhancement({ report }: { report: Report }) {
  const e = report.enhancement;
  const v = report.validation;
  const pairs =
    v?.recovery_registered.map((r) => {
      const after = v.recovery_enhanced.find((x) => x.id === r.id);
      return { label: `Lesion ${r.id}`, a: r.rc, b: after?.rc ?? r.rc };
    }) ?? [];
  return (
    <>
      <div className="section">
        <h3>Step 2 · {METHOD_LABEL[e.method] ?? e.method}</h3>
        <p className="note" style={{ marginTop: 0 }}>
          {e.method === "vit"
            ? "Hybrid CNN / Vision-Transformer U-Net reads the blurry PET together with the MRI (three neighbouring slices each) and predicts the sharp PET. Uptake comes from PET, edges from MRI."
            : e.method === "deconv"
              ? "Richardson–Lucy deconvolution with the scanner point-spread function, then an MRI-guided edge-preserving filter."
              : "PET left as acquired (registered only)."}
        </p>
        {e.seconds != null && (
          <dl className="kv">
            <dt>Time</dt>
            <dd>{f2(e.seconds)} s</dd>
            {e.model && (
              <>
                <dt>Model</dt>
                <dd style={{ textAlign: "right" }}>{e.model}</dd>
              </>
            )}
          </dl>
        )}
      </div>
      {v && v.quality_enhanced && (
        <div className="section">
          <h3>Fidelity vs ideal PET</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Registered</th>
                <th>Enhanced</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>PSNR (dB) ↑</td>
                <td>{f2(v.quality_registered.psnr_db)}</td>
                <td>
                  <b>{f2(v.quality_enhanced.psnr_db)}</b>
                </td>
              </tr>
              <tr>
                <td>SSIM ↑</td>
                <td>{f3(v.quality_registered.ssim)}</td>
                <td>
                  <b>{f3(v.quality_enhanced.ssim)}</b>
                </td>
              </tr>
              <tr>
                <td>NMAE ↓</td>
                <td>{f3(v.quality_registered.nmae)}</td>
                <td>
                  <b>{f3(v.quality_enhanced.nmae)}</b>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {pairs.length > 0 && (
        <div className="section">
          <h3>Lesion SUVmax recovery</h3>
          <PairedDots data={pairs} aLabel="Registered" bLabel="Enhanced" refLabel="truth" />
          <div className="note">
            Recovery coefficient = measured SUVmax / true SUVmax. Blur spills small-lesion uptake into its surroundings
            (partial-volume effect); 1.0 is perfect.
          </div>
        </div>
      )}
      {v && v.hallucination_enhanced.length > 0 && (
        <div className="section">
          <h3>Hallucination check</h3>
          {v.hallucination_enhanced.map((h) => {
            const before = v.hallucination_registered.find((x) => x.id === h.id);
            return (
              <div key={h.id} className="note" style={{ marginBottom: 6 }}>
                Radionecrosis lesion {h.id} (MRI-visible, PET-cold): mean SUV {f2(h.suv_measured_mean)} vs true{" "}
                {f2(h.suv_true_mean)} (ratio {f2(h.ratio)}; registered only {f2(before?.ratio)}).{" "}
                {h.ratio < 1.25 ? (
                  <span className="status good">
                    <CheckCircle2 size={13} /> no uptake invented
                  </span>
                ) : (
                  <span className="status bad">
                    <XCircle size={13} /> false uptake
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
      {v && <div className="section note">Detection sensitivity {pct(v.detection.sensitivity)} · Dice {f2(v.detection.mean_dice)}</div>}
    </>
  );
}

function Export({ c, report, health }: { c: CaseSummary; report: Report; health: Health | null }) {
  const pd = health?.pacs_default;
  const [host, setHost] = useState(pd?.host ?? "127.0.0.1");
  const [port, setPort] = useState(pd?.port ?? 4242);
  const [aet, setAet] = useState(pd?.called_aet ?? "ORTHANC");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const ex = report.export;
  const body = { host, port, called_aet: aet, calling_aet: "FUSIONMAP" };
  return (
    <>
      <div className="section">
        <h3>Step 3 · Clinical outputs</h3>
        <div className="stack">
          <a className="btn primary" href={exportUrl(c.id, "dicom.zip")} download>
            <Download size={15} /> DICOM bundle (.zip{ex ? `, ${f1(ex.size_mb)} MB` : ""})
          </a>
          <a className="btn" href={exportUrl(c.id, "report.html")} target="_blank" rel="noreferrer">
            <FileText size={15} /> Printable case report
          </a>
          <div className="grid2">
            <a className="btn sm" href={exportUrl(c.id, "pet.nii.gz")} download>
              PET NIfTI
            </a>
            <a className="btn sm" href={exportUrl(c.id, "mri.nii.gz")} download>
              MRI NIfTI
            </a>
          </div>
        </div>
      </div>
      {ex && (
        <div className="section">
          <h3>Bundle contents</h3>
          <dl className="kv">
            <dt>MR</dt>
            <dd>{ex.slices} slices · reference grid</dd>
            <dt>PET_REG</dt>
            <dd>registered PET · SUVbw</dd>
            <dt>PET_AI</dt>
            <dd>{ex.series.PET_AI ? "AI-enhanced PET · SUVbw" : "—"}</dd>
            <dt>FUSED</dt>
            <dd>colour fusion · RGB</dd>
            <dt>RTSTRUCT</dt>
            <dd>{ex.rtstruct_contours} contours</dd>
          </dl>
          <div className="note" style={{ marginTop: 8 }}>
            All series share one Study and Frame of Reference, so any PACS viewer or planning system links them.
          </div>
          <div className="mono muted" style={{ marginTop: 6, wordBreak: "break-all" }}>
            FoR {ex.frame_of_reference_uid}
          </div>
        </div>
      )}
      <div className="section">
        <h3>
          <Network size={12} style={{ verticalAlign: -1 }} /> Send to PACS (DICOM C-STORE)
        </h3>
        <div className="stack">
          <div className="grid2">
            <label className="field">
              Host
              <input className="input" value={host} onChange={(e) => setHost(e.target.value)} />
            </label>
            <label className="field">
              Port
              <input className="input num" type="number" value={port} onChange={(e) => setPort(+e.target.value)} />
            </label>
          </div>
          <label className="field">
            Called AE title
            <input className="input" value={aet} onChange={(e) => setAet(e.target.value)} />
          </label>
          <div className="grid2">
            <button
              className="btn sm"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const r = await api.pacsEcho(body);
                  setMsg({ ok: r.ok, text: r.ok ? "C-ECHO succeeded" : `C-ECHO failed ${r.error ?? ""}` });
                } catch (e) {
                  setMsg({ ok: false, text: String(e) });
                }
                setBusy(false);
              }}
            >
              Test (C-ECHO)
            </button>
            <button
              className="btn sm primary"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const r = await api.pacsPush(c.id, body);
                  setMsg({ ok: r.ok, text: r.ok ? `Sent ${r.sent}/${r.total} instances` : r.error ?? `sent ${r.sent}/${r.total}` });
                } catch (e) {
                  setMsg({ ok: false, text: String(e) });
                }
                setBusy(false);
              }}
            >
              <Send size={13} /> Send
            </button>
          </div>
          {msg && <div className={`alert ${msg.ok ? "info" : "err"}`}>{msg.text}</div>}
          {msg?.ok && pd?.viewer_url && (
            <a className="btn sm" href={pd.viewer_url} target="_blank" rel="noreferrer">
              Open in PACS viewer ↗
            </a>
          )}
          <div className="note">Works with Orthanc, dcm4chee or any DICOM storage SCP.</div>
        </div>
      </div>
    </>
  );
}
