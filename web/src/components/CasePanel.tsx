import { Check, Dices, FileUp, Loader2, Play, Trash2, X } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "../api";
import { ago } from "../lib/format";
import type { CaseSummary, Health, StepState } from "../types";

const STEP_ORDER = [
  ["simulate", "Load / simulate patient"],
  ["load", "Standardise to 1 mm grid"],
  ["register", "Register PET → MRI"],
  ["enhance", "Enhance PET (AI)"],
  ["fuse", "Fuse & analyse"],
  ["export", "Export DICOM + RT-STRUCT"],
  ["validate", "Validate vs ground truth"],
] as const;

export function Stepper({ steps, status }: { steps: Record<string, StepState>; status?: string }) {
  return (
    <div className="steps" aria-live="polite">
      {STEP_ORDER.map(([key, fallback]) => {
        const s = steps[key];
        const st = s?.status ?? (status === "done" ? "skipped" : "pending");
        return (
          <div key={key} className={`step ${st}`}>
            <div className="ic">
              {st === "done" ? <Check size={12} strokeWidth={3} /> : st === "running" ? <Loader2 size={12} className="spin" /> : st === "error" ? <X size={12} /> : null}
            </div>
            <div style={{ minWidth: 0 }}>
              <div className="t">{s?.label && key !== "simulate" ? s.label : fallback}</div>
              {st === "running" && (
                <>
                  <div className="m" title={s?.message ?? ""}>{s?.message || "working…"}</div>
                  <div className="bar">
                    <div style={{ width: `${Math.round((s?.progress ?? 0.05) * 100)}%` }} />
                  </div>
                </>
              )}
              {st === "skipped" && s?.message && <div className="m">{s.message}</div>}
            </div>
            <div className="s num">{s?.seconds != null ? `${s.seconds.toFixed(1)}s` : ""}</div>
          </div>
        );
      })}
    </div>
  );
}

interface Props {
  health: Health | null;
  cases: CaseSummary[];
  current: CaseSummary | null;
  steps: Record<string, StepState>;
  onCreated: (c: CaseSummary) => void;
  onSelect: (id: string) => void;
  onDeleted: (id: string) => void;
  error: string | null;
}

