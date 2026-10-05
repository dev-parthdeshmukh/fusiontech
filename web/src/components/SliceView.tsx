import { useEffect, useRef, useState } from "react";
import { renderSlice, type RenderSpec } from "../lib/render";
import { clamp, fromVoxel, ORIENT, sliceCount, sliceIndex, toVoxel, type Cursor, type Plane } from "../lib/volume";
import type { Manifest } from "../types";

interface Props {
  plane: Plane;
  manifest: Manifest;
  cursor: Cursor;
  setCursor: (c: Cursor) => void;
  onHover?: (c: Cursor | null) => void;
  spec: Omit<RenderSpec, "plane" | "index">;
  swipe: number;
  setSwipe: (v: number) => void;
  swipeLabels?: [string, string];
  focused?: boolean;
  onFocus?: () => void;
  title?: string;
}

const PLANE_NAME: Record<Plane, string> = { axial: "Axial", coronal: "Coronal", sagittal: "Sagittal" };

export function SliceView({ plane, manifest, cursor, setCursor, onHover, spec, swipe, setSwipe, swipeLabels, focused, onFocus, title }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const off = useRef<HTMLCanvasElement | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const rect = useRef({ x: 0, y: 0, w: 1, h: 1, iw: 1, ih: 1 });
  const dragging = useRef(false);
  const index = sliceIndex(plane, cursor);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const cv = canvas.current;
    if (!cv || size.w === 0) return;
    const img = renderSlice({ ...spec, plane, index });
    if (!img) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(size.w * dpr);
    cv.height = Math.round(size.h * dpr);
    const ctx = cv.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, size.w, size.h);
    if (!off.current) off.current = document.createElement("canvas");
    const o = off.current;
    o.width = img.width;
    o.height = img.height;
    o.getContext("2d")!.putImageData(img, 0, 0);
    // physical aspect ratio
    const [sx, sy, sz] = manifest.spacing_xyz;
    const pw = img.width * (plane === "sagittal" ? sy : sx);
    const ph = img.height * (plane === "axial" ? sy : sz);
    const scale = Math.min((size.w - 8) / pw, (size.h - 8) / ph);
    const dw = pw * scale;
    const dh = ph * scale;
    const dx = (size.w - dw) / 2;
    const dy = (size.h - dh) / 2;
    rect.current = { x: dx, y: dy, w: dw, h: dh, iw: img.width, ih: img.height };
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(o, dx, dy, dw, dh);
    // crosshair
    const { col, row } = fromVoxel(plane, cursor, manifest);
    const cx = dx + ((col + 0.5) / img.width) * dw;
    const cy = dy + ((row + 0.5) / img.height) * dh;
    ctx.strokeStyle = "rgba(125, 211, 252, 0.55)";
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(dx, cy);
    ctx.lineTo(cx - 9, cy);
    ctx.moveTo(cx + 9, cy);
    ctx.lineTo(dx + dw, cy);
    ctx.moveTo(cx, dy);
    ctx.lineTo(cx, cy - 9);
    ctx.moveTo(cx, cy + 9);
    ctx.lineTo(cx, dy + dh);
    ctx.stroke();
    if (spec.mode === "swipe") {
      const x = dx + swipe * dw;
      ctx.strokeStyle = "rgba(255,255,255,0.9)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, dy);
      ctx.lineTo(x, dy + dh);
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.beginPath();
      ctx.arc(x, dy + dh / 2, 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#0a0e14";
      ctx.font = "bold 11px system-ui";
      ctx.textAlign = "center";
      ctx.fillText("⇆", x, dy + dh / 2 + 4);
    }
  }, [spec, plane, index, cursor, size, swipe, manifest]);

  const toImage = (e: React.PointerEvent | React.WheelEvent) => {
    const b = canvas.current!.getBoundingClientRect();
    const r = rect.current;
    const px = e.clientX - b.left;
    const py = e.clientY - b.top;
    const col = Math.floor(((px - r.x) / r.w) * r.iw);
    const row = Math.floor(((py - r.y) / r.h) * r.ih);
    return { col, row, fx: (px - r.x) / r.w, inside: col >= 0 && row >= 0 && col < r.iw && row < r.ih };
  };
  const setFrom = (e: React.PointerEvent) => {
    const p = toImage(e);
    if (!p.inside) return;
    setCursor(toVoxel(plane, p.col, p.row, cursor, manifest));
  };

  const n = sliceCount(plane, manifest);
  const [L, R, T, B] = ORIENT[plane];
  return (
    <div ref={wrap} className={`pane${focused ? " focus" : ""}`} onPointerEnter={onFocus}>
      <canvas
        ref={canvas}
        onPointerDown={(e) => {
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
          dragging.current = true;
          setFrom(e);
        }}
        onPointerUp={() => (dragging.current = false)}
        onPointerLeave={() => onHover?.(null)}
        onPointerMove={(e) => {
          const p = toImage(e);
          if (spec.mode === "swipe" && !dragging.current) setSwipe(clamp(p.fx, 0, 1));
          if (dragging.current) setFrom(e);
          if (p.inside && onHover) onHover(toVoxel(plane, p.col, p.row, cursor, manifest));
        }}
        onWheel={(e) => {
          const step = e.deltaY > 0 ? -1 : 1;
          const c = { ...cursor };
          if (plane === "axial") c.z = clamp(c.z + step, 0, n - 1);
          else if (plane === "coronal") c.y = clamp(c.y - step, 0, n - 1);
          else c.x = clamp(c.x + step, 0, n - 1);
          setCursor(c);
        }}
      />
      <div className="ov tl">
        <b>{title ?? PLANE_NAME[plane]}</b>
        <div className="muted">
          {index + 1} / {n}
        </div>
      </div>
      <div className="ov l">{L}</div>
      <div className="ov r">{R}</div>
      <div className="ov t">{T}</div>
      <div className="ov b">{B}</div>
      {spec.mode === "swipe" && swipeLabels && (
        <>
          <div className="swipe-tag" style={{ left: 10 }}>◀ {swipeLabels[0]}</div>
          <div className="swipe-tag" style={{ right: 10 }}>{swipeLabels[1]} ▶</div>
        </>
      )}
    </div>
  );
}
