import { Columns2, Crosshair, Grid3x3, Layers, LayoutGrid, Maximize2, ScanLine } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ViewerData } from "../hooks/useCase";
import { makeLut } from "../lib/render";
import { mm, type Cursor, type Plane } from "../lib/volume";
import type { Colormaps, Hotspot, Report } from "../types";
import { MipView } from "./MipView";
import { SliceView } from "./SliceView";

export type Mode = "fused" | "swipe" | "checker" | "pet";
type ComparePreset = "alignment" | "sharpening" | "truth";

const COMPARE: Record<ComparePreset, { a: string; b: string; la: string; lb: string; title: string }> = {
  alignment: { a: "pet_naive", b: "pet_enhanced", la: "Naive overlay", lb: "FusionMap", title: "Alignment" },
  sharpening: { a: "pet_registered", b: "pet_enhanced", la: "Registered PET", lb: "AI-enhanced", title: "Sharpening" },
  truth: { a: "pet_enhanced", b: "truth_pet", la: "AI-enhanced", lb: "Ground truth", title: "vs truth" },
};

const SOURCES: Record<string, string> = {
  pet_enhanced: "AI-enhanced PET",
  pet_registered: "Registered PET",
  pet_naive: "Unregistered PET",
  truth_pet: "Ground-truth PET",
};

interface Props {
  caseId: string;
  viewer: ViewerData;
  report: Report;
  colormaps: Colormaps | null;
  selected: number | null;
  onSelect: (id: number | null) => void;
  jump: { zyx: [number, number, number]; n: number } | null;
}

function hashParam(name: string): string | null {
  return new URLSearchParams(location.hash.split("?")[1] ?? "").get(name);
}

