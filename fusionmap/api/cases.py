"""Case store and background job runner."""

from __future__ import annotations

import json
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import SimpleITK as sitk

from .. import imaging as im
from ..io import Scan, ScanMeta, load_scan
from ..phantom import Phantom, PhantomConfig, make_phantom
from ..pipeline import PipelineOptions, run_pipeline


@dataclass
class Case:
    id: str
    name: str
    kind: str  # phantom | upload
    created: float
    status: str = "created"  # created | queued | running | done | error
    options: dict = field(default_factory=dict)
    phantom: dict | None = None
    error: str | None = None
    events: list[dict] = field(default_factory=list)
    finished: float | None = None

    def public(self, with_report: bool = False, root: Path | None = None) -> dict:
        d = asdict(self)
        d.pop("events")
        d["steps"] = self.step_states()
        if with_report and root is not None:
            rp = root / self.id / "report.json"
            d["report"] = json.loads(rp.read_text()) if rp.exists() else None
        return d

    def step_states(self) -> dict:
        states: dict[str, dict] = {}
        for e in self.events:
            if e.get("type") == "step":
                states[e["step"]] = {k: e.get(k) for k in ("status", "label", "seconds", "message")}
            elif e.get("type") == "progress" and e["step"] in states:
                states[e["step"]]["progress"] = e.get("progress")
                states[e["step"]]["message"] = e.get("message")
        return states


class CaseManager:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.cases: dict[str, Case] = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fusionmap-job")
        self._load_existing()

    # ---- persistence -----------------------------------------------------------------
    def _load_existing(self):
        for f in sorted(self.root.glob("*/case.json")):
            try:
                d = json.loads(f.read_text())
                c = Case(**{k: v for k, v in d.items() if k in Case.__dataclass_fields__})
                if c.status in ("queued", "running"):
                    c.status, c.error = "error", "server restarted while the job was running"
                self.cases[c.id] = c
            except (json.JSONDecodeError, TypeError):
                continue

    def _save(self, c: Case):
        d = self.root / c.id
        d.mkdir(parents=True, exist_ok=True)
        (d / "case.json").write_text(json.dumps(asdict(c), default=str))

    def dir(self, cid: str) -> Path:
        return self.root / cid

    # ---- creation ----------------------------------------------------------------------
    def new_phantom_case(self, cfg: PhantomConfig, options: dict, name: str | None = None) -> Case:
        cid = uuid.uuid4().hex[:10]
        c = Case(id=cid, name=name or f"Phantom patient #{cfg.seed} ({cfg.tracer.upper()})", kind="phantom",
                 created=time.time(), options=options, phantom=asdict(cfg))
        with self.lock:
            self.cases[cid] = c
        self._save(c)
        return c

    def new_upload_case(self, mri_path: Path, pet_path: Path, options: dict, name: str | None = None) -> Case:
        cid = uuid.uuid4().hex[:10]
        inputs = self.dir(cid) / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        for src, dst in ((mri_path, "mri"), (pet_path, "pet")):
            target = inputs / (dst + "".join(Path(src).suffixes))
            shutil.move(str(src), target)
        c = Case(id=cid, name=name or "Uploaded study", kind="upload", created=time.time(), options=options)
        with self.lock:
            self.cases[cid] = c
        self._save(c)
        return c

    def delete(self, cid: str) -> bool:
        with self.lock:
            c = self.cases.pop(cid, None)
        if c is None:
            return False
        shutil.rmtree(self.dir(cid), ignore_errors=True)
        return True

    # ---- execution ---------------------------------------------------------------------
    def emit(self, c: Case, event: dict):
        event = {**event, "t": round(time.time() - c.created, 3)}
        with self.lock:
            c.events.append(event)

    def submit(self, cid: str, options: dict | None = None) -> Case:
        c = self.cases[cid]
        if c.status in ("queued", "running"):
            return c
        if options:
            c.options = {**c.options, **options}
        c.status, c.error, c.events, c.finished = "queued", None, [], None
        self._save(c)
        self.pool.submit(self._run, cid)
        return c

    def _run(self, cid: str):
        c = self.cases[cid]
        c.status = "running"
        self._save(c)
        folder = self.dir(cid)
        try:
            phantom = None
            if c.kind == "phantom":
                phantom, mri, pet = self._phantom_inputs(c, folder)
            else:
                mri, pet = self._upload_inputs(c, folder)
            extra = {"tracer": (c.phantom or {}).get("tracer")}
            if c.kind == "phantom":
                extra["working_spacing_mm"] = float((c.phantom or {}).get("mri_spacing", 1.0))
            opts = PipelineOptions.from_dict({**c.options, **extra})
            run_pipeline(folder, mri, pet, opts, emit=lambda e: self.emit(c, e), phantom=phantom)
            c.status = "done"
        except Exception as e:  # report every failure to the UI
            c.status, c.error = "error", f"{type(e).__name__}: {e}"
            self.emit(c, {"type": "error", "message": c.error, "trace": traceback.format_exc()[-2000:]})
        finally:
            c.finished = time.time()
            self._save(c)

    def _phantom_inputs(self, c: Case, folder: Path):
        truth = folder / "truth"
        self.emit(c, {"type": "step", "step": "simulate", "label": "Simulate patient", "status": "running"})
        t = time.perf_counter()
        if (truth / "truth.json").exists():
            ph = Phantom.load(truth)
        else:
            ph = make_phantom(PhantomConfig.from_dict(c.phantom or {}))
            ph.save(truth)
        inputs = folder / "inputs"
        inputs.mkdir(exist_ok=True)
        if not (inputs / "mri.nii.gz").exists():
            sitk.WriteImage(sitk.Cast(ph.mri, sitk.sitkInt16), str(inputs / "mri.nii.gz"))
            sitk.WriteImage(ph.pet, str(inputs / "pet.nii.gz"))
        self.emit(c, {"type": "step", "step": "simulate", "label": "Simulate patient", "status": "done",
                      "seconds": round(time.perf_counter() - t, 3)})
        seed = (c.phantom or {}).get("seed", 0)
        mri = Scan(im.to_float(ph.mri), ScanMeta(modality="MR", patient_name=f"PHANTOM^SEED{seed}",
                                                 patient_id=f"FM-PH-{seed:04d}", source="FusionMap phantom",
                                                 study_description="FusionMap phantom PET/MRI"))
        pet = Scan(ph.pet, ScanMeta(modality="PT", units="SUVbw", source="FusionMap phantom"))
        return ph, mri, pet

    def _upload_inputs(self, c: Case, folder: Path):
        inputs = folder / "inputs"
        mri_f = next(iter(sorted(inputs.glob("mri*"))))
        pet_f = next(iter(sorted(inputs.glob("pet*"))))
        self.emit(c, {"type": "step", "step": "simulate", "label": "Read uploaded scans", "status": "running"})
        mri = load_scan(mri_f, "MR")
        pet = load_scan(pet_f, "PT")
        self.emit(c, {"type": "step", "step": "simulate", "label": "Read uploaded scans", "status": "done"})
        return mri, pet
