import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Volume } from "../lib/volume";
import type { CaseSummary, Manifest, PipelineEvent, StepState } from "../types";

/** Live case state: initial fetch, then Server-Sent Events while the pipeline runs. */
export function useLiveCase(caseId: string | null) {
  const [data, setData] = useState<CaseSummary | null>(null);
  const [steps, setSteps] = useState<Record<string, StepState>>({});
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<(() => void) | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    closeRef.current?.();
    setError(null);
    if (!caseId) {
      setData(null);
      setSteps({});
      return;
    }
    let alive = true;
    api
      .getCase(caseId)
      .then((c) => {
        if (!alive) return;
        setData(c);
        setSteps(c.steps ?? {});
        if (c.status === "queued" || c.status === "running") {
          const local: Record<string, StepState> = {};
          closeRef.current = api.events(caseId, (e: PipelineEvent) => {
            if (!alive) return;
            if (e.type === "step" && e.step) {
              local[e.step] = {
                ...(local[e.step] ?? {}),
                status: e.status as StepState["status"],
                label: e.label,
                seconds: e.seconds ?? null,
                message: e.message ?? (e.status === "running" ? "" : local[e.step]?.message),
                progress: e.status === "done" ? 1 : local[e.step]?.progress ?? 0,
              };
              setSteps({ ...local });
            } else if (e.type === "progress" && e.step) {
              local[e.step] = { ...(local[e.step] ?? { status: "running" }), progress: e.progress, message: e.message };
              setSteps({ ...local });
            } else if (e.type === "error") {
              setError(e.message ?? "pipeline failed");
            } else if (e.type === "status") {
              api.getCase(caseId).then((c2) => {
                if (!alive) return;
                setData(c2);
                setSteps(c2.steps ?? local);
                if (c2.status === "error") setError(c2.error);
              });
            }
          });
        } else if (c.status === "error") {
          setError(c.error);
        }
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
      closeRef.current?.();
    };
  }, [caseId, tick]);

  return { data, steps, error, refresh };
}

export interface ViewerData {
  manifest: Manifest;
  vols: Record<string, Volume>;
}

/** Download the 8-bit viewer volumes for a finished case. */
export function useViewerData(caseId: string | null, ready: boolean, version: number) {
  const [state, setState] = useState<{ data: ViewerData | null; loading: boolean; progress: number; error: string | null }>(
    { data: null, loading: false, progress: 0, error: null },
  );
  useEffect(() => {
    if (!caseId || !ready) {
      setState({ data: null, loading: false, progress: 0, error: null });
      return;
    }
    let alive = true;
    setState((s) => ({ ...s, loading: true, progress: 0, error: null }));
    (async () => {
      try {
        const manifest = await api.manifest(caseId);
        const names = Object.keys(manifest.volumes);
        const [nz, ny, nx] = manifest.shape_zyx;
        const total = nz * ny * nx * names.length;
        const done: Record<string, number> = {};
        const vols: Record<string, Volume> = {};
        await Promise.all(
          names.map(async (n) => {
            const buf = await api.volume(caseId, manifest.volumes[n].file, (b) => {
              done[n] = b;
              if (alive) setState((s) => ({ ...s, progress: Object.values(done).reduce((a, x) => a + x, 0) / total }));
            });
            vols[n] = new Volume(buf, manifest.volumes[n], manifest);
          }),
        );
        if (alive) setState({ data: { manifest, vols }, loading: false, progress: 1, error: null });
      } catch (e) {
        if (alive) setState({ data: null, loading: false, progress: 0, error: String(e) });
      }
    })();
    return () => {
      alive = false;
    };
  }, [caseId, ready, version]);
  return state;
}
