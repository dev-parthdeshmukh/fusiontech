import json

from fusionmap.cli import main


def test_cli_demo_fast_grid(tmp_path, capsys):
    out = tmp_path / "demo"
    assert main(["demo", "--seed", "2", "--spacing", "2", "--registration", "rigid", "--enhancement", "deconv",
                 "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "FusionMap summary" in text and "TRE" in text
    rep = json.loads((out / "report.json").read_text())
    assert rep["validation"]["tre_final"]["mean_mm"] < rep["validation"]["tre_naive"]["mean_mm"]
    assert (out / "exports" / "fusionmap_dicom.zip").exists()


def test_cli_phantom_dicom(tmp_path, capsys):
    out = tmp_path / "ph"
    assert main(["phantom", "--seed", "4", "--out", str(out), "--dicom"]) == 0
    assert any((out / "dicom" / "PET").glob("*.dcm")) and any((out / "dicom" / "MRI").glob("*.dcm"))
    assert (out / "truth" / "truth.json").exists()
