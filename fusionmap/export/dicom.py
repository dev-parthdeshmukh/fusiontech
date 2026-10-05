"""DICOM writers — the output "drops directly into the hospital's existing radiology system".

The export is a self-contained, standards-conformant bundle sharing one Study and one
Frame of Reference, so any PACS viewer or treatment-planning system links them spatially:

* ``MR``       MR Image Storage — the reference anatomy on the fusion grid
* ``PET_REG``  PET Image Storage — PET registered to the MRI, quantitative (SUVbw, ``GML``)
* ``PET_AI``   PET Image Storage — MRI-guided AI-enhanced PET
* ``FUSED``    Secondary Capture, RGB — colour-coded PET/MRI fusion as displayed
* ``RTSTRUCT`` RT Structure Set — PET biological tumour volumes as closed planar contours
"""

from __future__ import annotations

import datetime as dt
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import (
    PYDICOM_IMPLEMENTATION_UID,
    ExplicitVRLittleEndian,
    MRImageStorage,
    PositronEmissionTomographyImageStorage,
    RTStructureSetStorage,
    SecondaryCaptureImageStorage,
    generate_uid,
)
from skimage import measure

from .. import DISCLAIMER, __version__
from ..io import ScanMeta

STUDY_COMPONENT_SOP = "1.2.840.10008.3.1.2.3.1"  # Detached Study Management (RT reference convention)
F18_HALF_LIFE_S = 6586.2

TRACER_NAMES = {"fdg": ("Fluorodeoxyglucose", "18F-FDG"), "fet": ("Fluoroethyltyrosine", "18F-FET")}


@dataclass
class StudyContext:
    meta: ScanMeta
    study_uid: str
    frame_of_reference_uid: str
    now: dt.datetime
    tracer: str | None = None

    @classmethod
    def from_meta(cls, meta: ScanMeta, tracer: str | None = None) -> StudyContext:
        return cls(
            meta=meta,
            study_uid=meta.study_instance_uid or generate_uid(),
            frame_of_reference_uid=meta.frame_of_reference_uid or generate_uid(),
            now=dt.datetime.now(),
            tracer=tracer,
        )


def _base(ctx: StudyContext, sop_class: str, modality: str, series_uid: str, series_number: int,
          description: str) -> Dataset:
    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = sop_class
    fm.MediaStorageSOPInstanceUID = generate_uid()
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    fm.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    fm.ImplementationVersionName = "FUSIONMAP_1"
    ds = Dataset()
    ds.file_meta = fm
    ds.SpecificCharacterSet = "ISO_IR 100"
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID
    date, time = ctx.now.strftime("%Y%m%d"), ctx.now.strftime("%H%M%S")
    m = ctx.meta
    ds.PatientName = m.patient_name or "ANONYMOUS"
    ds.PatientID = m.patient_id or "FM-0000"
    ds.PatientBirthDate = m.patient_birth_date or ""
    ds.PatientSex = m.patient_sex or ""
    ds.StudyInstanceUID = ctx.study_uid
    ds.StudyDate = m.study_date or date
    ds.StudyTime = time
    ds.StudyID = "1"
    ds.AccessionNumber = m.accession_number or ""
    ds.ReferringPhysicianName = ""
    ds.StudyDescription = m.study_description or "FusionMap PET/MRI fusion"
    ds.Modality = modality
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.SeriesDescription = description
    ds.SeriesDate = date
    ds.SeriesTime = time
    ds.ContentDate = date
    ds.ContentTime = time
    ds.InstanceCreationDate = date
    ds.InstanceCreationTime = time
    ds.Manufacturer = "FusionMap (Team Code Blooded)"
    ds.ManufacturerModelName = "FusionMap"
    ds.SoftwareVersions = __version__
    ds.FrameOfReferenceUID = ctx.frame_of_reference_uid
    ds.PositionReferenceIndicator = ""
    ds.ImageComments = DISCLAIMER
    ds.BurnedInAnnotation = "NO"
    return ds


