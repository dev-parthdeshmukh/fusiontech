"""Network architectures (PyTorch). Inference ships as ONNX — torch is a training-only dependency.

* :class:`HybridViTUNet` — 2.5-D MRI-guided PET enhancer: convolutional U-Net encoder/decoder
  with a Vision-Transformer bottleneck (TransUNet-style) using convolutional positional
  encoding, so it runs on any slice size that is a multiple of 16.
* :class:`VoxelMorph` — 3-D U-Net predicting a stationary velocity field at half resolution,
  integrated by scaling and squaring into a diffeomorphic displacement (VoxelMorph-diff).
* :class:`PatchDiscriminator` — 70x70-style PatchGAN used by the CycleGAN trainer.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

# ----------------------------------------------------------------------------------------
# hybrid CNN / ViT U-Net (2-D, multi-channel 2.5-D input)
# ----------------------------------------------------------------------------------------


class ConvBlock(nn.Module):
    def __init__(self, cin: int, cout: int):
        super().__init__()
        self.c1 = nn.Conv2d(cin, cout, 3, padding=1)
        self.n1 = nn.GroupNorm(8, cout)
        self.c2 = nn.Conv2d(cout, cout, 3, padding=1)
        self.n2 = nn.GroupNorm(8, cout)
        self.skip = nn.Conv2d(cin, cout, 1) if cin != cout else nn.Identity()

    def forward(self, x):
        h = F.gelu(self.n1(self.c1(x)))
        h = self.n2(self.c2(h))
        return F.gelu(h + self.skip(x))


class Attention(nn.Module):
    def __init__(self, dim: int, heads: int):
        super().__init__()
        self.heads = heads
        self.qkv = nn.Linear(dim, dim * 3)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x):  # [B, N, C]
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.heads, C // self.heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        attn = (q @ k.transpose(-2, -1)) * (C // self.heads) ** -0.5
        attn = attn.softmax(-1)
        out = (attn @ v).transpose(1, 2).reshape(B, N, C)
        return self.proj(out)


class TransformerBlock(nn.Module):
    def __init__(self, dim: int, heads: int, mlp_ratio: float = 3.0):
        super().__init__()
        self.n1 = nn.LayerNorm(dim)
        self.attn = Attention(dim, heads)
        self.n2 = nn.LayerNorm(dim)
        hidden = int(dim * mlp_ratio)
        self.mlp = nn.Sequential(nn.Linear(dim, hidden), nn.GELU(), nn.Linear(hidden, dim))

    def forward(self, x):
        x = x + self.attn(self.n1(x))
        return x + self.mlp(self.n2(x))


class ViTBottleneck(nn.Module):
    """Tokens = feature-map pixels; positional information from a depthwise conv (CPE)."""

    def __init__(self, dim: int, depth: int, heads: int):
        super().__init__()
        self.pos = nn.Conv2d(dim, dim, 3, padding=1, groups=dim)
        self.blocks = nn.ModuleList([TransformerBlock(dim, heads) for _ in range(depth)])
        self.norm = nn.LayerNorm(dim)

    def forward(self, x):  # [B, C, H, W]
        B, C, H, W = x.shape
        x = x + self.pos(x)
        t = x.flatten(2).transpose(1, 2)
        for blk in self.blocks:
            t = blk(t)
        t = self.norm(t)
        return t.transpose(1, 2).reshape(B, C, H, W)


class HybridViTUNet(nn.Module):
    def __init__(self, in_ch: int = 6, base: int = 32, vit_dim: int = 192, vit_depth: int = 4, heads: int = 6,
                 context: int = 1):
        super().__init__()
        self.context = context
        b = base
        self.e1 = ConvBlock(in_ch, b)
        self.d1 = nn.Conv2d(b, b * 2, 3, stride=2, padding=1)
        self.e2 = ConvBlock(b * 2, b * 2)
        self.d2 = nn.Conv2d(b * 2, b * 4, 3, stride=2, padding=1)
        self.e3 = ConvBlock(b * 4, b * 4)
        self.d3 = nn.Conv2d(b * 4, vit_dim, 3, stride=2, padding=1)
        self.e4 = ConvBlock(vit_dim, vit_dim)
        self.d4 = nn.Conv2d(vit_dim, vit_dim, 3, stride=2, padding=1)
        self.vit = ViTBottleneck(vit_dim, vit_depth, heads)
        self.u4 = nn.ConvTranspose2d(vit_dim, vit_dim, 2, stride=2)
        self.m4 = ConvBlock(vit_dim * 2, vit_dim)
        self.u3 = nn.ConvTranspose2d(vit_dim, b * 4, 2, stride=2)
        self.m3 = ConvBlock(b * 8, b * 4)
        self.u2 = nn.ConvTranspose2d(b * 4, b * 2, 2, stride=2)
        self.m2 = ConvBlock(b * 4, b * 2)
        self.u1 = nn.ConvTranspose2d(b * 2, b, 2, stride=2)
        self.m1 = ConvBlock(b * 2, b)
        self.head = nn.Conv2d(b, 1, 1)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, x):
        pet_center = x[:, self.context : self.context + 1]
        e1 = self.e1(x)
        e2 = self.e2(self.d1(e1))
        e3 = self.e3(self.d2(e2))
        e4 = self.e4(self.d3(e3))
        z = self.vit(self.d4(e4))
        y = self.m4(torch.cat([self.u4(z), e4], 1))
        y = self.m3(torch.cat([self.u3(y), e3], 1))
        y = self.m2(torch.cat([self.u2(y), e2], 1))
        y = self.m1(torch.cat([self.u1(y), e1], 1))
        return F.relu(pet_center + self.head(y))  # residual learning, SUV >= 0


# ----------------------------------------------------------------------------------------
# VoxelMorph-diff (3-D)
# ----------------------------------------------------------------------------------------


class SpatialTransformer(nn.Module):
    """Warp ``src`` by a displacement ``flow`` [B, 3, Z, Y, X] in voxels (dz, dy, dx)."""

    def __init__(self, size):
        super().__init__()
        vectors = [torch.arange(0, s, dtype=torch.float32) for s in size]
        grid = torch.stack(torch.meshgrid(vectors, indexing="ij"), 0).unsqueeze(0)
        self.register_buffer("grid", grid, persistent=False)
        self.size = size

    def forward(self, src, flow):
        loc = self.grid + flow
        for i, s in enumerate(self.size):
            loc[:, i] = 2 * (loc[:, i] / (s - 1) - 0.5)
        loc = loc.permute(0, 2, 3, 4, 1)[..., [2, 1, 0]]  # (x, y, z) for grid_sample
        return F.grid_sample(src, loc, align_corners=True, mode="bilinear", padding_mode="border")


class VecInt(nn.Module):
    def __init__(self, size, steps: int = 7):
        super().__init__()
        self.steps = steps
        self.warp = SpatialTransformer(size)

    def forward(self, vel):
        disp = vel / (2**self.steps)
        for _ in range(self.steps):
            disp = disp + self.warp(disp, disp)
        return disp


def _conv3(cin, cout, stride=1):
    return nn.Sequential(nn.Conv3d(cin, cout, 3, stride=stride, padding=1), nn.LeakyReLU(0.2))


def upsample_flow(disp_half, full_size):
    """Half-resolution displacement (voxels) -> full resolution, align_corners geometry."""
    half = disp_half.shape[2:]
    up = F.interpolate(disp_half, size=tuple(full_size), mode="trilinear", align_corners=True)
    scale = torch.tensor([(f - 1) / (h - 1) for f, h in zip(full_size, half)], dtype=up.dtype,
                         device=up.device).view(1, 3, 1, 1, 1)
    return up * scale


class VoxelMorph(nn.Module):
    """U-Net -> stationary velocity at 1/2 resolution -> scaling & squaring -> upsample."""

    def __init__(self, size=(48, 56, 48), enc=(16, 32, 32), dec=(32, 32), final=(32, 16),
                 int_steps: int = 7):
        super().__init__()
        self.size = tuple(size)
        self.half = tuple(s // 2 for s in size)
        self.enc = nn.ModuleList()
        c = 2
        for ch in enc:
            self.enc.append(_conv3(c, ch, stride=2))
            c = ch
        skips = list(enc[:-1][::-1])  # skip connections back up to 1/2 resolution
        self.dec = nn.ModuleList()
        for ch, sk in zip(dec, skips):
            self.dec.append(_conv3(c + sk, ch))
            c = ch
        layers = []
        for f in final:
            layers.append(_conv3(c, f))
            c = f
        self.final = nn.Sequential(*layers)
        self.flow = nn.Conv3d(c, 3, 3, padding=1)
        nn.init.normal_(self.flow.weight, 0, 1e-5)
        nn.init.zeros_(self.flow.bias)
        self.integrate = VecInt(self.half, int_steps)
        self.transformer = SpatialTransformer(self.size)

    def velocity(self, x):
        feats = []
        h = x
        for layer in self.enc:
            h = layer(h)
            feats.append(h)
        feats.pop()  # the deepest level is ``h`` itself
        for layer in self.dec:
            h = F.interpolate(h, scale_factor=2, mode="nearest")
            h = layer(torch.cat([h, feats.pop()], 1))
        return self.flow(self.final(h))  # [B, 3, Z/2, Y/2, X/2], half-res voxels

    def forward(self, x):
        vel = self.velocity(x)
        disp = upsample_flow(self.integrate(vel), self.size)
        warped = self.transformer(x[:, 1:2], disp)
        return warped, disp, vel


class VelocityOnly(nn.Module):
    """Export wrapper: ONNX graph contains only the CNN; integration runs in NumPy."""

    def __init__(self, net: VoxelMorph):
        super().__init__()
        self.net = net

    def forward(self, x):
        return self.net.velocity(x)


# ----------------------------------------------------------------------------------------
# PatchGAN for CycleGAN
# ----------------------------------------------------------------------------------------


class PatchDiscriminator(nn.Module):
    def __init__(self, in_ch: int = 1, base: int = 64, layers: int = 3):
        super().__init__()
        seq = [nn.Conv2d(in_ch, base, 4, 2, 1), nn.LeakyReLU(0.2)]
        c = base
        for i in range(1, layers):
            n = min(base * 2**i, base * 8)
            seq += [nn.Conv2d(c, n, 4, 2, 1), nn.InstanceNorm2d(n), nn.LeakyReLU(0.2)]
            c = n
        seq += [nn.Conv2d(c, c, 4, 1, 1), nn.InstanceNorm2d(c), nn.LeakyReLU(0.2), nn.Conv2d(c, 1, 4, 1, 1)]
        self.model = nn.Sequential(*seq)

    def forward(self, x):
        return self.model(x)


def count_parameters(m: nn.Module) -> int:
    return sum(p.numel() for p in m.parameters() if p.requires_grad)
