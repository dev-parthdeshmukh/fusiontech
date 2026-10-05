import type { CaseSummary, Colormaps, Health, Manifest, PipelineEvent } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep statusText */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then((r) => json<Health>(r)),
  colormaps: () => fetch("/api/colormaps").then((r) => json<Colormaps>(r)),
  cases: () => fetch("/api/cases").then((r) => json<CaseSummary[]>(r)),
  getCase: (id: string) => fetch(`/api/cases/${id}`).then((r) => json<CaseSummary>(r)),
  deleteCase: (id: string) => fetch(`/api/cases/${id}`, { method: "DELETE" }).then((r) => json(r)),
  benchmark: () => fetch("/api/benchmark").then((r) => json<Record<string, unknown>>(r)),
  createDemo: (body: Record<string, unknown>) =>
    fetch("/api/cases/demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => json<CaseSummary>(r)),
  rerun: (id: string, options: Record<string, unknown>) =>
    fetch(`/api/cases/${id}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
    }).then((r) => json<CaseSummary>(r)),
  upload: (mri: File, pet: File, options: Record<string, unknown>, name?: string) => {
    const fd = new FormData();
    fd.append("mri", mri);
    fd.append("pet", pet);
    fd.append("options", JSON.stringify(options));
    if (name) fd.append("name", name);
    return fetch("/api/cases/upload", { method: "POST", body: fd }).then((r) => json<CaseSummary>(r));
  },
  manifest: (id: string) => fetch(`/api/cases/${id}/viewer/manifest.json`).then((r) => json<Manifest>(r)),
  volume: async (id: string, file: string, onProgress?: (f: number) => void): Promise<Uint8Array> => {
    const res = await fetch(`/api/cases/${id}/viewer/${file}`);
    if (!res.ok || !res.body) throw new Error(`could not load ${file}`);
    // Content-Encoding: gzip is decoded by the browser; progress is approximate (compressed length)
    const reader = res.body.getReader();
    const chunks: Uint8Array[] = [];
    let n = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      n += value.length;
      onProgress?.(n);
    }
    const out = new Uint8Array(n);
    let o = 0;
    for (const c of chunks) {
      out.set(c, o);
      o += c.length;
    }
    return out;
  },
  pacsEcho: (body: Record<string, unknown>) =>
    fetch("/api/pacs/echo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => json<{ ok: boolean; error?: string }>(r)),
  pacsPush: (id: string, body: Record<string, unknown>) =>
    fetch(`/api/cases/${id}/pacs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => json<{ ok: boolean; sent: number; total: number; error?: string }>(r)),
  events: (id: string, onEvent: (e: PipelineEvent) => void): (() => void) => {
    const es = new EventSource(`/api/cases/${id}/events`);
    es.onmessage = (m) => {
      try {
        const e = JSON.parse(m.data) as PipelineEvent;
        onEvent(e);
        if (e.type === "status") es.close();
      } catch {
        /* ignore malformed keep-alives */
      }
    };
    es.onerror = () => es.close();
    return () => es.close();
  },
};

export const exportUrl = (id: string, name: string) => `/api/cases/${id}/exports/${name}`;
export const viewerUrl = (id: string, name: string) => `/api/cases/${id}/viewer/${name}`;
