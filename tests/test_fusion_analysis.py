import numpy as np

from fusionmap import imaging as im
from fusionmap import metrics as mt
from fusionmap.analysis import find_hotspots
from fusionmap.fusion import COLORMAPS, FusionSettings, all_luts, checkerboard, fuse, lut


def test_luts():
    for name in COLORMAPS:
        t = lut(name)
        assert t.shape == (256, 3) and t.dtype == np.uint8
    assert lut("gray")[255].tolist() == [255, 255, 255]
    assert set(all_luts()) == set(COLORMAPS)


def test_fuse_shapes_and_threshold():
    mri = np.linspace(0, 100, 64, dtype=np.float32).reshape(4, 4, 4)
    pet = np.zeros_like(mri)
    pet[2, 2, 2] = 4.0  # mid-range uptake (the top of the "hot" table is white)
    rgb = fuse(mri, pet, FusionSettings(pet_range=(1.0, 10.0), mri_window=(0, 100)))
    assert rgb.shape == (4, 4, 4, 3) and rgb.dtype == np.uint8
    # below threshold: pure greyscale
    assert rgb[0, 0, 1, 0] == rgb[0, 0, 1, 1] == rgb[0, 0, 1, 2]
    # hot voxel is coloured (red channel dominates for the 'hot' table)
    r, g, b = rgb[2, 2, 2].astype(int)
    assert r > b


def test_checkerboard():
    a, b = np.zeros((32, 32)), np.ones((32, 32))
    c = checkerboard(a, b, tile=8)
    assert c[0, 0] == 1 and c[0, 8] == 0 and c[8, 8] == 1


def test_hotspots_find_pet_positive_and_ignore_radionecrosis(phantom, pet_aligned, head):
    spots, labels, bg = find_hotspots(pet_aligned, head)
    truth_labels = im.arr(phantom.lesion_mask).astype(np.uint8)
    det = mt.detection([s.to_dict() for s in spots], labels, truth_labels, phantom.lesions,
                       float(np.mean(phantom.mri.GetSpacing())))
    assert det["detected"] == det["pet_positive_lesions"] == 2
    assert det["false_positives"] == 0
    cold = next(les for les in phantom.lesions if les.kind == "mri_only")
    assert not np.any(labels[truth_labels == cold.id])
    for s in spots:
        assert s.suv_max >= s.suv_peak >= 0 and s.tbr_max >= 1.6 and s.mtv_ml > 0
        assert s.side in ("left", "right", "midline")
