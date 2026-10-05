import numpy as np
import SimpleITK as sitk

from fusionmap import imaging as im
from fusionmap.phantom import Phantom, PhantomConfig, make_phantom

from .conftest import lesion_of


def test_geometry_and_types(phantom):
    assert phantom.mri.GetSpacing() == (2.0, 2.0, 2.0)
    assert phantom.pet.GetSpacing() == (2.5, 2.5, 2.5)
    assert phantom.pet_truth.GetSize() == phantom.mri.GetSize()
    assert im.arr(phantom.pet).min() >= 0
    assert [les.kind for les in phantom.lesions] == ["active", "mri_only", "pet_only"]


def test_deterministic():
    a = make_phantom(PhantomConfig(seed=11, mri_spacing=2.0, n_lesions=1))
    b = make_phantom(PhantomConfig(seed=11, mri_spacing=2.0, n_lesions=1))
    assert np.array_equal(im.arr(a.pet), im.arr(b.pet))
    assert np.array_equal(im.arr(a.mri), im.arr(b.mri))


def test_ground_truth_inverse_matches_itk(phantom):
    rigid = sitk.AffineTransform(3)
    rigid.SetMatrix(phantom.rigid_matrix.ravel().tolist())
    rigid.SetTranslation(phantom.rigid_offset.tolist())
    disp = sitk.GetImageFromArray(phantom.nonrigid_field, isVector=True)
    disp.CopyInformation(phantom.mri)
    inv = sitk.InvertDisplacementField(disp, maximumNumberOfIterations=30, maxErrorToleranceThreshold=0.01,
                                       meanErrorToleranceThreshold=0.001, enforceBoundaryCondition=True)
    tgt = sitk.CompositeTransform([rigid.GetInverse(), sitk.DisplacementFieldTransform(inv)])
    pts = phantom.eval_points[:150]
    ours = phantom.true_pet_points(pts)
    itk = np.array([tgt.TransformPoint(tuple(p)) for p in pts])
    assert np.abs(ours - itk).max() < 0.05
    assert phantom.tre(tgt)["mean_mm"] < 0.05


def test_naive_overlay_is_misaligned(phantom):
    tre = phantom.tre(None)
    assert 3.0 < tre["mean_mm"] < 30.0


def test_lesion_kinds_have_expected_contrast(phantom):
    truth = im.arr(phantom.pet_truth)
    labels = im.arr(phantom.lesion_mask)
    mri = im.arr(phantom.mri)
    brain = im.arr(phantom.brain_mask) > 0
    bg = np.percentile(truth[brain], 75)
    cold = lesion_of(phantom, "mri_only")
    hot = lesion_of(phantom, "pet_only")
    assert truth[labels == cold.id].mean() < bg  # radionecrosis is PET-cold
    assert truth[labels == hot.id].max() > 1.6 * bg  # MRI-occult tumour is PET-hot
    # MRI-occult: T1 inside the lesion is close to the surrounding tissue
    occ = labels == hot.id
    ring = np.zeros_like(occ)
    from scipy import ndimage as ndi

    ring = ndi.binary_dilation(occ, iterations=3) & ~occ & brain
    assert abs(mri[occ].mean() - mri[ring].mean()) / mri[ring].mean() < 0.25


def test_save_load_roundtrip(phantom, tmp_path):
    phantom.save(tmp_path / "ph")
    back = Phantom.load(tmp_path / "ph")
    assert back.lesions == phantom.lesions
    assert np.allclose(back.true_pet_points(phantom.eval_points[:20]), phantom.true_pet_points(phantom.eval_points[:20]),
                       atol=1e-3)