def _plane(ds: Dataset, ref: sitk.Image, k: int) -> None:
    ox, oy, oz = ref.GetOrigin()
    sx, sy, sz = ref.GetSpacing()
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [round(ox, 4), round(oy, 4), round(oz + k * sz, 4)]
    ds.PixelSpacing = [round(sy, 6), round(sx, 6)]
    ds.SliceThickness = round(sz, 6)
    ds.SpacingBetweenSlices = round(sz, 6)
    ds.SliceLocation = round(oz + k * sz, 4)
    ds.InstanceNumber = k + 1
    ds.Rows, ds.Columns = ref.GetSize()[1], ref.GetSize()[0]


def _mono16(ds: Dataset, pixels: np.ndarray) -> None:
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelData = np.ascontiguousarray(pixels.astype("<u2")).tobytes()


def _save(ds: Dataset, path: Path) -> None:
    ds.save_as(path, enforce_file_format=True)


def write_mr_series(vol: np.ndarray, ref: sitk.Image, ctx: StudyContext, folder: Path) -> tuple[str, list[str]]:
    folder.mkdir(parents=True, exist_ok=True)
    uid = generate_uid()
    hi = float(np.percentile(vol, 99.9)) or 1.0
    scaled = np.clip(vol / hi * 3000.0, 0, 4095)
    sop_uids = []
    for k in range(vol.shape[0]):
        ds = _base(ctx, MRImageStorage, "MR", uid, 900, "FusionMap MR reference (fusion grid)")
        ds.ImageType = ["DERIVED", "SECONDARY", "AXIAL"]
        ds.ScanningSequence = "RM"
        ds.SequenceVariant = "NONE"
        ds.ScanOptions = ""
        ds.MRAcquisitionType = "3D"
        ds.RepetitionTime = ""
        ds.EchoTime = ""
        ds.EchoTrainLength = ""
        _plane(ds, ref, k)
        ds.WindowCenter = 1500
        ds.WindowWidth = 3000
        ds.RescaleIntercept = 0
        ds.RescaleSlope = 1
        _mono16(ds, np.round(scaled[k]))
        _save(ds, folder / f"MR_{k + 1:04d}.dcm")
        sop_uids.append(ds.SOPInstanceUID)
    return uid, sop_uids


def write_pet_series(vol_suv: np.ndarray, ref: sitk.Image, ctx: StudyContext, folder: Path, number: int,
                     description: str) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    uid = generate_uid()
    name, label = TRACER_NAMES.get(ctx.tracer or "", ("", ""))
    hi = float(np.percentile(vol_suv, 99.9)) or 1.0
    for k in range(vol_suv.shape[0]):
        ds = _base(ctx, PositronEmissionTomographyImageStorage, "PT", uid, number, description)
        ds.ImageType = ["DERIVED", "SECONDARY"]
        ds.SeriesType = ["STATIC", "IMAGE"]
        ds.Units = "GML"  # SUV body-weight
        ds.CountsSource = "EMISSION"
        ds.CorrectedImage = ["DECY", "ATTN"]
        ds.DecayCorrection = "START"
        ds.NumberOfSlices = vol_suv.shape[0]
        ds.FrameReferenceTime = 0
        ds.ImageIndex = k + 1
        ds.AcquisitionDate = ctx.now.strftime("%Y%m%d")
        ds.AcquisitionTime = ctx.now.strftime("%H%M%S")
        ds.ActualFrameDuration = ""
        ds.DecayFactor = 1
        rp = Dataset()
        rp.Radiopharmaceutical = name
        rp.RadionuclideHalfLife = F18_HALF_LIFE_S if name else ""
        rp.RadiopharmaceuticalStartTime = ""
        rp.RadionuclideTotalDose = ""
        ds.RadiopharmaceuticalInformationSequence = Sequence([rp])
        _plane(ds, ref, k)
        sl = np.clip(vol_suv[k], 0, None)
        slope = max(float(sl.max()) / 65000.0, 1e-6)
        ds.RescaleIntercept = 0
        ds.RescaleSlope = f"{slope:.8g}"[:16]
        ds.WindowCenter = round(hi / 2, 4)
        ds.WindowWidth = round(hi, 4)
        _mono16(ds, np.round(sl / float(ds.RescaleSlope)))
        if label:
            ds.SeriesDescription = f"{description} ({label})"
        _save(ds, folder / f"PT_{k + 1:04d}.dcm")
    return uid


