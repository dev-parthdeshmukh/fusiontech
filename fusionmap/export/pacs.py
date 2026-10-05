"""DICOM networking: push the export bundle to a PACS with C-STORE (pynetdicom)."""

from __future__ import annotations

from pathlib import Path

import pydicom
from pynetdicom import AE
from pynetdicom.sop_class import Verification

STORAGE_CLASSES = {
    "1.2.840.10008.5.1.4.1.1.4": "MR Image Storage",
    "1.2.840.10008.5.1.4.1.1.128": "PET Image Storage",
    "1.2.840.10008.5.1.4.1.1.7": "Secondary Capture Image Storage",
    "1.2.840.10008.5.1.4.1.1.481.3": "RT Structure Set Storage",
}


def echo(host: str, port: int, called_aet: str = "ANY-SCP", calling_aet: str = "FUSIONMAP", timeout: float = 5) -> bool:
    ae = AE(ae_title=calling_aet)
    ae.acse_timeout = timeout
    ae.network_timeout = timeout
    ae.add_requested_context(Verification)
    assoc = ae.associate(host, int(port), ae_title=called_aet)
    if not assoc.is_established:
        return False
    status = assoc.send_c_echo()
    assoc.release()
    return bool(status) and status.Status == 0x0000


def push_folder(folder: Path, host: str, port: int, called_aet: str = "ANY-SCP", calling_aet: str = "FUSIONMAP",
                timeout: float = 10) -> dict:
    files = sorted(p for p in Path(folder).rglob("*.dcm"))
    ae = AE(ae_title=calling_aet)
    ae.acse_timeout = timeout
    ae.network_timeout = timeout
    for uid in STORAGE_CLASSES:
        ae.add_requested_context(uid, "1.2.840.10008.1.2.1")
    assoc = ae.associate(host, int(port), ae_title=called_aet)
    if not assoc.is_established:
        return {"ok": False, "error": f"association with {called_aet}@{host}:{port} failed", "sent": 0,
                "total": len(files)}
    sent, failed = 0, []
    try:
        for f in files:
            ds = pydicom.dcmread(f)
            status = assoc.send_c_store(ds)
            if status and status.Status == 0x0000:
                sent += 1
            else:
                failed.append(f.name)
    finally:
        assoc.release()
    return {"ok": not failed, "sent": sent, "total": len(files), "failed": failed[:20]}
