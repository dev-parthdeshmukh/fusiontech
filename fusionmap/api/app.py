"""FusionMap web API (FastAPI) + static web app."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .. import DISCLAIMER, __version__
from ..enhancement import ai as enh_ai
from ..export import echo, push_folder
from ..fusion import all_luts
from ..phantom import TRACERS, PhantomConfig
from ..registration import learned as vxm
from .cases import CaseManager

STATIC = Path(__file__).resolve().parent.parent / "static"
DATA = Path(os.environ.get("FUSIONMAP_DATA", Path.cwd() / "var"))
BENCHMARK_PATHS = [DATA / "benchmark.json", Path(__file__).resolve().parents[2] / "docs" / "benchmark.json"]

manager = CaseManager(DATA / "cases")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Demo day: the first page a visitor sees should already show a fused study.
    if not manager.cases and os.environ.get("FUSIONMAP_PREWARM", "1") == "1":
        cfg = PhantomConfig(seed=2026, tracer="fdg", lesion_mix="showcase", n_lesions=3)
        c = manager.new_phantom_case(cfg, {}, "Showcase patient #2026 (FDG)")
        manager.submit(c.id)
    yield


app = FastAPI(title="FusionMap API", version=__version__, lifespan=lifespan,
              description="AI software PET/MRI fusion — " + DISCLAIMER)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class PipelineOptionsIn(BaseModel):
    registration: str | None = Field(None, pattern="^(auto|none|rigid|rigid\\+bspline|rigid\\+voxelmorph)$")
    enhancement: str | None = Field(None, pattern="^(auto|none|vit|deconv)$")
    colormap: str | None = None
    pet_fwhm_mm: float | None = Field(None, ge=1, le=15)
    working_spacing_mm: float | None = Field(None, ge=0.5, le=3.0)
    export_dicom: bool | None = None


class DemoIn(BaseModel):
    seed: int = Field(2026, ge=0, le=10_000_000)
    tracer: str = Field("fdg", pattern="^(fdg|fet)$")
    n_lesions: int | None = Field(None, ge=0, le=6)
    lesion_mix: str = Field("active", pattern="^(active|mixed|showcase)$")
    rotation_deg: float = Field(7.0, ge=0, le=25)
    translation_mm: float = Field(12.0, ge=0, le=40)
    nonrigid_mm: float = Field(2.5, ge=0, le=8)
    pet_fwhm_mm: float = Field(6.0, ge=2, le=12)
    pet_snr: float = Field(10.0, ge=2, le=50)
    mri_spacing: float = Field(1.0, ge=1.0, le=2.0, description="phantom grid (2 mm = fast preview)")
    name: str | None = None
    options: PipelineOptionsIn = PipelineOptionsIn()
    run: bool = True


class PacsIn(BaseModel):
    host: str
    port: int = Field(104, ge=1, le=65535)
    called_aet: str = "ANY-SCP"
    calling_aet: str = "FUSIONMAP"


def _clean(opts: PipelineOptionsIn | None) -> dict:
    return {k: v for k, v in (opts.model_dump() if opts else {}).items() if v is not None}


def _case(cid: str):
    c = manager.cases.get(cid)
    if c is None:
        raise HTTPException(404, f"case {cid} not found")
    return c


# ── meta ─────────────────────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "disclaimer": DISCLAIMER,
        "models": {
            "voxelmorph": {"available": vxm.available(), "used_by_auto": vxm.is_beneficial(), "card": vxm.model_card()},
            "enhancer": {"available": enh_ai.available(), "card": enh_ai.model_card()},
        },
        "tracers": {k: v.name for k, v in TRACERS.items()},
        "pacs_default": {"host": os.environ.get("FUSIONMAP_PACS_HOST", "127.0.0.1"),
                         "port": int(os.environ.get("FUSIONMAP_PACS_PORT", "4242")),
                         "called_aet": os.environ.get("FUSIONMAP_PACS_AET", "ORTHANC"),
                         "viewer_url": os.environ.get("FUSIONMAP_PACS_VIEWER", "")},
    }


@app.get("/api/colormaps")
def colormaps():
    return all_luts()


@app.get("/api/benchmark")
def benchmark():
    for p in BENCHMARK_PATHS:
        if p.exists():
            return json.loads(p.read_text())
    raise HTTPException(404, "no benchmark has been run yet (fusionmap benchmark)")


# ── cases ────────────────────────────────────────────────────────────────────────────────
@app.get("/api/cases")
def list_cases():
    cs = sorted(manager.cases.values(), key=lambda c: -c.created)
    return [c.public() for c in cs]


@app.post("/api/cases/demo")
def create_demo(body: DemoIn):
    cfg = PhantomConfig(seed=body.seed, tracer=body.tracer, n_lesions=body.n_lesions, lesion_mix=body.lesion_mix,
                        rotation_deg=body.rotation_deg, translation_mm=body.translation_mm,
                        nonrigid_mm=body.nonrigid_mm, pet_fwhm_mm=body.pet_fwhm_mm, pet_snr=body.pet_snr,
                        mri_spacing=body.mri_spacing)
    opts = {"pet_fwhm_mm": body.pet_fwhm_mm, **_clean(body.options)}
    c = manager.new_phantom_case(cfg, opts, body.name)
    if body.run:
        manager.submit(c.id)
    return c.public()


@app.post("/api/cases/upload")
async def create_upload(mri: UploadFile = File(...), pet: UploadFile = File(...), name: str | None = Form(None),
                        options: str | None = Form(None), run: bool = Form(True)):
    tmp = Path(tempfile.mkdtemp(prefix="fm_upload_"))
    paths = []
    for f, stem in ((mri, "mri"), (pet, "pet")):
        fname = Path(f.filename or stem).name
        suffix = "".join(Path(fname).suffixes) or ".bin"
        if suffix.lower() not in (".zip", ".nii", ".nii.gz", ".mha", ".nrrd", ".dcm"):
            raise HTTPException(400, f"{stem}: upload a .zip of DICOM files or a .nii/.nii.gz volume")
        dst = tmp / (stem + suffix)
        with dst.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        paths.append(dst)
    try:
        opts = _clean(PipelineOptionsIn(**json.loads(options))) if options else {}
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(400, f"invalid options: {e}") from e
    c = manager.new_upload_case(paths[0], paths[1], opts, name)
    shutil.rmtree(tmp, ignore_errors=True)
    if run:
        manager.submit(c.id)
    return c.public()


@app.get("/api/cases/{cid}")
def get_case(cid: str):
    return _case(cid).public(with_report=True, root=manager.root)


@app.delete("/api/cases/{cid}")
def delete_case(cid: str):
    if not manager.delete(cid):
        raise HTTPException(404, "not found")
    return {"deleted": cid}


@app.post("/api/cases/{cid}/run")
def run_case(cid: str, body: PipelineOptionsIn | None = None):
    _case(cid)
    return manager.submit(cid, _clean(body)).public()


@app.get("/api/cases/{cid}/events")
async def events(cid: str):
    c = _case(cid)

    async def stream():
        i = 0
        idle = 0
        while True:
            evs = c.events
            while i < len(evs):
                yield f"data: {json.dumps(evs[i])}\n\n"
                i += 1
            if c.status in ("done", "error") and i >= len(c.events):
                yield f"data: {json.dumps({'type': 'status', 'status': c.status, 'error': c.error})}\n\n"
                return
            idle += 1
            if idle % 50 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.15)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/cases/{cid}/viewer/{name}")
def viewer_file(cid: str, name: str):
    _case(cid)
    p = (manager.dir(cid) / "viewer" / name).resolve()
    if not str(p).startswith(str((manager.dir(cid) / "viewer").resolve())) or not p.exists():
        raise HTTPException(404, "not found")
    if name.endswith(".u8.gz"):
        return Response(p.read_bytes(), media_type="application/octet-stream",
                        headers={"Content-Encoding": "gzip", "Cache-Control": "max-age=3600"})
    return FileResponse(p)


EXPORTS = {
    "dicom.zip": ("exports/fusionmap_dicom.zip", "application/zip"),
    "pet.nii.gz": ("exports/pet_fused_grid.nii.gz", "application/gzip"),
    "mri.nii.gz": ("exports/mri_fused_grid.nii.gz", "application/gzip"),
    "report.json": ("report.json", "application/json"),
}


@app.get("/api/cases/{cid}/exports/{name}")
def export_file(cid: str, name: str):
    c = _case(cid)
    if name == "report.html":
        from ..export.report import render_report

        rp = manager.dir(cid) / "report.json"
        if not rp.exists():
            raise HTTPException(404, "case has not been processed")
        return HTMLResponse(render_report(c.public(), json.loads(rp.read_text()), manager.dir(cid)))
    if name not in EXPORTS:
        raise HTTPException(404, "unknown export")
    rel, media = EXPORTS[name]
    p = manager.dir(cid) / rel
    if not p.exists():
        raise HTTPException(404, "export not available — run the pipeline first")
    return FileResponse(p, media_type=media, filename=f"fusionmap_{cid}_{name}")


@app.post("/api/cases/{cid}/pacs")
def pacs_push(cid: str, body: PacsIn):
    _case(cid)
    folder = manager.dir(cid) / "exports" / "fusionmap_dicom_dicom"
    if not folder.exists():
        raise HTTPException(404, "no DICOM export for this case")
    return push_folder(folder, body.host, body.port, body.called_aet, body.calling_aet)


@app.post("/api/pacs/echo")
def pacs_echo(body: PacsIn):
    try:
        return {"ok": echo(body.host, body.port, body.called_aet, body.calling_aet)}
    except (OSError, RuntimeError) as e:
        return {"ok": False, "error": str(e)}


# ── web app ──────────────────────────────────────────────────────────────────────────────
@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    target = (STATIC / path).resolve()
    if path and target.is_file() and str(target).startswith(str(STATIC.resolve())):
        return FileResponse(target)
    index = STATIC / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"message": "FusionMap API is running. Build the web app (cd web && npm run build) "
                                    "or open /docs for the API.", "version": __version__})
