import threading
import zipfile

import numpy as np
import pydicom
import pytest
import SimpleITK as sitk

from fusionmap import imaging as im
from fusionmap.export.dicom import export_bundle, write_acquisition_dicom
from fusionmap.io import ScanMeta, load_scan, suv_factor


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    ref = im.empty_like_grid((-20.0, -30.0, -10.0), (2.0, 2.0, 2.0), (24, 20, 10))
    z, y, x = np.indices((10, 20, 24))
    mri = (100 + 10 * x).astype(np.float32)
    pet = np.exp(-(((x - 12) ** 2 + (y - 10) ** 2 + (z - 5) ** 2) / 8.0)).astype(np.float32) * 12.0
    labels = (pet > 4).astype(np.uint8)
    rgb = np.zeros((10, 20, 24, 3), np.uint8)
    rgb[..., 0] = 200
    out = tmp_path_factory.mktemp("bundle") / "fm.zip"
    meta = ScanMeta(patient_name="TEST^PATIENT", patient_id="P123", modality="MR")
    manifest = export_bundle(out, ref, mri, pet, pet * 1.1, rgb, labels, meta, tracer="fdg")
    return out, manifest, ref, pet


def _datasets(folder):
    return [pydicom.dcmread(f) for f in sorted(folder.rglob("*.dcm"))]


def test_bundle_structure(bundle):
    out, manifest, _, _ = bundle
    assert out.exists() and manifest["slices"] == 10
    names = zipfile.ZipFile(out).namelist()
    for d in ("MR/", "PET_REG/", "PET_AI/", "FUSED/", "RTSTRUCT/"):
        assert any(n.startswith(d) for n in names), d


def test_shared_study_and_frame_of_reference(bundle):
    _, manifest, _, _ = bundle
    from pathlib import Path

    ds = _datasets(Path(manifest["folder"]))
    assert {d.StudyInstanceUID for d in ds} == {manifest["study_instance_uid"]}
    assert {d.FrameOfReferenceUID for d in ds} == {manifest["frame_of_reference_uid"]}
    assert {d.PatientID for d in ds} == {"P123"}
    assert {d.Modality for d in ds} == {"MR", "PT", "OT", "RTSTRUCT"}


def test_pet_values_roundtrip_as_suv(bundle):
    _, manifest, ref, pet = bundle
    from pathlib import Path

    folder = Path(manifest["folder"]) / "PET_REG"
    img = sitk.ReadImage(sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(folder)))
    a = sitk.GetArrayFromImage(img)
    assert np.allclose(a, pet, atol=pet.max() / 3000)
    assert np.allclose(img.GetSpacing(), ref.GetSpacing()) and np.allclose(img.GetOrigin(), ref.GetOrigin())
    d = pydicom.dcmread(sorted(folder.glob("*.dcm"))[0])
    assert d.Units == "GML" and d.RadiopharmaceuticalInformationSequence[0].Radiopharmaceutical == "Fluorodeoxyglucose"


def test_rgb_and_rtstruct(bundle):
    _, manifest, ref, _ = bundle
    from pathlib import Path

    f = pydicom.dcmread(sorted((Path(manifest["folder"]) / "FUSED").glob("*.dcm"))[0])
    assert f.PhotometricInterpretation == "RGB" and f.SamplesPerPixel == 3
    assert f.pixel_array.shape == (20, 24, 3)
    rs = pydicom.dcmread(Path(manifest["folder"]) / "RTSTRUCT" / "RS.dcm")
    assert len(rs.StructureSetROISequence) == 1
    mr_uids = {d.SOPInstanceUID for d in _datasets(Path(manifest["folder"]) / "MR")}
    contour = rs.ROIContourSequence[0].ContourSequence[0]
    assert contour.ContourGeometricType == "CLOSED_PLANAR"
    assert contour.ContourImageSequence[0].ReferencedSOPInstanceUID in mr_uids
    pts = np.array(contour.ContourData, float).reshape(-1, 3)
    lo, hi = im.physical_bounds(ref)
    assert np.all(pts >= lo - 1e-6) and np.all(pts <= hi + 1e-6)
    assert manifest["rtstruct_contours"] > 0


def test_acquisition_dicom_suv_conversion(phantom, tmp_path):
    info = write_acquisition_dicom(phantom.mri, phantom.pet, tmp_path / "acq", patient_id="X1")
    pet = load_scan(tmp_path / "acq" / "PET", "PT")
    mri = load_scan(tmp_path / "acq" / "MRI", "MR")
    assert pet.meta.modality == "PT" and pet.meta.units == "SUVbw"
    assert mri.meta.modality == "MR"
    assert pet.meta.study_instance_uid != mri.meta.study_instance_uid  # two separate scanners
    a = im.arr(pet.image)
    b = im.arr(im.canonical(phantom.pet))
    assert abs(a.max() - b.max()) / b.max() < 0.01  # Bq/ml -> SUV recovered
    ds = pydicom.dcmread(sorted((tmp_path / "acq" / "PET").glob("*.dcm"))[0])
    assert abs(suv_factor(ds) * info["bq_per_suv"] - 1.0) < 1e-3


def test_zip_upload_path(phantom, tmp_path):
    write_acquisition_dicom(phantom.mri, phantom.pet, tmp_path / "acq")
    z = tmp_path / "pet.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in (tmp_path / "acq" / "PET").glob("*.dcm"):
            zf.write(f, f"series/{f.name}")
    scan = load_scan(z, "PT")
    assert scan.image.GetSize() == phantom.pet.GetSize()


def test_zip_slip_rejected(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../escape.txt", "x")
    with pytest.raises(ValueError):
        load_scan(z)


def test_pacs_cstore_roundtrip(bundle):
    from pathlib import Path

    from pynetdicom import AE, evt
    from pynetdicom.sop_class import Verification

    from fusionmap.export import echo, push_folder
    from fusionmap.export.pacs import STORAGE_CLASSES

    received = []

    def on_store(event):
        received.append(event.dataset.SOPInstanceUID)
        return 0x0000

    ae = AE(ae_title="TEST-SCP")
    for uid in STORAGE_CLASSES:
        ae.add_supported_context(uid, "1.2.840.10008.1.2.1")
    ae.add_supported_context(Verification)
    server = ae.start_server(("127.0.0.1", 0), block=False, evt_handlers=[(evt.EVT_C_STORE, on_store)])
    port = server.server_address[1]
    try:
        assert echo("127.0.0.1", port, "TEST-SCP")
        _, manifest, _, _ = bundle
        res = push_folder(Path(manifest["folder"]), "127.0.0.1", port, "TEST-SCP")
        assert res["ok"] and res["sent"] == res["total"] == len(received) > 40
    finally:
        server.shutdown()
    assert threading.active_count() >= 1
