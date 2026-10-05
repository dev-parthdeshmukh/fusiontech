import numpy as np
import pytest

from fusionmap import imaging as im
from fusionmap.registration import bspline_mi, learned, normalized_mutual_information, rigid_mi


@pytest.fixture(scope="module")
def rigid(phantom, head):
    mask = im.like(head.astype(np.uint8), phantom.mri, np.uint8)
    return rigid_mi(phantom.mri, phantom.pet, fixed_mask=mask)


def test_rigid_mi_recovers_head_pose(phantom, rigid):
    before = phantom.tre(None)["mean_mm"]
    after = phantom.tre(rigid.transform)
    assert after["mean_mm"] < 1.6, after
    assert after["mean_mm"] < before / 4
    assert rigid.metric_trace and rigid.metric_trace[-1] > rigid.metric_trace[0]


def test_registration_increases_nmi(phantom, rigid, head):
    mri = im.arr(phantom.mri)
    naive = im.arr(im.resample(phantom.pet, phantom.mri))
    reg = im.arr(im.resample(phantom.pet, phantom.mri, rigid.transform))
    assert normalized_mutual_information(mri, reg, head) > normalized_mutual_information(mri, naive, head)


def test_bspline_returns_composite(phantom, rigid, head):
    mask = im.like(head.astype(np.uint8), phantom.mri, np.uint8)
    res = bspline_mi(phantom.mri, phantom.pet, rigid.transform, fixed_mask=mask, grid_spacing_mm=100.0)
    assert res.transform.GetName() == "CompositeTransform"
    assert phantom.tre(res.transform)["mean_mm"] < 2.5


def test_velocity_integration_identities():
    z = np.zeros((3, 8, 10, 12), np.float32)
    assert np.allclose(learned.integrate_velocity(z), 0)
    const = np.zeros_like(z)
    const[2] = 0.5  # uniform shift integrates exactly
    assert np.allclose(learned.integrate_velocity(const)[2], 0.5, atol=1e-4)
    up = learned.upsample_displacement(const, (16, 20, 24))
    assert up.shape == (3, 16, 20, 24)
    assert np.allclose(up[2], 0.5 * 23 / 11, atol=1e-4)  # magnitude rescaled to the fine grid
    mm = learned.field_to_mm_xyz(up)
    assert mm.shape == (16, 20, 24, 3) and np.allclose(mm[..., 0], up[2] * learned.NET_SPACING)


@pytest.mark.skipif(not learned.available(), reason="VoxelMorph model not trained")
def test_voxelmorph_refines_without_folding(phantom, rigid, head):
    res = learned.register_voxelmorph(phantom.mri, phantom.pet, rigid.transform, head)
    assert res.params["min_jacobian"] > 0
    assert phantom.tre(res.transform)["mean_mm"] < phantom.tre(rigid.transform)["mean_mm"] + 0.3
