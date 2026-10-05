"""Conditional CycleGAN for *unpaired* PET domain translation (blurry clinical PET <-> sharp PET).

Paired training (``train_enhancer.py``) needs the ideal PET for every input — available for
phantoms, not for patients.  When a hospital has only unpaired data (routine PET from its own
scanner plus high-resolution PET from elsewhere), CycleGAN learns the mapping from the two
unpaired sets using cycle consistency:  F(G(a)) ≈ a  and  G(F(b)) ≈ b.

Both generators are conditioned on the co-registered MRI (an extra input channel), the same
idea Plasma CycleGAN uses to condition MRI->PET translation on side information.

    python -m training.train_cyclegan --data training/data/enhancer --iters 2000
"""

from __future__ import annotations

import argparse
import itertools
import time
from pathlib import Path

import numpy as np
import torch

from fusionmap.enhancement import ai
from training.losses import lsgan
from training.nets import HybridViTUNet, PatchDiscriminator, count_parameters
from training.train_enhancer import Volume
from training.train_voxelmorph import export_onnx

ROOT = Path(__file__).resolve().parent.parent


def unpaired_batch(vols, rng, n, crop):
    """Domain A: acquired PET (+MRI) from some patients; domain B: sharp PET (+MRI) from others."""
    a, b = [], []
    half = max(len(vols) // 2, 1)
    for _ in range(n):
        va = vols[rng.integers(0, half)]
        vb = vols[rng.integers(half, len(vols))] if len(vols) > 1 else va
        xa, _, _, _ = va.sample(rng, crop)
        xb, tb, _, _ = vb.sample(rng, crop)
        mri_a = xa[ai.CONTEXT + 2 * ai.CONTEXT + 1 : ai.CONTEXT + 2 * ai.CONTEXT + 2]
        mri_b = xb[ai.CONTEXT + 2 * ai.CONTEXT + 1 : ai.CONTEXT + 2 * ai.CONTEXT + 2]
        a.append(np.concatenate([xa[ai.CONTEXT : ai.CONTEXT + 1], mri_a], 0))
        b.append(np.concatenate([tb, mri_b], 0))
    return torch.from_numpy(np.stack(a)), torch.from_numpy(np.stack(b))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=ROOT / "training/data/enhancer")
    ap.add_argument("--iters", type=int, default=2000)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--crop", type=int, default=96)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lambda-cycle", type=float, default=10.0)
    ap.add_argument("--lambda-id", type=float, default=5.0)
    ap.add_argument("--max-volumes", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "training/runs/cyclegan_G.onnx")
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args(argv)
    torch.set_num_threads(a.threads)
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    files = sorted(a.data.glob("enh_*.npz"))
    if a.max_volumes:
        files = files[: a.max_volumes]
    vols = [Volume(f) for f in files]
    # generators: (PET, MRI) -> PET of the other domain; residual on the PET channel (context=0)
    G = HybridViTUNet(in_ch=2, base=16, vit_dim=96, vit_depth=2, heads=4, context=0)  # blurry -> sharp
    F_ = HybridViTUNet(in_ch=2, base=16, vit_dim=96, vit_depth=2, heads=4, context=0)  # sharp -> blurry
    DA, DB = PatchDiscriminator(1, 32), PatchDiscriminator(1, 32)
    print(f"G/F params {count_parameters(G):,} · D params {count_parameters(DA):,}", flush=True)
    opt_g = torch.optim.Adam(itertools.chain(G.parameters(), F_.parameters()), lr=a.lr, betas=(0.5, 0.999))
    opt_d = torch.optim.Adam(itertools.chain(DA.parameters(), DB.parameters()), lr=a.lr, betas=(0.5, 0.999))
    t0 = time.time()
    for it in range(1, a.iters + 1):
        xa, xb = unpaired_batch(vols, rng, a.batch, a.crop)
        mri_a, mri_b = xa[:, 1:2], xb[:, 1:2]
        fake_b = G(xa)
        fake_a = F_(xb)
        rec_a = F_(torch.cat([fake_b, mri_a], 1))
        rec_b = G(torch.cat([fake_a, mri_b], 1))
        id_b = G(xb)
        id_a = F_(xa)
        loss_g = (lsgan(DB(fake_b), True) + lsgan(DA(fake_a), True)
                  + a.lambda_cycle * ((rec_a - xa[:, :1]).abs().mean() + (rec_b - xb[:, :1]).abs().mean())
                  + a.lambda_id * ((id_b - xb[:, :1]).abs().mean() + (id_a - xa[:, :1]).abs().mean()))
        opt_g.zero_grad()
        loss_g.backward()
        opt_g.step()
        loss_d = 0.5 * (lsgan(DB(xb[:, :1]), True) + lsgan(DB(fake_b.detach()), False)
                        + lsgan(DA(xa[:, :1]), True) + lsgan(DA(fake_a.detach()), False))
        opt_d.zero_grad()
        loss_d.backward()
        opt_d.step()
        if it % 25 == 0 or it == a.iters:
            print(f"it {it:5d}  G {loss_g.item():.4f}  D {loss_d.item():.4f}  {time.time() - t0:.0f}s", flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    export_onnx(G.eval(), torch.zeros(1, 2, 96, 96), a.out, dynamic=True, output="y")
    return {"loss_g": float(loss_g.item()), "loss_d": float(loss_d.item())}


if __name__ == "__main__":
    main()
