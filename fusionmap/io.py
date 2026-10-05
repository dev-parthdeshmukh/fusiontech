"""Loading scans the way hospitals store them: DICOM series (folders or .zip) or NIfTI.

PET DICOM is converted to **SUV body-weight** when the radiopharmaceutical tags are present
(decay-corrected injected dose, patient weight), which is what nuclear-medicine physicians read.
"""

from __future__ import annotations

import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pydicom
import SimpleITK as sitk

from . import imaging as im

NIFTI_SUFFIXES = (".nii", ".nii.gz", ".mha", ".mhd", ".nrrd")


@dataclass
class ScanMeta:
    """Identity and provenance carried through to the exported DICOM objects."""

    modality: str = "OT"
    patient_name: str = "ANONYMOUS"
    patient_id: str = "FM-0000"
    patient_sex: str = ""
    patient_birth_date: str = ""
    study_instance_uid: str = ""
    study_date: str = ""
    study_description: str = ""
    frame_of_reference_uid: str = ""
    series_description: str = ""
    accession_number: str = ""
    units: str = ""
    suv_factor: float | None = None
    source: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Scan:
    image: sitk.Image
    meta: ScanMeta


def load_scan(path: str | Path, modality_hint: str | None = None) -> Scan:
    """Load a NIfTI/MHA/NRRD file, a DICOM folder, a single DICOM file's series or a .zip."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    if p.is_file() and p.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="fusionmap_zip_"))
        with zipfile.ZipFile(p) as zf:
            _safe_extract(zf, tmp)
        return load_scan(tmp, modality_hint)
    if p.is_file() and p.name.lower().endswith(NIFTI_SUFFIXES):
        img = im.canonical(sitk.ReadImage(str(p)))
        meta = ScanMeta(modality=(modality_hint or "OT").upper(), source=p.name)
        return Scan(img, meta)
    folder = p if p.is_dir() else p.parent
    return _load_dicom_folder(folder, modality_hint)


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if not str(target).startswith(str(root)):
            raise ValueError(f"unsafe path in archive: {member.filename}")
    zf.extractall(dest)


def _load_dicom_folder(folder: Path, modality_hint: str | None) -> Scan:
    # find every series below ``folder`` and keep the one with the most slices
    best: tuple[int, Path, str] | None = None
    dirs = [folder] + [d for d in folder.rglob("*") if d.is_dir()]
    for d in dirs:
        for sid in sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(d)) or []:
            files = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(d), sid)
            if best is None or len(files) > best[0]:
                best = (len(files), d, sid)
    if best is None:
        nifti = [f for f in folder.rglob("*") if f.name.lower().endswith(NIFTI_SUFFIXES)]
        if nifti:
            return load_scan(nifti[0], modality_hint)
        raise ValueError(f"no DICOM series or NIfTI volume found in {folder}")
    _, d, sid = best
    files = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(d), sid)
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(files)
    img = reader.Execute()
    ds = pydicom.dcmread(files[0], stop_before_pixels=True)
    meta = _meta_from_dataset(ds, modality_hint)
    meta.source = f"DICOM series ({len(files)} files)"
    img = im.canonical(img)
    if meta.modality == "PT":
        factor = suv_factor(ds)
        if factor is not None:
            img = img * float(factor)
            meta.suv_factor = float(factor)
            meta.units = "SUVbw"
    return Scan(img, meta)


def _meta_from_dataset(ds: pydicom.Dataset, modality_hint: str | None) -> ScanMeta:
    def g(tag: str, default: str = "") -> str:
        v = ds.get(tag, default)
        return str(v) if v is not None else default

    return ScanMeta(
        modality=g("Modality", modality_hint or "OT").upper() or (modality_hint or "OT").upper(),
        patient_name=g("PatientName", "ANONYMOUS"),
        patient_id=g("PatientID", "FM-0000"),
        patient_sex=g("PatientSex"),
        patient_birth_date=g("PatientBirthDate"),
        study_instance_uid=g("StudyInstanceUID"),
        study_date=g("StudyDate"),
        study_description=g("StudyDescription"),
        frame_of_reference_uid=g("FrameOfReferenceUID"),
        series_description=g("SeriesDescription"),
        accession_number=g("AccessionNumber"),
        units=g("Units"),
    )


def suv_factor(ds: pydicom.Dataset) -> float | None:
    """Multiplicative factor converting stored PET values (Bq/ml) to SUV body-weight.

    SUVbw = C(t) [Bq/ml] * weight [g] / (dose [Bq] * 2^(-dt / T1/2)).
    Returns ``None`` when the data are not Bq/ml or the needed tags are missing.
    """
    try:
        if str(ds.get("Units", "")).upper() not in ("BQML", ""):
            return None
        weight_kg = float(ds.PatientWeight)
        rp = ds.RadiopharmaceuticalInformationSequence[0]
        dose = float(rp.RadionuclideTotalDose)
        half_life = float(rp.RadionuclideHalfLife)
        start = _dicom_time(str(rp.get("RadiopharmaceuticalStartTime", "")))
        acq = _dicom_time(str(ds.get("SeriesTime", ds.get("AcquisitionTime", ""))))
        if weight_kg <= 0 or dose <= 0 or half_life <= 0:
            return None
        dt = (acq - start).total_seconds() if (start and acq) else 0.0
        if dt < 0:
            dt += 24 * 3600
        decayed = dose * 2.0 ** (-dt / half_life)
        return weight_kg * 1000.0 / decayed
    except (AttributeError, IndexError, KeyError, ValueError, TypeError):
        return None


def _dicom_time(s: str) -> datetime | None:
    s = s.strip()
    if not s:
        return None
    s = s.split(".")[0]
    try:
        if len(s) >= 6:
            return datetime.strptime(s[:6], "%H%M%S")
        if len(s) >= 4:
            return datetime.strptime(s[:4], "%H%M")
    except ValueError:
        return None
    return None


def summarize_image(img: sitk.Image) -> dict:
    a = sitk.GetArrayViewFromImage(img)
    return {
        "size": list(img.GetSize()),
        "spacing_mm": [round(float(s), 4) for s in img.GetSpacing()],
        "origin_mm": [round(float(o), 3) for o in img.GetOrigin()],
        "fov_mm": [round(float(n * s), 1) for n, s in zip(img.GetSize(), img.GetSpacing())],
        "min": float(np.min(a)),
        "max": float(np.max(a)),
    }
