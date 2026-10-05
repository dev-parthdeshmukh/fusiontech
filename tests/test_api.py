"""End-to-end through the HTTP API on a fast 2 mm phantom."""

import importlib
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory, monkeypatch_module):
    monkeypatch_module.setenv("FUSIONMAP_DATA", str(tmp_path_factory.mktemp("data")))
    monkeypatch_module.setenv("FUSIONMAP_PREWARM", "0")
    import fusionmap.api.app as appmod

    importlib.reload(appmod)
    with TestClient(appmod.app) as c:
        yield c


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def done_case(client):
    r = client.post("/api/cases/demo", json={"seed": 3, "lesion_mix": "showcase", "n_lesions": 3, "mri_spacing": 2.0,
                                             "options": {"registration": "rigid", "enhancement": "deconv"}})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    for _ in range(600):
        c = client.get(f"/api/cases/{cid}").json()
        if c["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert c["status"] == "done", c.get("error")
    return c


def test_health_and_colormaps(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and "voxelmorph" in h["models"]
    cm = client.get("/api/colormaps").json()
    assert len(cm["hot"]) == 256


def test_report_contents(done_case):
    rep = done_case["report"]
    v = rep["validation"]
    assert v["tre_final"]["mean_mm"] < v["tre_naive"]["mean_mm"] / 3
    assert v["detection"]["detected"] >= 1
    assert rep["registration"]["nmi_after"] > rep["registration"]["nmi_before"]
    assert set(done_case["steps"]) >= {"simulate", "load", "register", "enhance", "fuse", "export", "validate"}


def test_viewer_assets(client, done_case):
    cid = done_case["id"]
    m = client.get(f"/api/cases/{cid}/viewer/manifest.json").json()
    vol = m["volumes"]["mri"]
    raw = client.get(f"/api/cases/{cid}/viewer/{vol['file']}").content
    assert len(raw) == int(np.prod(m["shape_zyx"]))
    assert client.get(f"/api/cases/{cid}/viewer/mip.png").headers["content-type"] == "image/png"
    assert client.get(f"/api/cases/{cid}/viewer/../case.json").status_code == 404


def test_exports(client, done_case):
    cid = done_case["id"]
    z = client.get(f"/api/cases/{cid}/exports/dicom.zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"
    html = client.get(f"/api/cases/{cid}/exports/report.html")
    assert html.status_code == 200 and "FusionMap PET/MRI fusion report" in html.text
    assert client.get(f"/api/cases/{cid}/exports/nope").status_code == 404


def test_events_replay_and_terminate(client, done_case):
    with client.stream("GET", f"/api/cases/{done_case['id']}/events") as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert events[-1]["type"] == "status" and events[-1]["status"] == "done"
    assert any(e.get("type") == "complete" for e in events)


def test_validation_errors(client):
    assert client.post("/api/cases/demo", json={"tracer": "xyz"}).status_code == 422
    assert client.post("/api/cases/demo", json={"options": {"registration": "magic"}}).status_code == 422
    assert client.get("/api/cases/doesnotexist").status_code == 404


def test_upload_hospital_dicom(client, phantom, tmp_path):
    """Two zips of DICOM from 'separate scanners' (PET in Bq/ml) through the upload endpoint."""
    import zipfile

    from fusionmap.export.dicom import write_acquisition_dicom

    write_acquisition_dicom(phantom.mri, phantom.pet, tmp_path / "acq", patient_id="UP-1")
    zips = {}
    for name in ("MRI", "PET"):
        z = tmp_path / f"{name.lower()}.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for f in (tmp_path / "acq" / name).glob("*.dcm"):
                zf.write(f, f.name)
        zips[name] = z
    with zips["MRI"].open("rb") as m, zips["PET"].open("rb") as p:
        r = client.post("/api/cases/upload", files={"mri": ("mri.zip", m), "pet": ("pet.zip", p)},
                        data={"options": json.dumps({"registration": "rigid", "enhancement": "none",
                                                     "working_spacing_mm": 2.0})})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    for _ in range(600):
        c = client.get(f"/api/cases/{cid}").json()
        if c["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert c["status"] == "done", c.get("error")
    rep = c["report"]
    assert rep["inputs"]["pet"]["meta"]["units"] == "SUVbw"
    assert rep["inputs"]["mri"]["meta"]["patient_id"] == "UP-1"
    assert rep["registration"]["nmi_after"] > rep["registration"]["nmi_before"]
    assert "validation" not in rep  # real-patient path: no ground truth
    assert len(rep["analysis"]["hotspots"]) >= 1
