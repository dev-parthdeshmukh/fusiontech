import type { Plane, Volume } from "./volume";

export type Lut = Uint8Array; // 256 * 3

export function makeLut(table: number[][] | undefined): Lut {
  const lut = new Uint8Array(256 * 3);
  if (!table) {
    for (let i = 0; i < 256; i++) lut.set([i, i, i], i * 3);
    return lut;
  }
  for (let i = 0; i < 256; i++) lut.set(table[i] ?? [i, i, i], i * 3);
  return lut;
}

export interface FusionParams {
  lut: Lut;
  opacity: number; // 0..1
  /** PET threshold and max as 0..255 values of the PET volume encoding */
  thr: number;
  top: number;
  /** MRI window as 0..255 of the MRI encoding */
  wlo: number;
  whi: number;
  showMri: boolean;
  showPet: boolean;
}

/** Fused RGBA pixels: greyscale MRI with colour-mapped PET blended above threshold. */
export function fusePixels(
  mri: Uint8Array | null,
  pet: Uint8Array | null,
  n: number,
  p: FusionParams,
  out: Uint8ClampedArray,
  offset = 0,
  stride = 1,
): void {
  const { lut, opacity, thr, top, wlo, whi, showMri, showPet } = p;
  const wscale = 255 / Math.max(whi - wlo, 1);
  const pscale = 1 / Math.max(top - thr, 1e-3);
  for (let i = offset; i < n; i += stride) {
    let g = 0;
    if (mri && showMri) {
      g = (mri[i] - wlo) * wscale;
      g = g < 0 ? 0 : g > 255 ? 255 : g;
    }
    let r = g,
      gg = g,
      b = g;
    if (pet && showPet) {
      let t = (pet[i] - thr) * pscale;
      if (t > 0) {
        if (t > 1) t = 1;
        const a = showMri ? opacity * Math.min(t * 4, 1) : 1;
        const li = Math.round(t * 255) * 3;
        r = g * (1 - a) + lut[li] * a;
        gg = g * (1 - a) + lut[li + 1] * a;
        b = g * (1 - a) + lut[li + 2] * a;
      } else if (!showMri) {
        r = gg = b = 0;
      }
    }
    const o = i * 4;
    out[o] = r;
    out[o + 1] = gg;
    out[o + 2] = b;
    out[o + 3] = 255;
  }
}

/** Outline every labelled region (label > 0) by writing a colour onto boundary pixels. */
export function drawContours(
  labels: Uint8Array,
  w: number,
  h: number,
  out: Uint8ClampedArray,
  color: [number, number, number],
  only?: number,
): void {
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const v = labels[i];
      if (!v || (only && v !== only)) continue;
      const edge =
        x === 0 ||
        y === 0 ||
        x === w - 1 ||
        y === h - 1 ||
        labels[i - 1] !== v ||
        labels[i + 1] !== v ||
        labels[i - w] !== v ||
        labels[i + w] !== v;
      if (edge) {
        const o = i * 4;
        out[o] = color[0];
        out[o + 1] = color[1];
        out[o + 2] = color[2];
      }
    }
  }
}

export interface RenderSpec {
  plane: Plane;
  index: number;
  mri: Volume | null;
  /** Primary PET for fused / right-hand side of compare */
  pet: Volume | null;
  /** Secondary PET for the left side of compare / checkerboard */
  petB?: Volume | null;
  mode: "fused" | "swipe" | "checker" | "pet";
  swipe: number; // 0..1, fraction from the left showing petB
  checker: number; // tile size in pixels
  params: FusionParams;
  hotspots?: Volume | null;
  truth?: Volume | null;
  selectedHotspot?: number | null;
}

/** Render a slice to an ImageData (native voxel resolution). */
export function renderSlice(spec: RenderSpec): ImageData | null {
  const base = spec.mri ?? spec.pet;
  if (!base) return null;
  const s = base.slice(spec.plane, spec.index);
  const { w, h } = s;
  const n = w * h;
  const img = new ImageData(w, h);
  const out = img.data;
  const mri = spec.mri ? spec.mri.slice(spec.plane, spec.index).px : null;
  const pet = spec.pet ? spec.pet.slice(spec.plane, spec.index).px : null;
  const p = spec.params;

  if (spec.mode === "fused" || spec.mode === "pet") {
    const params = spec.mode === "pet" ? { ...p, showMri: false, showPet: true } : p;
    fusePixels(mri, pet, n, params, out);
  } else {
    const petB = spec.petB ? spec.petB.slice(spec.plane, spec.index).px : null;
    const tmpA = new Uint8ClampedArray(n * 4);
    const tmpB = new Uint8ClampedArray(n * 4);
    fusePixels(mri, petB, n, p, tmpB);
    fusePixels(mri, pet, n, p, tmpA);
    if (spec.mode === "swipe") {
      const cut = Math.round(spec.swipe * w);
      for (let y = 0; y < h; y++) {
        const row = y * w * 4;
        out.set(tmpB.subarray(row, row + cut * 4), row);
        out.set(tmpA.subarray(row + cut * 4, row + w * 4), row + cut * 4);
      }
    } else {
      // checkerboard: MRI greyscale tiles alternate with PET-only tiles of the primary PET
      const pure = new Uint8ClampedArray(n * 4);
      fusePixels(null, pet, n, { ...p, showMri: false, showPet: true }, pure);
      const grey = new Uint8ClampedArray(n * 4);
      fusePixels(mri, null, n, { ...p, showPet: false }, grey);
      const t = Math.max(4, spec.checker);
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          const o = (y * w + x) * 4;
          const src = ((Math.floor(x / t) + Math.floor(y / t)) & 1) === 0 ? grey : pure;
          out[o] = src[o];
          out[o + 1] = src[o + 1];
          out[o + 2] = src[o + 2];
          out[o + 3] = 255;
        }
      }
    }
  }
  if (spec.truth) drawContours(spec.truth.slice(spec.plane, spec.index).px, w, h, out, [120, 220, 255]);
  if (spec.hotspots) {
    const lab = spec.hotspots.slice(spec.plane, spec.index).px;
    drawContours(lab, w, h, out, [57, 255, 160]);
    if (spec.selectedHotspot) drawContours(lab, w, h, out, [255, 255, 255], spec.selectedHotspot);
  }
  return img;
}
