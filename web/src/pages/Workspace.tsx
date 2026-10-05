import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { CasePanel } from "../components/CasePanel";
import { ResultsPanel } from "../components/ResultsPanel";
import { Viewer } from "../components/Viewer";
import { useLiveCase, useViewerData } from "../hooks/useCase";
import type { CaseSummary, Colormaps, Health, Hotspot } from "../types";

export function Workspace({ health, colormaps }: { health: Health | null; colormaps: Colormaps | null }) {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [caseId, setCaseId] = useState<string | null>(() => new URLSearchParams(location.hash.split("?")[1]).get("case"));
  const [selected, setSelected] = useState<number | null>(null);
  const [jump, setJump] = useState<{ zyx: [number, number, number]; n: number } | null>(null);
  const live = useLiveCase(caseId);
  const done = live.data?.status === "done" && Boolean(live.data?.report);
  const viewer = useViewerData(caseId, done, live.data?.finished ?? 0);

  const reloadCases = useCallback(() => {
    api.cases().then(setCases).catch(() => undefined);
  }, []);
  useEffect(reloadCases, [reloadCases, live.data?.status]);
  useEffect(() => {
    if (!caseId && cases.length) {
      const firstDone = cases.find((c) => c.status === "done");
      if (firstDone) setCaseId(firstDone.id);
    }
  }, [cases, caseId]);
  useEffect(() => {
    if (caseId) history.replaceState(null, "", `#/workspace?case=${caseId}`);
    setSelected(null);
  }, [caseId]);

  const selectHotspot = (h: Hotspot) => {
    setSelected(h.id);
    setJump({ zyx: h.peak_index_zyx, n: Date.now() });
  };

  const report = live.data?.report ?? null;
  return (
    <div className="workspace">
      <CasePanel
        health={health}
        cases={cases}
        current={live.data}
        steps={live.steps}
        error={live.error}
        onCreated={(c) => {
          setCaseId(c.id);
          reloadCases();
        }}
        onSelect={setCaseId}
        onDeleted={(id) => {
          if (id === caseId) setCaseId(null);
          reloadCases();
        }}
      />
      <main className="center">
        {viewer.data && report && caseId ? (
          <Viewer
            key={caseId + (live.data?.finished ?? "")}
            caseId={caseId}
            viewer={viewer.data}
            report={report}
            colormaps={colormaps}
            selected={selected}
            onSelect={(id) => {
              const h = report.analysis.hotspots.find((x) => x.id === id);
              if (h) selectHotspot(h);
            }}
            jump={jump}
          />
        ) : (
          <div className="empty" style={{ gridRow: "1 / -1" }}>
            {live.data && (live.data.status === "running" || live.data.status === "queued") ? (
              <div>
                <Loader2 size={34} className="spin" style={{ color: "var(--accent)" }} />
                <h2 style={{ marginTop: 14 }}>Fusing PET and MRI…</h2>
                <p className="sec">Simulate → register → enhance → fuse → export. Follow the steps on the left.</p>
              </div>
            ) : viewer.loading ? (
              <div>
                <Loader2 size={34} className="spin" style={{ color: "var(--accent)" }} />
                <h2 style={{ marginTop: 14 }}>Loading volumes… {Math.round(viewer.progress * 100)}%</h2>
              </div>
            ) : (
              <div style={{ maxWidth: 520 }}>
                <img src="/favicon.svg" alt="" width={64} height={64} />
                <h2 style={{ marginTop: 14 }}>PET-MRI precision, without a PET-MRI scanner</h2>
                <p className="sec">
                  Pick a demo patient (or upload a PET and an MRI from separate scanners) and press <b>Run FusionMap</b>. In
                  about a minute you get a registered, sharpened, colour-fused study plus a PACS-ready DICOM bundle.
                </p>
                {(live.error || viewer.error) && <div className="alert err">{live.error || viewer.error}</div>}
              </div>
            )}
          </div>
        )}
      </main>
      {live.data && report && done ? (
        <ResultsPanel c={live.data} health={health} report={report} selected={selected} onSelect={selectHotspot} />
      ) : (
        <aside className="results">
          <div className="section">
            <h3>Results</h3>
            <p className="note">
              Alignment error, tumour volumes (SUVmax, MTV, TBR), enhancement fidelity and DICOM export appear here once the
              pipeline finishes.
            </p>
          </div>
        </aside>
      )}
    </div>
  );
}
