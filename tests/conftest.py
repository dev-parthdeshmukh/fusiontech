import numpy as np
import pytest
import SimpleITK as sitk

from fusionmap import imaging as im
from fusionmap.phantom import PhantomConfig, make_phantom


@pytest.fixture(scope="session")
def phantom():
    """A 2 mm showcase phantom (fast): viable, radionecrosis and MRI-occult lesion."""
    return make_phantom(PhantomConfig(seed=5, lesion_mix="showcase", n_lesions=3, mri_spacing=2.0))


@pytest.fixture(scope="session")
def head(phantom):
    return im.foreground_mask(phantom.mri)


@pytest.fixture(scope="session")
def true_tx(phantom):
    from training.make_data import true_transform

    return true_transform(phantom)


@pytest.fixture(scope="session")
def pet_aligned(phantom, true_tx) -> sitk.Image:
    return im.resample(phantom.pet, phantom.mri, true_tx)


def lesion_of(ph, kind):
    return next(les for les in ph.lesions if les.kind == kind)


@pytest.fixture
def rng():
    return np.random.default_rng(0)