export function Viewer({ caseId, viewer, report, colormaps, selected, onSelect, jump }: Props) {
  const { manifest, vols } = viewer;
  const [nz, ny, nx] = manifest.shape_zyx;
  const hotspots = report.analysis.hotspots;
  const first = hotspots[0]?.peak_index_zyx;
  const [cursor, setCursor] = useState<Cursor>(() =>
    first ? { z: first[0], y: first[1], x: first[2] } : { z: Math.floor(nz / 2), y: Math.floor(ny / 2), x: Math.floor(nx / 2) },
  );
  const [hover, setHover] = useState<Cursor | null>(null);
  // deep links (handy for demos): #/workspace?case=…&mode=swipe&preset=sharpening&swipe=0.55
  const [mode, setMode] = useState<Mode>(() => (hashParam("mode") as Mode) || "swipe");
  const [preset, setPreset] = useState<ComparePreset>(() => (hashParam("preset") as ComparePreset) || "alignment");
  const [source, setSource] = useState("pet_enhanced");
  const [cmap, setCmap] = useState(manifest.colormap || "hot");
  const [opacity, setOpacity] = useState(0.8);
  const petHi = vols.pet_enhanced?.meta.hi ?? 1;
  const [thrSuv, setThrSuv] = useState(report.analysis.display.pet_threshold);
  const [topSuv, setTopSuv] = useState(report.analysis.display.pet_max);
  const [showHot, setShowHot] = useState(true);
  const [showTruth, setShowTruth] = useState(false);
  const [layout, setLayout] = useState<"quad" | "single">("quad");
  const [main, setMain] = useState<Plane>("axial");
  const [swipe, setSwipe] = useState(() => Number(hashParam("swipe") ?? 0.5));
  const [focus, setFocus] = useState<Plane>("axial");

  useEffect(() => {
    if (jump) {
      setCursor({ z: jump.zyx[0], y: jump.zyx[1], x: jump.zyx[2] });
    }
  }, [jump]);

  // keyboard: arrows scroll the focused plane, 1-4 switch modes
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT" || (e.target as HTMLElement)?.tagName === "SELECT") return;
      const d = e.key === "ArrowUp" || e.key === "ArrowRight" ? 1 : e.key === "ArrowDown" || e.key === "ArrowLeft" ? -1 : 0;
      if (d) {
        e.preventDefault();
        setCursor((c) => {
          const n = { ...c };
          if (focus === "axial") n.z = Math.max(0, Math.min(nz - 1, c.z + d));
          if (focus === "coronal") n.y = Math.max(0, Math.min(ny - 1, c.y - d));
          if (focus === "sagittal") n.x = Math.max(0, Math.min(nx - 1, c.x + d));
          return n;
        });
      }
      const m = ({ "1": "fused", "2": "swipe", "3": "checker", "4": "pet" } as Record<string, Mode>)[e.key];
      if (m) setMode(m);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focus, nz, ny, nx]);

  const lut = useMemo(() => makeLut(colormaps?.[cmap]), [colormaps, cmap]);
  const mri = vols.mri ?? null;
  const cmp = COMPARE[preset];
  const hasTruth = Boolean(vols.truth_pet);
  const primary = mode === "swipe" || mode === "checker" ? vols[cmp.b] ?? vols.pet_enhanced : vols[source] ?? vols.pet_enhanced;
  const secondary = mode === "swipe" ? vols[cmp.a] ?? null : null;
  const params = useMemo(
    () => ({
      lut,
      opacity,
      thr: (thrSuv / petHi) * 255,
      top: (topSuv / petHi) * 255,
      wlo: 0,
      whi: 255,
      showMri: true,
      showPet: true,
    }),
    [lut, opacity, thrSuv, topSuv, petHi],
  );
  const spec = useMemo(
    () => ({
      mri,
      pet: primary,
      petB: secondary,
      mode,
      swipe,
      checker: 12,
      params,
      hotspots: showHot ? vols.hotspots ?? null : null,
      truth: showTruth ? vols.truth_lesions ?? null : null,
      selectedHotspot: selected,
    }),
    [mri, primary, secondary, mode, swipe, params, showHot, showTruth, vols, selected],
  );

  const at = hover ?? cursor;
  const pos = mm(at, manifest);
  const suv = vols.pet_enhanced ? vols.pet_enhanced.value(at.z, at.y, at.x) : 0;
  const suvReg = vols.pet_registered ? vols.pet_registered.value(at.z, at.y, at.x) : 0;
  const hid = vols.hotspots ? vols.hotspots.at(at.z, at.y, at.x) : 0;
  const swipeLabels: [string, string] = [cmp.la, cmp.lb];
  const planes: Plane[] = ["axial", "coronal", "sagittal"];
  const minors = planes.filter((p) => p !== main);
  const gradient = colormaps?.[cmap]
    ? `linear-gradient(90deg, ${[0, 64, 128, 192, 255].map((i) => `rgb(${colormaps[cmap][i].join(",")})`).join(",")})`
    : undefined;

  const pane = (p: Plane, big = false) => (
    <SliceView
      key={p}
      plane={p}
      manifest={manifest}
      cursor={cursor}
      setCursor={setCursor}
      onHover={setHover}
      spec={spec}
      swipe={swipe}
      setSwipe={setSwipe}
      swipeLabels={big ? swipeLabels : undefined}
      focused={focus === p}
      onFocus={() => setFocus(p)}
    />
  );

  return (
    <>
      <div className="toolbar">
        <div className="seg" role="tablist" aria-label="view mode">
          <button className={mode === "fused" ? "on" : ""} onClick={() => setMode("fused")} title="Fused (1)">
            <Layers size={14} style={{ verticalAlign: -2, marginRight: 4 }} />
            Fused
          </button>
          <button className={mode === "swipe" ? "on" : ""} onClick={() => setMode("swipe")} title="Before / after swipe (2)">
            <Columns2 size={14} style={{ verticalAlign: -2, marginRight: 4 }} />
            Compare
          </button>
          <button className={mode === "checker" ? "on" : ""} onClick={() => setMode("checker")} title="Checkerboard QA (3)">
            <Grid3x3 size={14} style={{ verticalAlign: -2, marginRight: 4 }} />
            Checker
          </button>
          <button className={mode === "pet" ? "on" : ""} onClick={() => setMode("pet")} title="PET only (4)">
            <ScanLine size={14} style={{ verticalAlign: -2, marginRight: 4 }} />
            PET
          </button>
        </div>
        {mode === "swipe" ? (
          <div className="seg" aria-label="comparison">
            {(Object.keys(COMPARE) as ComparePreset[])
              .filter((k) => k !== "truth" || hasTruth)
              .map((k) => (
                <button key={k} className={preset === k ? "on" : ""} onClick={() => setPreset(k)}>
                  {COMPARE[k].title}
                </button>
              ))}
          </div>
        ) : mode !== "checker" ? (
          <select className="input" style={{ width: 170 }} value={source} onChange={(e) => setSource(e.target.value)} aria-label="PET source">
            {Object.entries(SOURCES)
              .filter(([k]) => vols[k])
              .map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
          </select>
        ) : null}
        <div className="grp">
          <span className="lbl">Colour</span>
          <select className="input" style={{ width: 96 }} value={cmap} onChange={(e) => setCmap(e.target.value)} aria-label="colour map">
            {Object.keys(colormaps ?? { hot: [] })
              .filter((k) => k !== "gray")
              .map((k) => (
                <option key={k}>{k}</option>
              ))}
          </select>
          {gradient && <div className="legend-bar" style={{ background: gradient }} title={`${thrSuv.toFixed(1)}–${topSuv.toFixed(1)} SUV`} />}
        </div>
        <div className="grp">
          <span className="lbl">Opacity</span>
          <input type="range" min={0.1} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(+e.target.value)} aria-label="PET opacity" />
        </div>
        <div className="grp">
          <span className="lbl num" style={{ width: 64 }}>SUV ≥ {thrSuv.toFixed(1)}</span>
          <input
            type="range"
            min={0}
            max={topSuv}
            step={0.1}
            value={thrSuv}
            onChange={(e) => setThrSuv(+e.target.value)}
            aria-label="PET threshold (SUV)"
          />
        </div>
        <div className="grp">
          <span className="lbl num" style={{ width: 58 }}>max {topSuv.toFixed(1)}</span>
          <input type="range" min={thrSuv + 0.5} max={petHi} step={0.1} value={topSuv} onChange={(e) => setTopSuv(+e.target.value)} aria-label="PET maximum (SUV)" />
        </div>
        <div className="grp">
          <button className={`btn sm ${showHot ? "" : "ghost"}`} onClick={() => setShowHot((v) => !v)} title="Outline PET tumour volumes">
            <Crosshair size={13} /> BTV
          </button>
          {vols.truth_lesions && (
            <button className={`btn sm ${showTruth ? "" : "ghost"}`} onClick={() => setShowTruth((v) => !v)} title="Outline ground-truth lesions">
              Truth
            </button>
          )}
          <button className="btn sm ghost icon" onClick={() => setLayout((l) => (l === "quad" ? "single" : "quad"))} title="Toggle layout">
            {layout === "quad" ? <Maximize2 size={14} /> : <LayoutGrid size={14} />}
          </button>
          {layout === "single" && (
            <div className="seg">
              {planes.map((p) => (
                <button key={p} className={main === p ? "on" : ""} onClick={() => setMain(p)}>
                  {p[0].toUpperCase()}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      {layout === "quad" ? (
        <div className="viewgrid">
          <div className="main">{pane(main, true)}</div>
          {pane(minors[0])}
          {pane(minors[1])}
          <MipView caseId={caseId} manifest={manifest} />
        </div>
      ) : (
        <div className="viewgrid single">{pane(main, true)}</div>
      )}
      <div className="readout">
        <span>
          x/y/z <b>{pos.map((v) => v.toFixed(1)).join(" / ")}</b> mm (LPS)
        </span>
        <span>
          SUV <b>{suv.toFixed(2)}</b> <span className="muted">(registered {suvReg.toFixed(2)})</span>
        </span>
        <span>
          voxel <b>{[at.x, at.y, at.z].join(", ")}</b>
        </span>
        {hid > 0 && (
          <button className="btn sm" onClick={() => onSelect(hid)}>
            inside BTV {hid}
          </button>
        )}
        <span className="muted" style={{ marginLeft: "auto" }}>
          wheel / ↑↓ scroll · click to navigate · 1–4 modes
        </span>
      </div>
    </>
  );
}

export function hotspotJump(h: Hotspot) {
  return h.peak_index_zyx;
}
