export type StepStatus = "pending" | "running" | "done" | "skipped" | "error";

export interface StepState {
  status: StepStatus;
  label?: string;
  seconds?: number | null;
  message?: string | null;
  progress?: number | null;
}

export interface Hotspot {
  id: number;
  suv_max: number;
  suv_peak: number;
  suv_mean: number;
  mtv_ml: number;
  tlg: number;
  tbr_max: number;
  peak_mm: number[];
  centroid_mm: number[];
  peak_index_zyx: [number, number, number];
  side: string;
  bbox_zyx: number[][];
}

export interface TRE {
  mean_mm: number;
  median_mm: number;
  p95_mm: number;
  max_mm: number;
  lesion_mm: number[];
}

export interface Quality {
  psnr_db: number;
  ssim: number;
  nmae: number;
}

export interface Recovery {
  id: number;
  kind: string;
  suv_true: number;
  suv_measured: number;
  rc: number;
  volume_ml: number;
}

export interface Hallucination {
  id: number;
  suv_true_mean: number;
  suv_measured_mean: number;
  ratio: number;
}

export interface Lesion {
  id: number;
  center_mm: number[];
  radius_mm: number;
  suv_true: number;
  necrotic: boolean;
  volume_ml: number;
  kind: "active" | "pet_only" | "mri_only";
}

export interface Validation {
  tre_naive: TRE;
  tre_rigid: TRE;
  tre_final: TRE;
  quality_registered: Quality;
  quality_enhanced: Quality | null;
  recovery_registered: Recovery[];
  recovery_enhanced: Recovery[];
  hallucination_registered: Hallucination[];
  hallucination_enhanced: Hallucination[];
  detection: {
    pet_positive_lesions: number;
    detected: number;
    sensitivity: number | null;
    false_positives: number;
    mean_dice: number | null;
    mean_centroid_error_mm: number | null;
  };
  phantom: {
    tracer: string;
    lesions: Lesion[];
    misalignment: { rotation_deg: number[]; translation_mm: number[]; nonrigid_peak_mm: number };
    config: Record<string, unknown>;
  };
}

export interface Report {
  version: string;
  disclaimer: string;
  options: Record<string, unknown>;
  inputs: {
    mri: ImageSummary & { meta: Record<string, unknown> };
    pet: ImageSummary & { meta: Record<string, unknown> };
    fusion_grid: ImageSummary;
  };
  registration: {
    method: string;
    rigid?: { seconds: number; rotation_deg: number[]; translation_mm: number[]; iterations: number; stop: string };
    deformable?: {
      model: string;
      seconds: number;
      max_displacement_mm?: number;
      mean_displacement_mm?: number;
      min_jacobian?: number;
    };
    mi_trace?: number[];
    nmi_before: number;
    nmi_after: number;
    edge_alignment_before: number;
    edge_alignment_after: number;
  };
  enhancement: { method: string; seconds?: number; model?: string };
  analysis: {
    background_suv: number;
    tbr_threshold: number;
    display: { pet_threshold: number; pet_max: number };
    hotspots: Hotspot[];
  };
  export?: {
    zip: string;
    study_instance_uid: string;
    frame_of_reference_uid: string;
    series: Record<string, string | null>;
    slices: number;
    rtstruct_contours: number;
    size_mb: number;
  };
  validation?: Validation;
  timings_s: Record<string, number>;
  total_seconds: number;
}

export interface ImageSummary {
  size: number[];
  spacing_mm: number[];
  origin_mm: number[];
  fov_mm: number[];
  min: number;
  max: number;
}

export interface CaseSummary {
  id: string;
  name: string;
  kind: "phantom" | "upload";
  created: number;
  status: "created" | "queued" | "running" | "done" | "error";
  options: Record<string, unknown>;
  phantom: Record<string, unknown> | null;
  error: string | null;
  finished: number | null;
  steps: Record<string, StepState>;
  report?: Report | null;
}

export interface VolumeMeta {
  file: string;
  lo: number;
  hi: number;
  kind: "mri" | "pet" | "labels";
  labels?: boolean;
}

export interface Manifest {
  shape_zyx: [number, number, number];
  spacing_xyz: [number, number, number];
  origin_xyz: [number, number, number];
  volumes: Record<string, VolumeMeta>;
  mip: { file: string; frames: number; frame_width: number; frame_height: number };
  colormap: string;
}

export interface Health {
  status: string;
  version: string;
  disclaimer: string;
  pacs_default?: { host: string; port: number; called_aet: string; viewer_url: string };
  models: {
    voxelmorph: { available: boolean; used_by_auto?: boolean; card: ModelCard | null };
    enhancer: { available: boolean; card: ModelCard | null };
  };
}

export interface ModelCard {
  name: string;
  architecture: string;
  parameters: number;
  training: Record<string, unknown>;
  validation: Record<string, unknown>;
}

export type Colormaps = Record<string, number[][]>;

export interface PipelineEvent {
  type: "step" | "progress" | "complete" | "error" | "status";
  step?: string;
  label?: string;
  status?: string;
  progress?: number;
  message?: string;
  seconds?: number;
  error?: string | null;
  t?: number;
}
