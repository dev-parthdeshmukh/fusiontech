import { useEffect, useRef, useState } from "react";
import { viewerUrl } from "../api";
import type { Manifest } from "../types";

/** Rotating maximum-intensity projection — the classic nuclear-medicine 3-D overview. */
export function MipView({ caseId, manifest }: { caseId: string; manifest: Manifest }) {
  const { frames, frame_width: fw, frame_height: fh, file } = manifest.mip;
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(true);
  const drag = useRef<{ x: number; f: number } | null>(null);
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => setFrame((f) => (f + 1) % frames), 90);
    return () => window.clearInterval(id);
  }, [playing, frames]);
  const [sx, , sz] = manifest.spacing_xyz;
  const aspect = (fw * sx) / (fh * sz);
  return (
    <div
      className="pane"
      style={{ display: "grid", placeItems: "center", cursor: "ew-resize" }}
      onPointerDown={(e) => {
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        drag.current = { x: e.clientX, f: frame };
        setPlaying(false);
      }}
      onPointerMove={(e) => {
        if (!drag.current) return;
        const df = Math.round((e.clientX - drag.current.x) / 8);
        setFrame((((drag.current.f + df) % frames) + frames) % frames);
      }}
      onPointerUp={() => (drag.current = null)}
      onDoubleClick={() => setPlaying((p) => !p)}
    >
      <div
        role="img"
        aria-label="rotating maximum intensity projection of the enhanced PET"
        style={{
          height: "92%",
          aspectRatio: String(aspect),
          maxWidth: "92%",
          backgroundImage: `url(${viewerUrl(caseId, file)})`,
          backgroundSize: `${frames * 100}% 100%`,
          backgroundPosition: `${(frame / Math.max(frames - 1, 1)) * 100}% 0`,
          imageRendering: "auto",
        }}
      />
      <div className="ov tl">
        <b>PET MIP</b>
        <div className="muted">{Math.round((360 * frame) / frames)}°</div>
      </div>
      <div className="ov br muted">{playing ? "drag to rotate" : "double-click to play"}</div>
    </div>
  );
}