export function CasePanel({ health, cases, current, steps, onCreated, onSelect, onDeleted, error }: Props) {
  const [tab, setTab] = useState<"demo" | "upload">("demo");
  const [seed, setSeed] = useState(7);
  const [tracer, setTracer] = useState("fdg");
  const [mix, setMix] = useState("showcase");
  const [severity, setSeverity] = useState(1);
  const [registration, setRegistration] = useState("auto");
  const [enhancement, setEnhancement] = useState("auto");
  const [mri, setMri] = useState<File | null>(null);
  const [pet, setPet] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const running = current?.status === "running" || current?.status === "queued";
  const vxmOk = health?.models.voxelmorph.available;
  const aiOk = health?.models.enhancer.available;
  const options = { registration, enhancement };

  const runDemo = async () => {
    setBusy(true);
    setErr(null);
    try {
      const c = await api.createDemo({
        seed,
        tracer,
        lesion_mix: mix,
        n_lesions: mix === "showcase" ? 3 : null,
        rotation_deg: 7 * severity,
        translation_mm: 12 * severity,
        options,
      });
      onCreated(c);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  const runUpload = async () => {
    if (!mri || !pet) return;
    setBusy(true);
    setErr(null);
    try {
      onCreated(await api.upload(mri, pet, options, `${mri.name.split(".")[0]} + ${pet.name.split(".")[0]}`));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="side">
      <div className="section">
        <div className="seg" style={{ width: "100%", display: "grid", gridTemplateColumns: "1fr 1fr" }}>
          <button className={tab === "demo" ? "on" : ""} onClick={() => setTab("demo")}>
            <Dices size={13} style={{ verticalAlign: -2, marginRight: 5 }} />
            Demo patient
          </button>
          <button className={tab === "upload" ? "on" : ""} onClick={() => setTab("upload")}>
            <FileUp size={13} style={{ verticalAlign: -2, marginRight: 5 }} />
            Upload scans
          </button>
        </div>
        {tab === "demo" ? (
          <div className="stack" style={{ marginTop: 12 }}>
            <p className="note" style={{ margin: 0 }}>
              A simulated patient from the MNI152 brain: tumours, PET physics and a different head position in each
              scanner. The exact truth is known, so every number is measurable.
            </p>
            <div className="grid2">
              <label className="field">
                Patient seed
                <div className="row">
                  <input className="input num" type="number" value={seed} min={0} onChange={(e) => setSeed(+e.target.value)} />
                  <button className="btn icon" title="Random patient" onClick={() => setSeed(Math.floor(Math.random() * 9000) + 100)}>
                    <Dices size={14} />
                  </button>
                </div>
              </label>
              <label className="field">
                Tracer
                <select className="input" value={tracer} onChange={(e) => setTracer(e.target.value)}>
                  <option value="fdg">18F-FDG</option>
                  <option value="fet">18F-FET (amino acid)</option>
                </select>
              </label>
            </div>
            <label className="field">
              Lesions
              <select className="input" value={mix} onChange={(e) => setMix(e.target.value)}>
                <option value="showcase">Showcase: viable + MRI-occult + radionecrosis</option>
                <option value="active">Viable tumours only</option>
                <option value="mixed">Random mix</option>
              </select>
            </label>
            <label className="field">
              <span className="row between">
                <span>Head-position mismatch</span>
                <span className="num muted">±{(7 * severity).toFixed(0)}° · ±{(12 * severity).toFixed(0)} mm</span>
              </span>
              <input type="range" min={0.25} max={2} step={0.25} value={severity} onChange={(e) => setSeverity(+e.target.value)} />
            </label>
          </div>
        ) : (
          <div className="stack" style={{ marginTop: 12 }}>
            <p className="note" style={{ margin: 0 }}>
              Upload a <b>.zip of DICOM files</b> or a <b>.nii/.nii.gz</b> for each scanner. PET DICOM in Bq/ml is converted to
              SUV from the radiopharmaceutical tags.
            </p>
            <FilePick label="MRI (T1 / T1+Gd)" file={mri} setFile={setMri} />
            <FilePick label="PET" file={pet} setFile={setPet} />
            <p className="note" style={{ margin: 0 }}>
              No scans handy? <code className="mono">fusionmap phantom --dicom</code> writes a hospital-style pair.
            </p>
          </div>
        )}
      </div>

      <div className="section">
        <h3>Pipeline</h3>
        <div className="stack">
          <label className="field">
            Step 1 · Registration
            <select className="input" value={registration} onChange={(e) => setRegistration(e.target.value)}>
              <option value="auto">Auto ({vxmOk ? "Rigid MI + VoxelMorph" : "Rigid MI + B-spline"})</option>
              <option value="rigid+voxelmorph" disabled={!vxmOk}>
                Rigid MI + VoxelMorph (AI)
              </option>
              <option value="rigid+bspline">Rigid MI + B-spline</option>
              <option value="rigid">Rigid MI only</option>
              <option value="none">None (naive overlay)</option>
            </select>
          </label>
          <label className="field">
            Step 2 · PET enhancement
            <select className="input" value={enhancement} onChange={(e) => setEnhancement(e.target.value)}>
              <option value="auto">Auto ({aiOk ? "ViT-hybrid AI" : "Deconvolution"})</option>
              <option value="vit" disabled={!aiOk}>
                ViT-hybrid U-Net (AI, MRI-guided)
              </option>
              <option value="deconv">Richardson–Lucy + MRI-guided filter</option>
              <option value="none">None</option>
            </select>
          </label>
          <button
            className="btn hero"
            disabled={busy || running || (tab === "upload" && (!mri || !pet))}
            onClick={tab === "demo" ? runDemo : runUpload}
          >
            {busy || running ? <Loader2 size={16} className="spin" /> : <Play size={16} />}
            {running ? "Running FusionMap…" : "Run FusionMap"}
          </button>
          {(err || error) && <div className="alert err">{err || error}</div>}
        </div>
      </div>

      {current && (
        <div className="section">
          <h3>Progress</h3>
          <Stepper steps={steps} status={current.status} />
          {current.report?.total_seconds != null && current.status === "done" && (
            <div className="note" style={{ marginTop: 8 }}>
              Finished in <b className="num">{current.report.total_seconds.toFixed(1)} s</b> on CPU.
            </div>
          )}
        </div>
      )}

      <div className="section">
        <h3>Recent cases</h3>
        {cases.length === 0 && <div className="note">No cases yet.</div>}
        <div className="stack" style={{ gap: 2 }}>
          {cases.slice(0, 12).map((c) => (
            <div key={c.id} className={`case-item ${current?.id === c.id ? "on" : ""}`} onClick={() => onSelect(c.id)}>
              <div className="n">{c.name}</div>
              <button
                className="btn ghost icon sm"
                title="Delete case"
                onClick={(e) => {
                  e.stopPropagation();
                  api.deleteCase(c.id).then(() => onDeleted(c.id));
                }}
              >
                <Trash2 size={13} />
              </button>
              <div className="d">
                {c.status === "done" ? "✓ complete" : c.status} · {ago(c.created)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}

function FilePick({ label, file, setFile }: { label: string; file: File | null; setFile: (f: File | null) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      className={`dropzone ${over ? "over" : ""} ${file ? "has" : ""}`}
      onClick={() => ref.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files?.[0];
        if (f) setFile(f);
      }}
    >
      <input ref={ref} type="file" hidden accept=".zip,.nii,.gz,.mha,.nrrd" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      <b>{label}</b>
      <div className="note">{file ? `${file.name} · ${(file.size / 1e6).toFixed(1)} MB` : "drop a .zip / .nii.gz or click"}</div>
    </div>
  );
}
