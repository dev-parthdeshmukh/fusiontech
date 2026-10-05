import type { Manifest, VolumeMeta } from "../types";

export type Plane = "axial" | "coronal" | "sagittal";

/** 8-bit volume on the canonical LPS fusion grid, indexed [z][y][x]. */
export class Volume {
  readonly nz: number;
  readonly ny: number;
  readonly nx: number;
  constructor(
    readonly data: Uint8Array,
    readonly meta: VolumeMeta,
    readonly manifest: Manifest,
  ) {
    [this.nz, this.ny, this.nx] = manifest.shape_zyx;
  }

  at(z: number, y: number, x: number): number {
    return this.data[(z * this.ny + y) * this.nx + x];
  }

  /** Value in physical units (SUV for PET, raw for MRI). */
  value(z: number, y: number, x: number): number {
    return this.meta.lo + (this.at(z, y, x) / 255) * (this.meta.hi - this.meta.lo);
  }

  /** Extract a 2-D slice in display orientation (radiological convention). */
  slice(plane: Plane, index: number): { w: number; h: number; px: Uint8Array } {
    const { nx, ny, nz, data } = this;
    if (plane === "axial") {
      const k = clamp(index, 0, nz - 1);
      return { w: nx, h: ny, px: data.subarray(k * nx * ny, (k + 1) * nx * ny) };
    }
    if (plane === "coronal") {
      const j = clamp(index, 0, ny - 1);
      const px = new Uint8Array(nx * nz);
      for (let r = 0; r < nz; r++) {
        const z = nz - 1 - r; // superior at the top
        const src = (z * ny + j) * nx;
        px.set(data.subarray(src, src + nx), r * nx);
      }
      return { w: nx, h: nz, px };
    }
    const i = clamp(index, 0, nx - 1);
    const px = new Uint8Array(ny * nz);
    for (let r = 0; r < nz; r++) {
      const z = nz - 1 - r;
      const base = z * ny * nx + i;
      for (let c = 0; c < ny; c++) px[r * ny + c] = data[base + c * nx]; // anterior on the left
    }
    return { w: ny, h: nz, px };
  }
}

export interface Cursor {
  x: number;
  y: number;
  z: number;
}

export function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

/** Map a 2-D slice pixel (column, row) back to voxel coordinates. */
export function toVoxel(plane: Plane, col: number, row: number, c: Cursor, m: Manifest): Cursor {
  const [nz] = m.shape_zyx;
  if (plane === "axial") return { x: col, y: row, z: c.z };
  if (plane === "coronal") return { x: col, y: c.y, z: nz - 1 - row };
  return { x: c.x, y: col, z: nz - 1 - row };
}

/** Where the cursor sits in a plane's (col, row) coordinates. */
export function fromVoxel(plane: Plane, c: Cursor, m: Manifest): { col: number; row: number } {
  const [nz] = m.shape_zyx;
  if (plane === "axial") return { col: c.x, row: c.y };
  if (plane === "coronal") return { col: c.x, row: nz - 1 - c.z };
  return { col: c.y, row: nz - 1 - c.z };
}

export function sliceIndex(plane: Plane, c: Cursor) {
  return plane === "axial" ? c.z : plane === "coronal" ? c.y : c.x;
}

export function sliceCount(plane: Plane, m: Manifest) {
  const [nz, ny, nx] = m.shape_zyx;
  return plane === "axial" ? nz : plane === "coronal" ? ny : nx;
}

export function mm(c: Cursor, m: Manifest): [number, number, number] {
  const [ox, oy, oz] = m.origin_xyz;
  const [sx, sy, sz] = m.spacing_xyz;
  return [ox + c.x * sx, oy + c.y * sy, oz + c.z * sz];
}

/** Orientation labels (left, right, top, bottom) for each plane in radiological convention. */
export const ORIENT: Record<Plane, [string, string, string, string]> = {
  axial: ["R", "L", "A", "P"],
  coronal: ["R", "L", "S", "I"],
  sagittal: ["A", "P", "S", "I"],
};
