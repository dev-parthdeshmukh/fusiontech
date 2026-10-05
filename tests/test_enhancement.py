import numpy as np
import pytest
import SimpleITK as sitk

from fusionmap import imaging as im
from fusionmap import metrics as mt
from fusionmap.enhancement import ai, enhance_deconv, guided_filter


@pytest.fixture(scope="module")
def truth_and_labels(phantom):
    return im.arr(phantom.pet_truth), im.arr(phantom.lesion_mask).astype(np.uint8)


def test_guided_filter_preserves_constant():
    a = np.full((6, 7, 8), 3.0, np.float32)
    g = np.random.default_rng(0).random((6, 7, 8)).astype(np.float32)
    assert np.allclose(guided_filter(a, g, radius=1, eps=1e-3), 3.0, atol=1e-4)


def test_deconvolution_recovers_lesion_suv(phantom, pet_aligned, head, truth_and_labels):
    truth, labels = truth_and_labels
    out = enhance_deconv(pet_aligned, phantom.mri, head, fwhm_mm=6.0)
    a = im.arr(out)
    assert a.min() >= 0 and a.shape == truth.shape
    before = [r["rc"] for r in mt.lesion_recovery(im.arr(pet_aligned), truth, labels, phantom.lesions)]
    after = [r["rc"] for r in mt.lesion_recovery(a, truth, labels, phantom.lesions)]
    # deconvolution undoes partial-volume loss (raises SUVmax) but, being noise-amplifying, can overshoot —
    # the reason the learned enhancer exists. Assert the reliable part: recovery rises and stays bounded.
    assert np.mean(after) > np.mean(before)
    assert max(after) < 1.6


def test_stack_inputs_contract():
    pet = np.arange(5 * 4 * 4, dtype=np.float32).reshape(5, 4, 4)
    mri = -pet
    x = ai.stack_inputs(pet, mri, 0)
    assert x.shape == (ai.IN_CHANNELS, 4, 4)
    assert np.array_equal(x[0], pet[0]) and np.array_equal(x[1], pet[0]) and np.array_equal(x[2], pet[1])
    assert np.array_equal(x[3 + ai.CONTEXT], mri[0])


@pytest.mark.skipif(not ai.available(), reason="enhancer model not trained")
def test_ai_enhancer_quality_and_no_hallucination(phantom, pet_aligned, head, truth_and_labels):
    truth, labels = truth_and_labels
    ref = im.isotropic_reference(phantom.mri, 1.0)
    # the model is trained at 1 mm: evaluate on the native training resolution
    mri1 = im.resample(phantom.mri, ref, interpolator=sitk.sitkBSpline)
    pet1 = im.resample(pet_aligned, ref)
    head1 = im.foreground_mask(mri1)
    out = im.arr(ai.enhance_ai(pet1, mri1, head1))
    tr1 = im.arr(im.resample(phantom.pet_truth, ref))
    brain = im.arr(sitk.Resample(phantom.brain_mask, ref, sitk.Transform(), sitk.sitkNearestNeighbor, 0)) > 0
    lab1 = im.arr(sitk.Resample(phantom.lesion_mask, ref, sitk.Transform(), sitk.sitkNearestNeighbor, 0)).astype(np.uint8)
    q0 = mt.image_quality(im.arr(pet1), tr1, brain)
    q1 = mt.image_quality(out, tr1, brain)
    assert q1["psnr_db"] > q0["psnr_db"]
    for h in mt.hallucination(out, tr1, lab1, phantom.lesions):
        assert h["ratio"] < 1.3
