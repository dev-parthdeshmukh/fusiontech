"""Loss functions for training."""

from __future__ import annotations

import torch
import torch.nn.functional as F


def mutual_information(a: torch.Tensor, b: torch.Tensor, mask: torch.Tensor | None = None, bins: int = 32,
                       samples: int = 30_000, vmax: float = 1.5) -> torch.Tensor:
    """Differentiable global mutual information with Gaussian Parzen windows (nats)."""
    a = a.reshape(-1)
    b = b.reshape(-1)
    if mask is not None:
        idx = torch.nonzero(mask.reshape(-1), as_tuple=False).squeeze(1)
    else:
        idx = torch.arange(a.numel(), device=a.device)
    if idx.numel() > samples:
        idx = idx[torch.randint(0, idx.numel(), (samples,), device=a.device)]
    va = (a[idx] / vmax).clamp(0, 1)
    vb = (b[idx] / vmax).clamp(0, 1)
    centers = torch.linspace(0, 1, bins, device=a.device)
    sigma = 0.75 / bins
    wa = torch.exp(-((va[:, None] - centers[None]) ** 2) / (2 * sigma**2))
    wb = torch.exp(-((vb[:, None] - centers[None]) ** 2) / (2 * sigma**2))
    wa = wa / (wa.sum(1, keepdim=True) + 1e-8)
    wb = wb / (wb.sum(1, keepdim=True) + 1e-8)
    pab = wa.t() @ wb / va.numel()
    pa = pab.sum(1, keepdim=True)
    pb = pab.sum(0, keepdim=True)
    return (pab * torch.log(pab / (pa @ pb + 1e-10) + 1e-10)).sum()


def diffusion_regulariser(field: torch.Tensor) -> torch.Tensor:
    """Mean squared spatial gradient of a [B, 3, Z, Y, X] field."""
    dz = field[:, :, 1:] - field[:, :, :-1]
    dy = field[:, :, :, 1:] - field[:, :, :, :-1]
    dx = field[:, :, :, :, 1:] - field[:, :, :, :, :-1]
    return (dz.pow(2).mean() + dy.pow(2).mean() + dx.pow(2).mean()) / 3.0


def gradient_l1(pred: torch.Tensor, target: torch.Tensor, weight: torch.Tensor | None = None) -> torch.Tensor:
    """L1 between image gradients — rewards sharp, correctly placed edges (2-D)."""
    def grads(x):
        return x[..., 1:, :] - x[..., :-1, :], x[..., :, 1:] - x[..., :, :-1]

    py, px = grads(pred)
    ty, tx = grads(target)
    ly = (py - ty).abs()
    lx = (px - tx).abs()
    if weight is not None:
        ly = ly * weight[..., 1:, :]
        lx = lx * weight[..., :, 1:]
    return ly.mean() + lx.mean()


def lsgan(pred: torch.Tensor, real: bool) -> torch.Tensor:
    return F.mse_loss(pred, torch.ones_like(pred) if real else torch.zeros_like(pred))
