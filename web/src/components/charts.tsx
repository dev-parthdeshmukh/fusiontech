import { useMemo, useRef, useState } from "react";

/* Charts follow one spec: hairline recessive grid, 2px lines, <=24px bars with 4px rounded data
   ends, values in text tokens (never in the series colour), hover tooltip on every mark. */

function niceTicks(min: number, max: number, count = 4): number[] {
  if (!isFinite(min) || !isFinite(max) || max <= min) return [min];
  const span = max - min;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

function fmt(v: number, digits = 2) {
  if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return v.toFixed(digits);
}

interface Tip {
  x: number;
  y: number;
  lines: { key?: string; value: string; label: string }[];
}

function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip) return null;
  return (
    <div className="tooltip" style={{ left: tip.x + 12, top: tip.y - 10 }}>
      {tip.lines.map((l, i) => (
        <div key={i}>
          {l.key && <span className="k" style={{ background: l.key }} />}
          <b>{l.value}</b> <span className="muted">{l.label}</span>
        </div>
      ))}
    </div>
  );
}

/** Single-series line (e.g. mutual information per optimiser iteration) with crosshair. */
export function LineChart({
  values,
  height = 120,
  color = "var(--series-1)",
  xLabel = "iteration",
  yLabel = "",
  digits = 3,
}: {
  values: number[];
  height?: number;
  color?: string;
  xLabel?: string;
  yLabel?: string;
  digits?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const W = 340;
  const pad = { l: 38, r: 10, t: 8, b: 22 };
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const ticks = niceTicks(lo, hi, 3);
  const y0 = Math.min(lo, ticks[0] ?? lo);
  const y1 = Math.max(hi, ticks[ticks.length - 1] ?? hi);
  const sx = (i: number) => pad.l + (i / Math.max(values.length - 1, 1)) * (W - pad.l - pad.r);
  const sy = (v: number) => pad.t + (1 - (v - y0) / Math.max(y1 - y0, 1e-9)) * (height - pad.t - pad.b);
  const d = values.map((v, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join("");
  if (values.length < 2) return null;
  const onMove = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((x - pad.l) / (W - pad.l - pad.r)) * (values.length - 1));
    setHover(Math.max(0, Math.min(values.length - 1, i)));
  };
  const tip: Tip | null =
    hover === null || !ref.current
      ? null
      : {
          x: (sx(hover) / W) * ref.current.getBoundingClientRect().width,
          y: (sy(values[hover]) / height) * ref.current.getBoundingClientRect().height,
          lines: [{ key: color, value: fmt(values[hover], digits), label: `${yLabel} · sample ${hover + 1}` }],
        };
  return (
    <div className="chart" ref={ref} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label={`${yLabel} by ${xLabel}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="gridline" x1={pad.l} x2={W - pad.r} y1={sy(t)} y2={sy(t)} />
            <text className="tick" x={pad.l - 6} y={sy(t) + 3.5} textAnchor="end">
              {fmt(t, digits)}
            </text>
          </g>
        ))}
        <line className="baseline" x1={pad.l} x2={W - pad.r} y1={height - pad.b} y2={height - pad.b} />
        <text className="tick" x={pad.l} y={height - 6}>
          start
        </text>
        <text className="tick" x={W - pad.r} y={height - 6} textAnchor="end">
          converged
        </text>
        <path d={d} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={sx(values.length - 1)} cy={sy(values[values.length - 1])} r={4} fill={color} stroke="var(--panel)" strokeWidth={2} />
        {hover !== null && (
          <>
            <line className="baseline" x1={sx(hover)} x2={sx(hover)} y1={pad.t} y2={height - pad.b} />
            <circle cx={sx(hover)} cy={sy(values[hover])} r={4} fill={color} stroke="var(--panel)" strokeWidth={2} />
          </>
        )}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

export interface BarDatum {
  label: string;
  value: number;
  sub?: string;
  emphasis?: boolean;
  err?: number;
}

/** Horizontal bars with one emphasised bar (the story) and the rest recessive. */
export function BarList({ data, unit = "", digits = 2, max }: { data: BarDatum[]; unit?: string; digits?: number; max?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const W = 340;
  const rowH = 30;
  const labelW = 118;
  const pad = 46;
  const top = max ?? Math.max(...data.map((d) => d.value + (d.err ?? 0))) * 1.05;
  const bw = (v: number) => Math.max(2, (v / Math.max(top, 1e-9)) * (W - labelW - pad));
  const H = data.length * rowH + 4;
  return (
    <div className="chart" ref={ref} onPointerLeave={() => setTip(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="bar chart">
        <line className="baseline" x1={labelW} x2={labelW} y1={0} y2={H} />
        {data.map((d, i) => {
          const y = i * rowH + 6;
          const w = bw(d.value);
          const fill = d.emphasis ? "var(--series-1)" : "#4a5563";
          return (
            <g
              key={d.label}
              onPointerMove={(e) => {
                const r = ref.current!.getBoundingClientRect();
                setTip({
                  x: e.clientX - r.left,
                  y: e.clientY - r.top,
                  lines: [
                    {
                      key: fill,
                      value: `${fmt(d.value, digits)}${unit}${d.err ? ` ± ${fmt(d.err, digits)}` : ""}`,
                      label: d.label,
                    },
                  ],
                });
              }}
            >
              <rect x={0} y={y - 4} width={W} height={rowH} fill="transparent" />
              <text className="lab" x={labelW - 8} y={y + 12} textAnchor="end">
                {d.label}
              </text>
              <path
                d={`M${labelW},${y} h${w - 4} a4,4 0 0 1 4,4 v10 a4,4 0 0 1 -4,4 h${-(w - 4)} z`}
                fill={fill}
              />
              {d.err ? (
                <line
                  x1={labelW + bw(Math.max(d.value - d.err, 0))}
                  x2={labelW + bw(d.value + d.err)}
                  y1={y + 9}
                  y2={y + 9}
                  stroke="var(--text-2)"
                  strokeWidth={1}
                />
              ) : null}
              <text className="val" x={labelW + bw(d.value + (d.err ?? 0)) + 6} y={y + 13}>
                {fmt(d.value, digits)}
                {unit}
              </text>
            </g>
          );
        })}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

export interface PairDatum {
  label: string;
  a: number;
  b: number;
}

/** Paired dot plot: two measurements per item against a reference line (e.g. RC vs truth = 1). */
export function PairedDots({
  data,
  aLabel,
  bLabel,
  reference = 1,
  refLabel = "truth",
  digits = 2,
}: {
  data: PairDatum[];
  aLabel: string;
  bLabel: string;
  reference?: number;
  refLabel?: string;
  digits?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const W = 340;
  const rowH = 30;
  const labelW = 70;
  const right = 12;
  const { lo, hi } = useMemo(() => {
    const vals = data.flatMap((d) => [d.a, d.b]).concat([reference]);
    return { lo: Math.min(...vals) * 0.92, hi: Math.max(...vals) * 1.05 };
  }, [data, reference]);
  const sx = (v: number) => labelW + ((v - lo) / Math.max(hi - lo, 1e-9)) * (W - labelW - right);
  const H = data.length * rowH + 24;
  const ticks = niceTicks(lo, hi, 4);
  return (
    <div className="chart" ref={ref} onPointerLeave={() => setTip(null)}>
      <div className="legend">
        <span><i style={{ background: "var(--series-2)", borderRadius: "50%" }} />{aLabel}</span>
        <span><i style={{ background: "var(--series-1)", borderRadius: "50%" }} />{bLabel}</span>
        <span><i style={{ background: "var(--text-2)", width: 2 }} />{refLabel} = {reference}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${aLabel} vs ${bLabel}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="gridline" x1={sx(t)} x2={sx(t)} y1={0} y2={H - 18} />
            <text className="tick" x={sx(t)} y={H - 4} textAnchor="middle">
              {fmt(t, 1)}
            </text>
          </g>
        ))}
        <line x1={sx(reference)} x2={sx(reference)} y1={0} y2={H - 18} stroke="var(--text-2)" strokeWidth={1} />
        {data.map((d, i) => {
          const y = i * rowH + 15;
          return (
            <g
              key={d.label}
              onPointerMove={(e) => {
                const r = ref.current!.getBoundingClientRect();
                setTip({
                  x: e.clientX - r.left,
                  y: e.clientY - r.top,
                  lines: [
                    { key: "var(--series-2)", value: fmt(d.a, digits), label: `${aLabel} · ${d.label}` },
                    { key: "var(--series-1)", value: fmt(d.b, digits), label: `${bLabel} · ${d.label}` },
                  ],
                });
              }}
            >
              <rect x={0} y={y - 13} width={W} height={rowH} fill="transparent" />
              <text className="lab" x={0} y={y + 4}>
                {d.label}
              </text>
              <line x1={sx(d.a)} x2={sx(d.b)} y1={y} y2={y} stroke="var(--axis)" strokeWidth={2} />
              <circle cx={sx(d.a)} cy={y} r={5} fill="var(--series-2)" stroke="var(--panel)" strokeWidth={2} />
              <circle cx={sx(d.b)} cy={y} r={5} fill="var(--series-1)" stroke="var(--panel)" strokeWidth={2} />
            </g>
          );
        })}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

/** Before/after error against a clinical tolerance band (status colours + label, never colour alone). */
export function ToleranceMeter({ before, after, tolerance = 2, unit = "mm" }: { before: number; after: number; tolerance?: number; unit?: string }) {
  const W = 340;
  const H = 54;
  const max = Math.max(before, tolerance * 2) * 1.08;
  const sx = (v: number) => 8 + (Math.min(v, max) / max) * (W - 16);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`error ${before} ${unit} before, ${after} ${unit} after, tolerance ${tolerance} ${unit}`}>
        <rect x={8} y={22} width={W - 16} height={8} rx={4} fill="var(--panel-3)" />
        <rect x={8} y={22} width={sx(tolerance) - 8} height={8} rx={4} fill="rgba(12,163,12,0.35)" />
        <line x1={sx(tolerance)} x2={sx(tolerance)} y1={16} y2={36} stroke="var(--text-2)" strokeWidth={1} />
        <text className="tick" x={sx(tolerance)} y={50} textAnchor="middle">
          {tolerance} {unit} tolerance
        </text>
        <circle cx={sx(before)} cy={26} r={6} fill="var(--critical)" stroke="var(--panel)" strokeWidth={2} />
        <text className="val" x={sx(before)} y={12} textAnchor="end">
          before {fmt(before, 1)} {unit}
        </text>
        <circle cx={sx(after)} cy={26} r={6} fill="var(--good)" stroke="var(--panel)" strokeWidth={2} />
        <text className="val" x={Math.max(sx(after), 40)} y={12} textAnchor="start">
          after {fmt(after, 2)}
        </text>
      </svg>
    </div>
  );
}