def write_fused_series(rgb: np.ndarray, ref: sitk.Image, ctx: StudyContext, folder: Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    uid = generate_uid()
    for k in range(rgb.shape[0]):
        ds = _base(ctx, SecondaryCaptureImageStorage, "OT", uid, 903, "FusionMap colour PET/MR fusion")
        ds.ImageType = ["DERIVED", "SECONDARY", "FUSION"]
        ds.ConversionType = "WSD"
        _plane(ds, ref, k)
        ds.SamplesPerPixel = 3
        ds.PhotometricInterpretation = "RGB"
        ds.PlanarConfiguration = 0
        ds.BitsAllocated = 8
        ds.BitsStored = 8
        ds.HighBit = 7
        ds.PixelRepresentation = 0
        ds.PixelData = np.ascontiguousarray(rgb[k]).tobytes()
        _save(ds, folder / f"FUSED_{k + 1:04d}.dcm")
    return uid


ROI_COLORS = [(255, 60, 60), (255, 200, 0), (0, 200, 255), (120, 255, 120), (255, 120, 255), (255, 140, 0)]


def write_rtstruct(labels: np.ndarray, names: dict[int, str], ref: sitk.Image, ctx: StudyContext,
                   mr_series_uid: str, mr_sop_uids: list[str], path: Path) -> int:
    """Closed planar contours for every label > 0, referencing the MR series slices."""
    ox, oy, oz = ref.GetOrigin()
    sx, sy, sz = ref.GetSpacing()
    ds = _base(ctx, RTStructureSetStorage, "RTSTRUCT", generate_uid(), 904, "FusionMap PET BTV contours")
    ds.StructureSetLabel = "FusionMap BTV"
    ds.StructureSetName = "PET biological tumour volumes"
    ds.StructureSetDate = ctx.now.strftime("%Y%m%d")
    ds.StructureSetTime = ctx.now.strftime("%H%M%S")
    ds.InstanceNumber = 1
    ds.ApprovalStatus = "UNAPPROVED"

    contour_imgs = Sequence()
    for sop in mr_sop_uids:
        ci = Dataset()
        ci.ReferencedSOPClassUID = MRImageStorage
        ci.ReferencedSOPInstanceUID = sop
        contour_imgs.append(ci)
    rs = Dataset()
    rs.SeriesInstanceUID = mr_series_uid
    rs.ContourImageSequence = contour_imgs
    st = Dataset()
    st.ReferencedSOPClassUID = STUDY_COMPONENT_SOP
    st.ReferencedSOPInstanceUID = ctx.study_uid
    st.RTReferencedSeriesSequence = Sequence([rs])
    fr = Dataset()
    fr.FrameOfReferenceUID = ctx.frame_of_reference_uid
    fr.RTReferencedStudySequence = Sequence([st])
    ds.ReferencedFrameOfReferenceSequence = Sequence([fr])

    roi_seq, contour_seq, obs_seq = Sequence(), Sequence(), Sequence()
    n_contours = 0
    for i, lid in enumerate(sorted(int(v) for v in np.unique(labels) if v > 0)):
        roi = Dataset()
        roi.ROINumber = lid
        roi.ReferencedFrameOfReferenceUID = ctx.frame_of_reference_uid
        roi.ROIName = names.get(lid, f"FM_BTV_{lid}")
        roi.ROIGenerationAlgorithm = "AUTOMATIC"
        roi_seq.append(roi)
        rc = Dataset()
        rc.ROIDisplayColor = list(ROI_COLORS[i % len(ROI_COLORS)])
        rc.ReferencedROINumber = lid
        contours = Sequence()
        mask = labels == lid
        for k in np.where(mask.any((1, 2)))[0]:
            sl = np.pad(mask[k].astype(np.float32), 1)
            for c in measure.find_contours(sl, 0.5):
                c = measure.approximate_polygon(c - 1.0, tolerance=0.35)
                if len(c) < 4:
                    continue
                c = c[:-1] if np.allclose(c[0], c[-1]) else c
                pts = np.column_stack([ox + c[:, 1] * sx, oy + c[:, 0] * sy, np.full(len(c), oz + k * sz)])
                cd = Dataset()
                ref_img = Dataset()
                ref_img.ReferencedSOPClassUID = MRImageStorage
                ref_img.ReferencedSOPInstanceUID = mr_sop_uids[int(k)]
                cd.ContourImageSequence = Sequence([ref_img])
                cd.ContourGeometricType = "CLOSED_PLANAR"
                cd.NumberOfContourPoints = len(pts)
                cd.ContourData = [f"{v:.3f}" for v in pts.ravel()]
                contours.append(cd)
                n_contours += 1
        rc.ContourSequence = contours
        contour_seq.append(rc)
        ob = Dataset()
        ob.ObservationNumber = lid
        ob.ReferencedROINumber = lid
        ob.ROIObservationLabel = "PET BTV TBR1.6"
        ob.RTROIInterpretedType = "GTV"
        ob.ROIInterpreter = ""
        obs_seq.append(ob)
    ds.StructureSetROISequence = roi_seq
    ds.ROIContourSequence = contour_seq
    ds.RTROIObservationsSequence = obs_seq
    _save(ds, path)
    return n_contours


def export_bundle(
    out_zip: Path,
    ref: sitk.Image,
    mri: np.ndarray,
    pet_registered: np.ndarray,
    pet_enhanced: np.ndarray | None,
    fused_rgb: np.ndarray,
    hotspot_labels: np.ndarray,
    meta: ScanMeta,
    tracer: str | None = None,
) -> dict:
    """Write all series into ``out_zip``; returns a manifest of what was written."""
    work = out_zip.parent / (out_zip.stem + "_dicom")
    if work.exists():
        for f in sorted(work.rglob("*"), reverse=True):
            f.unlink() if f.is_file() else f.rmdir()
    work.mkdir(parents=True, exist_ok=True)
    ctx = StudyContext.from_meta(meta, tracer)
    mr_uid, mr_sops = write_mr_series(mri, ref, ctx, work / "MR")
    reg_uid = write_pet_series(pet_registered, ref, ctx, work / "PET_REG", 901, "FusionMap PET registered to MR")
    ai_uid = None
    if pet_enhanced is not None:
        ai_uid = write_pet_series(pet_enhanced, ref, ctx, work / "PET_AI", 902, "FusionMap PET AI-enhanced")
    fused_uid = write_fused_series(fused_rgb, ref, ctx, work / "FUSED")
    n_contours = 0
    if np.any(hotspot_labels > 0):
        (work / "RTSTRUCT").mkdir(exist_ok=True)
        names = {int(i): f"FM_BTV_{int(i)}" for i in np.unique(hotspot_labels) if i > 0}
        n_contours = write_rtstruct(hotspot_labels, names, ref, ctx, mr_uid, mr_sops, work / "RTSTRUCT" / "RS.dcm")
    (work / "README.txt").write_text(
        "FusionMap DICOM export\n"
        f"{DISCLAIMER}\n\n"
        "MR/        reference anatomy on the fusion grid (MR Image Storage)\n"
        "PET_REG/   PET registered to MR, SUVbw (PET Image Storage)\n"
        "PET_AI/    MRI-guided AI-enhanced PET, SUVbw (PET Image Storage)\n"
        "FUSED/     colour-coded PET/MR fusion (Secondary Capture, RGB)\n"
        "RTSTRUCT/  PET biological tumour volumes (RT Structure Set)\n\n"
        f"StudyInstanceUID     {ctx.study_uid}\nFrameOfReferenceUID  {ctx.frame_of_reference_uid}\n")
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(work.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(work))
    return {
        "zip": out_zip.name,
        "folder": str(work),
        "study_instance_uid": ctx.study_uid,
        "frame_of_reference_uid": ctx.frame_of_reference_uid,
        "series": {"MR": mr_uid, "PET_REG": reg_uid, "PET_AI": ai_uid, "FUSED": fused_uid},
        "slices": int(mri.shape[0]),
        "rtstruct_contours": n_contours,
        "size_mb": round(out_zip.stat().st_size / 1e6, 2),
    }


def write_acquisition_dicom(mri_img: sitk.Image, pet_img_suv: sitk.Image, folder: Path, patient_id: str = "FM-DEMO",
                            patient_name: str = "DEMO^PATIENT", tracer: str = "fdg", weight_kg: float = 70.0,
                            dose_bq: float = 250e6, uptake_s: float = 3600.0) -> dict:
    """Write MRI and PET as they would arrive from two *separate* scanners.

    Different studies, different frames of reference, PET stored in Bq/ml with the
    radiopharmaceutical tags needed for SUV conversion — exactly the hospital situation
    FusionMap is built for.
    """
    folder = Path(folder)
    now = dt.datetime.now().replace(microsecond=0)
    mri_meta = ScanMeta(patient_name=patient_name, patient_id=patient_id, study_description="MRI brain with contrast")
    mri_ctx = StudyContext.from_meta(mri_meta)
    mri_ctx.now = now - dt.timedelta(days=2)
    write_mr_series(sitk.GetArrayFromImage(mri_img).astype(np.float32), mri_img, mri_ctx, folder / "MRI")

    pet_meta = ScanMeta(patient_name=patient_name, patient_id=patient_id, study_description="PET brain")
    ctx = StudyContext.from_meta(pet_meta, tracer)
    ctx.now = now
    decayed = dose_bq * 2.0 ** (-uptake_s / F18_HALF_LIFE_S)
    bq_per_suv = decayed / (weight_kg * 1000.0)
    vol = sitk.GetArrayFromImage(pet_img_suv).astype(np.float32) * bq_per_suv
    out = folder / "PET"
    out.mkdir(parents=True, exist_ok=True)
    uid = generate_uid()
    name, label = TRACER_NAMES.get(tracer, ("", ""))
    start = (now - dt.timedelta(seconds=uptake_s)).strftime("%H%M%S")
    for k in range(vol.shape[0]):
        ds = _base(ctx, PositronEmissionTomographyImageStorage, "PT", uid, 1, f"PET {label} brain static")
        ds.ImageType = ["ORIGINAL", "PRIMARY"]
        ds.SeriesType = ["STATIC", "IMAGE"]
        ds.Units = "BQML"
        ds.CountsSource = "EMISSION"
        ds.CorrectedImage = ["DECY", "ATTN", "SCAT"]
        ds.DecayCorrection = "START"
        ds.NumberOfSlices = vol.shape[0]
        ds.FrameReferenceTime = 0
        ds.ImageIndex = k + 1
        ds.AcquisitionDate = now.strftime("%Y%m%d")
        ds.AcquisitionTime = now.strftime("%H%M%S")
        ds.ActualFrameDuration = 600000
        ds.DecayFactor = 1
        ds.PatientWeight = weight_kg
        rp = Dataset()
        rp.Radiopharmaceutical = name
        rp.RadionuclideHalfLife = F18_HALF_LIFE_S
        rp.RadiopharmaceuticalStartTime = start
        rp.RadionuclideTotalDose = dose_bq
        ds.RadiopharmaceuticalInformationSequence = Sequence([rp])
        _plane(ds, pet_img_suv, k)
        sl = np.clip(vol[k], 0, None)
        slope = max(float(sl.max()) / 65000.0, 1e-6)
        ds.RescaleIntercept = 0
        ds.RescaleSlope = f"{slope:.8g}"[:16]
        _mono16(ds, np.round(sl / float(ds.RescaleSlope)))
        _save(ds, out / f"PT_{k + 1:04d}.dcm")
    return {"mri": str(folder / "MRI"), "pet": str(folder / "PET"), "bq_per_suv": bq_per_suv}
