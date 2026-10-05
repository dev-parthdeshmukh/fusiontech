"""Training code smoke tests (skipped when PyTorch is not installed)."""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from fusionmap.enhancement import ai  # noqa: E402
from fusionmap.registration import learned  # noqa: E402
from training.losses import diffusion_regulariser, gradient_l1, mutual_information  # noqa: E402
from training.nets import HybridViTUNet, SpatialTransformer, VecInt, VoxelMorph  # noqa: E402


def test_vit_unet_any_multiple_of_16():
    net = HybridViTUNet(in_ch=ai.IN_CHANNELS, base=8, vit_dim=32, vit_depth=1, heads=2)
    for h, w in ((64, 64), (96, 128)):
        y = net(torch.rand(2, ai.IN_CHANNELS, h, w))
        assert y.shape == (2, 1, h, w) and float(y.min()) >= 0


def test_vit_unet_starts_as_identity():
    net = HybridViTUNet(in_ch=ai.IN_CHANNELS, base=8, vit_dim=32, vit_depth=1, heads=2)
    x = torch.rand(1, ai.IN_CHANNELS, 32, 32)
    assert torch.allclose(net(x), x[:, ai.CONTEXT : ai.CONTEXT + 1])  # zero-initialised residual head


def test_spatial_transformer_shift():
    st = SpatialTransformer((8, 8, 8))
    src = torch.zeros(1, 1, 8, 8, 8)
    src[0, 0, :, :, 4] = 1.0
    flow = torch.zeros(1, 3, 8, 8, 8)
    flow[:, 2] = 1.0  # sample one voxel to the +x side
    out = st(src, flow)
    assert torch.allclose(out[0, 0, :, :, 3], torch.ones(8, 8))


def test_vecint_matches_numpy():
    v = torch.zeros(1, 3, 6, 7, 8)
    v[:, 0] = 0.3
    v[:, 1, :, 3:, :] = -0.2
    t = VecInt((6, 7, 8), steps=7)(v)[0].numpy()
    n = learned.integrate_velocity(v[0].numpy())
    assert np.allclose(t, n, atol=1e-3)


def test_voxelmorph_shapes():
    net = VoxelMorph(size=learned.NET_SIZE_ZYX)
    x = torch.rand(1, 2, *learned.NET_SIZE_ZYX)
    warped, disp, vel = net(x)
    assert warped.shape == (1, 1, *learned.NET_SIZE_ZYX)
    assert disp.shape == (1, 3, *learned.NET_SIZE_ZYX)
    assert vel.shape == (1, 3, *(s // 2 for s in learned.NET_SIZE_ZYX))


def test_losses():
    a = torch.rand(1, 1, 16, 16, 16)
    assert mutual_information(a, a) > mutual_information(a, torch.rand_like(a))
    assert diffusion_regulariser(torch.zeros(1, 3, 4, 4, 4)) == 0
    x = torch.rand(1, 1, 8, 8)
    assert gradient_l1(x, x) == 0


def test_cyclegan_two_steps(tmp_path):
    from training import train_cyclegan

    # tiny synthetic "volumes" in the enhancer data format
    rng = np.random.default_rng(0)
    for i in range(2):
        shape = (12, 64, 64)
        np.savez_compressed(tmp_path / f"enh_{i:04d}.npz", pet=rng.random(shape).astype(np.float16),
                            mri=rng.random(shape).astype(np.float16), truth=rng.random(shape).astype(np.float16),
                            head=np.ones(shape, np.uint8), lesions=np.zeros(shape, np.uint8), tracer="fdg", fwhm=6.0)
    res = train_cyclegan.main(["--data", str(tmp_path), "--iters", "2", "--batch", "1", "--crop", "48",
                               "--threads", "1", "--out", str(tmp_path / "g.onnx")])
    assert np.isfinite(res["loss_g"]) and (tmp_path / "g.onnx").exists()
