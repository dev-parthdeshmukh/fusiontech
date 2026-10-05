export const f1 = (v: number | null | undefined) => (v === null || v === undefined || !isFinite(v) ? "–" : v.toFixed(1));
export const f2 = (v: number | null | undefined) => (v === null || v === undefined || !isFinite(v) ? "–" : v.toFixed(2));
export const f3 = (v: number | null | undefined) => (v === null || v === undefined || !isFinite(v) ? "–" : v.toFixed(3));
export const pct = (v: number | null | undefined) =>
  v === null || v === undefined || !isFinite(v) ? "–" : `${Math.round(v * 100)}%`;

export function ago(ts: number) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

export const KIND_LABEL: Record<string, string> = {
  active: "Viable tumour (MRI + PET)",
  pet_only: "MRI-occult tumour (PET only)",
  mri_only: "Radionecrosis (MRI only, PET-cold)",
};

export const METHOD_LABEL: Record<string, string> = {
  naive: "No registration",
  rigid: "Rigid MI",
  "rigid+bspline": "Rigid + B-spline",
  "rigid+voxelmorph": "Rigid + VoxelMorph",
  none: "No enhancement",
  deconv: "RL deconvolution",
  vit: "ViT-hybrid AI",
};
