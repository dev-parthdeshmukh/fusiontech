"""Train the VoxelMorph-diff deformable PET->MRI registration network and export ONNX.

    python -m training.train_voxelmorph --data training/data/vxm --iters 3000

Loss = auxiliary end-point-error supervision (available because the training pairs are simulated)
     + lambda_mi * (-mutual information between MRI and warped PET)
     + lambda_reg * diffusion regulariser on the velocity field.
Mutual information keeps the model driven by image evidence (as it must be on real data);
the supervised term speeds up convergence on CPU-scale budgets — VoxelMorph explicitly
supports such auxiliary losses (Balakrishnan et al., 2019).
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

from fusionmap.registration import learned
from training.losses import diffusion_regulariser, mutual_information
from training.nets import VelocityOnly, VoxelMorph, count_parameters

ROOT = Path(__file__).resolve().parent.parent


def load(folder: Path):
    files = sorted(folder.glob("vxm_*.npz"))
    data = []
    for f in files:
        d = np.load(f)
        data.append((d["x"], d["disp"], d["brain"]))
    return files, data


def to_tensor(sample, flip: bool, rng):
    """2 mm sample -> 4 mm network grid (inputs and mask pooled; displacement pooled, in 4 mm voxels)."""
    x, disp, brain = (learned.pool(np.asarray(a, np.float32)) for a in sample)
    disp = disp / learned.NET_POOL
    brain = brain > 0.5
    if flip:  # left-right mirror: flip X axis, negate dx
        x, disp, brain = x[..., ::-1], disp[..., ::-1].copy(), brain[..., ::-1]
        disp[2] *= -1
    x = x.copy()
    if rng is not None:
        x[0] = np.clip(x[0], 0, None) ** rng.uniform(0.85, 1.15)
    return (torch.from_numpy(np.ascontiguousarray(x))[None], torch.from_numpy(np.ascontiguousarray(disp))[None],
            torch.from_numpy(np.ascontiguousarray(brain > 0))[None, None])


def field_error_mm(pred, gt, brain):
    err = ((pred - gt) ** 2).sum(1, keepdim=True).sqrt() * learned.NET_SPACING
    return float(err[brain].mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=ROOT / "training/data/vxm")
    ap.add_argument("--iters", type=int, default=12000)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val", type=int, default=16)
    ap.add_argument("--lambda-mi", type=float, default=0.1)
    ap.add_argument("--lambda-reg", type=float, default=0.05)
    ap.add_argument("--out", type=Path, default=ROOT / "fusionmap/models/voxelmorph.onnx")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--export-only", action="store_true",
                    help="skip training: validate and export training/runs/voxelmorph_best.pt")
    ap.add_argument("--note", default="", help="free-text note stored in the model card")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    torch.manual_seed(0)
    rng = np.random.default_rng(0)

    files, data = load(a.data)
    train, val = data[: -a.val], data[-a.val :]
    print(f"{len(train)} train / {len(val)} val pairs", flush=True)
    size = tuple(int(s) for s in learned.NET_SIZE_ZYX)
    net = VoxelMorph(size=size)
    print(f"VoxelMorph params: {count_parameters(net):,}", flush=True)
    opt = torch.optim.Adam(net.parameters(), lr=a.lr)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda i: 0.05 + 0.95 * 0.5 * (1 + math.cos(math.pi * i / a.iters)))

    def validate():
        net.eval()
        errs, base = [], []
        with torch.no_grad():
            for s in val:
                x, gt, brain = to_tensor(s, False, None)
                _, d, _ = net(x)
                errs.append(field_error_mm(d, gt, brain))
                base.append(field_error_mm(torch.zeros_like(gt), gt, brain))
        net.train()
        return float(np.mean(errs)), float(np.mean(base))

    best = (float("inf"), 0)
    ckpt = ROOT / "training/runs/voxelmorph_best.pt"
    ckpt.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    hist = []
    for it in range(1, 0 if a.export_only else a.iters + 1):
        x, gt, brain = to_tensor(train[rng.integers(len(train))], bool(rng.random() < 0.5), rng)
        warped, disp, vel = net(x)
        err = ((disp - gt) ** 2).sum(1, keepdim=True)[brain] * learned.NET_SPACING**2
        l_field = torch.sqrt(err + 1e-6).mean()  # end-point error (mm): constant-magnitude gradients
        head = x[:, 0:1] > 0.05
        l_mi = -mutual_information(x[:, 0:1], warped, head)
        l_reg = diffusion_regulariser(vel)
        loss = l_field + a.lambda_mi * l_mi + a.lambda_reg * l_reg
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        opt.step()
        sched.step()
        if it % 200 == 0:
            print(f"it {it:5d}  loss {loss.item():.4f}  EPE {l_field.item():.3f}mm  MI {-l_mi.item():.4f}  "
                  f"reg {l_reg.item():.5f}  {time.time() - t0:.0f}s", flush=True)
        if it % 1000 == 0 or it == a.iters:
            err, base = validate()
            hist.append({"iter": it, "val_field_error_mm": err, "val_rigid_only_mm": base})
            print(f"   VAL residual field error: rigid-only {base:.3f} mm -> VoxelMorph {err:.3f} mm", flush=True)
            if err < best[0]:
                best = (err, it)
                torch.save(net.state_dict(), ckpt)

    net.load_state_dict(torch.load(ckpt))
    net.eval()
    err, base = validate()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    export_onnx(VelocityOnly(net), torch.zeros(1, 2, *size), a.out, dynamic=False, output="vel")
    card = {
        "name": "FusionMap VoxelMorph-diff (PET->MRI)",
        "architecture": "3-D U-Net on a 4 mm grid, enc (16,32,32) / dec (32,32) / final (32,16); stationary "
                        "velocity at 1/2 resolution (8 mm), 7-step scaling & squaring",
        "parameters": count_parameters(net),
        "input": {"x": [1, 2, *size], "channels": ["MRI (fixed)", "rigidly aligned PET (moving)"],
                  "grid": f"{learned.NET_SPACING} mm canonical grid centred on the head (2 mm sampling, 2x pooled)",
                  "norm": "in-head p99"},
        "output": {"vel": [1, 3, *(s // 2 for s in size)], "units": "half-resolution voxels (dz, dy, dx)"},
        "training": {"pairs": len(train), "iterations": a.iters,
                     "best_iteration": "best checkpoint (export-only)" if a.export_only else best[1],
                     "loss": f"end-point error + {a.lambda_mi}*(-MI) + {a.lambda_reg}*diffusion", "date": str(date.today())},
        "validation": {"pairs": len(val), "residual_error_rigid_only_mm": round(base, 4),
                       "residual_error_voxelmorph_mm": round(err, 4), "history": hist},
        "intended_use": "Research prototype. Trained on simulated brain PET/MRI phantoms only.",
        "note": a.note,
    }
    a.out.with_suffix(".json").write_text(json.dumps(card, indent=2))
    print(json.dumps(card["validation"] | {"history": None}, indent=2))


def export_onnx(model, example, path: Path, dynamic: bool, output: str):
    model.eval()
    kwargs = dict(input_names=["x"], output_names=[output], opset_version=17)
    if dynamic:
        kwargs["dynamic_axes"] = {"x": {0: "n", 2: "h", 3: "w"}, output: {0: "n", 2: "h", 3: "w"}}
    try:
        torch.onnx.export(model, (example,), str(path), dynamo=False, **kwargs)
    except TypeError:
        torch.onnx.export(model, (example,), str(path), **kwargs)
    print(f"exported {path} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()
