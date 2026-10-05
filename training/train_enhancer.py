"""Train the MRI-guided hybrid ViT/U-Net PET enhancer and export ONNX.

    python -m training.train_enhancer --data training/data/enhancer --iters 4000

Inputs are 2.5-D slabs (PET + MRI, three neighbouring slices each) built with the exact
runtime preprocessing (``fusionmap.enhancement.ai``).  The target is the ideal activity
(no PSF blur, no noise).  The loss up-weights tumour voxels so small-lesion SUVmax — the
quantity clinicians act on — is recovered, and adds a gradient term for crisp edges.
Phantoms include MRI-occult and PET-negative lesions so the network must take *uptake*
from the PET and only *boundaries* from the MRI.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import date
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from fusionmap.enhancement import ai
from training.losses import gradient_l1
from training.nets import HybridViTUNet, count_parameters
from training.train_voxelmorph import export_onnx

ROOT = Path(__file__).resolve().parent.parent


class Volume:
    def __init__(self, path: Path):
        d = np.load(path)
        self.pet = d["pet"].astype(np.float32)
        self.mri = d["mri"].astype(np.float32)
        self.truth = d["truth"].astype(np.float32)
        self.head = d["head"] > 0
        self.lesions = d["lesions"]
        self.tracer = str(d["tracer"])
        ps, ms = ai.normalisation(self.pet, self.mri, self.head)
        self.ps = ps
        self.pet_n = self.pet / ps
        self.mri_n = np.clip(self.mri / ms, 0, 2.0)
        self.truth_n = self.truth / ps
        zs = np.where(self.head.any((1, 2)))[0]
        self.head_slices = zs
        self.lesion_slices = np.where(self.lesions.any((1, 2)))[0]

    def sample(self, rng, crop: int):
        if len(self.lesion_slices) and rng.random() < 0.45:
            k = int(rng.choice(self.lesion_slices))
            ys, xs = np.nonzero(self.lesions[k])
        else:
            k = int(rng.choice(self.head_slices))
            ys, xs = np.nonzero(self.head[k])
        j = rng.integers(len(ys))
        cy, cx = int(ys[j]), int(xs[j])
        H, W = self.head.shape[1:]
        y0 = int(np.clip(cy - crop // 2 + rng.integers(-crop // 4, crop // 4 + 1), 0, max(H - crop, 0)))
        x0 = int(np.clip(cx - crop // 2 + rng.integers(-crop // 4, crop // 4 + 1), 0, max(W - crop, 0)))
        sl = (slice(y0, y0 + crop), slice(x0, x0 + crop))
        x = ai.stack_inputs(self.pet_n, self.mri_n, k)[:, sl[0], sl[1]]
        t = self.truth_n[k][sl][None]
        les = (self.lesions[k][sl] > 0)[None].astype(np.float32)
        head = self.head[k][sl][None].astype(np.float32)
        x, t, les, head = (_pad(a, crop) for a in (x, t, les, head))
        if rng.random() < 0.5:
            x, t, les, head = (a[..., ::-1] for a in (x, t, les, head))
        if rng.random() < 0.3:
            x, t, les, head = (a[..., ::-1, :] for a in (x, t, les, head))
        x = x.copy()
        x[3:] = np.clip(x[3:], 0, None) ** rng.uniform(0.85, 1.15)  # MRI contrast jitter
        return x, t.copy(), les.copy(), head.copy()


def _pad(a, crop):
    h, w = a.shape[-2:]
    if h == crop and w == crop:
        return a
    out = np.zeros(a.shape[:-2] + (crop, crop), a.dtype)
    out[..., :h, :w] = a
    return out


def batch(vols, rng, n, crop):
    xs, ts, ls, hs = zip(*(vols[rng.integers(len(vols))].sample(rng, crop) for _ in range(n)))
    return (torch.from_numpy(np.stack(xs)), torch.from_numpy(np.stack(ts)), torch.from_numpy(np.stack(ls)),
            torch.from_numpy(np.stack(hs)))


def full_volume(net, v: Volume, step: int = 3):
    """Enhance every ``step``-th head slice of a validation volume (whole slices)."""
    zs, ys, xs, (Hp, Wp) = ai.padded_crop(v.head)
    H, W = ys.stop - ys.start, xs.stop - xs.start
    ks = list(range(zs.start, zs.stop, step))
    preds = {}
    with torch.no_grad():
        for b0 in range(0, len(ks), 8):
            kb = ks[b0 : b0 + 8]
            x = np.zeros((len(kb), ai.IN_CHANNELS, Hp, Wp), np.float32)
            for i, k in enumerate(kb):
                x[i, :, :H, :W] = ai.stack_inputs(v.pet_n, v.mri_n, k)[:, ys, xs]
            y = net(torch.from_numpy(x)).numpy()
            for i, k in enumerate(kb):
                preds[k] = y[i, 0, :H, :W]
    return preds, ys, xs


def evaluate(net, vols):
    out = {"psnr_input": [], "psnr_pred": [], "rc_input": [], "rc_pred": []}
    net.eval()
    for v in vols:
        preds, ys, xs = full_volume(net, v)
        ks = sorted(preds)
        tr = np.stack([v.truth_n[k][ys, xs] for k in ks])
        pi = np.stack([v.pet_n[k][ys, xs] for k in ks])
        pp = np.stack([preds[k] for k in ks])
        hm = np.stack([v.head[k][ys, xs] for k in ks])
        peak = float(tr[hm].max())
        for key, est in (("input", pi), ("pred", pp)):
            mse = float(((est - tr)[hm] ** 2).mean())
            out[f"psnr_{key}"].append(10 * math.log10(peak**2 / max(mse, 1e-12)))
        lab = np.stack([v.lesions[k][ys, xs] for k in ks])
        for lid in np.unique(lab[lab > 0]):
            m = lab == lid
            t = float(tr[m].max())
            if t < 1.25 * float(np.percentile(tr[hm], 90)):
                continue  # PET-negative lesion: no SUVmax to recover
            out["rc_input"].append(float(pi[m].max()) / t)
            out["rc_pred"].append(float(pp[m].max()) / t)
    net.train()
    return {k: float(np.mean(v)) if v else None for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=ROOT / "training/data/enhancer")
    ap.add_argument("--iters", type=int, default=4000)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--crop", type=int, default=128)
    ap.add_argument("--lr", type=float, default=4e-4)
    ap.add_argument("--val", type=int, default=3)
    ap.add_argument("--base", type=int, default=24)
    ap.add_argument("--vit-dim", type=int, default=128)
    ap.add_argument("--vit-depth", type=int, default=4)
    ap.add_argument("--heads", type=int, default=4)
    ap.add_argument("--lesion-weight", type=float, default=6.0)
    ap.add_argument("--out", type=Path, default=ROOT / "fusionmap/models/enhancer_vit.onnx")
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    files = sorted(a.data.glob("enh_*.npz"))
    vols = [Volume(f) for f in files]
    train, val = vols[: -a.val], vols[-a.val :]
    print(f"{len(train)} train / {len(val)} val volumes", flush=True)
    net = HybridViTUNet(in_ch=ai.IN_CHANNELS, base=a.base, vit_dim=a.vit_dim, vit_depth=a.vit_depth, heads=a.heads,
                        context=ai.CONTEXT)
    print(f"HybridViTUNet params: {count_parameters(net):,}", flush=True)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    warm = 200
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda i: min(1.0, (i + 1) / warm) * (0.03 + 0.97 * 0.5 * (1 + math.cos(math.pi * i / a.iters))))
    ckpt = ROOT / "training/runs/enhancer_best.pt"
    ckpt.parent.mkdir(parents=True, exist_ok=True)
    best = (-float("inf"), 0)
    hist = []
    t0 = time.time()
    for it in range(1, a.iters + 1):
        x, t, les, head = batch(train, rng, a.batch, a.crop)
        y = net(x)
        w = 0.15 + head + a.lesion_weight * F.max_pool2d(les, 5, 1, 2)
        loss = ((y - t).abs() * w).mean() + 0.5 * gradient_l1(y, t, w)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        opt.step()
        sched.step()
        if it % 50 == 0:
            print(f"it {it:5d}  loss {loss.item():.5f}  lr {sched.get_last_lr()[0]:.2e}  {time.time() - t0:.0f}s",
                  flush=True)
        if it % 500 == 0 or it == a.iters:
            m = evaluate(net, val)
            hist.append({"iter": it, **m})
            print(f"   VAL PSNR {m['psnr_input']:.2f} -> {m['psnr_pred']:.2f} dB | lesion RC "
                  f"{m['rc_input']:.3f} -> {m['rc_pred']:.3f}", flush=True)
            score = m["psnr_pred"] - 10 * abs((m["rc_pred"] or 0) - 1)  # fidelity, and SUVmax error either way
            if score > best[0]:
                best = (score, it)
                torch.save(net.state_dict(), ckpt)
    net.load_state_dict(torch.load(ckpt))
    net.eval()
    m = evaluate(net, val)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    export_onnx(net, torch.zeros(1, ai.IN_CHANNELS, 128, 160), a.out, dynamic=True, output="y")
    card = {
        "name": "FusionMap MRI-guided PET enhancer (hybrid CNN / Vision Transformer U-Net)",
        "architecture": f"U-Net (base {a.base}) with {a.vit_depth}-layer ViT bottleneck (dim {a.vit_dim}, "
                        f"{a.heads} heads, conv positional encoding), residual output",
        "parameters": count_parameters(net),
        "input": {"x": ["N", ai.IN_CHANNELS, "H", "W"], "channels": "PET z-1,z,z+1 | MRI z-1,z,z+1",
                  "norm": "PET / in-head p99.5, MRI / in-head p99", "multiple_of": ai.MULTIPLE},
        "output": {"y": ["N", 1, "H", "W"], "meaning": "sharp PET of the centre slice (same normalisation)"},
        "training": {"volumes": len(train), "iterations": a.iters, "best_iteration": best[1], "batch": a.batch,
                     "crop": a.crop, "loss": f"lesion-weighted L1 (x{a.lesion_weight}) + 0.5 gradient-L1",
                     "date": str(date.today())},
        "validation": {"volumes": len(val), **{k: (round(v, 4) if v is not None else None) for k, v in m.items()},
                       "history": hist},
        "intended_use": "Research prototype. Trained on simulated brain PET/MRI phantoms only.",
    }
    a.out.with_suffix(".json").write_text(json.dumps(card, indent=2))
    print(json.dumps({k: v for k, v in card["validation"].items() if k != "history"}, indent=2))


if __name__ == "__main__":
    main()
