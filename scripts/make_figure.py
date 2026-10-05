"""Build docs/screenshots/enhancement_grid.png from a finished `fusionmap demo` run.

    fusionmap demo --seed 2026 --out var/demo_2026
    python scripts/make_figure.py var/demo_2026 2026
"""

import json
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from PIL import Image, ImageDraw, ImageFont

from fusionmap import imaging as im
from fusionmap.fusion import lut
from fusionmap.phantom import PhantomConfig, make_phantom


def main(run: Path, seed: int, out: Path = Path("docs/screenshots/enhancement_grid.png")):
    mri_img = sitk.ReadImage(str(run / "work/mri.nii.gz"))
    mri = im.arr(mri_img)
    reg = im.arr(sitk.ReadImage(str(run / "work/pet_registered.nii.gz")))
    enh = im.arr(sitk.ReadImage(str(run / "work/pet_enhanced.nii.gz")))
    ph = make_phantom(PhantomConfig(seed=seed, lesion_mix="showcase", n_lesions=3))
    truth = im.arr(im.resample(ph.pet_truth, mri_img))
    lesions = json.loads((run / "report.json").read_text())["validation"]["phantom"]["lesions"]
    hi = float(np.percentile(truth, 99.95))
    table = lut("inferno")

    def gray(a):
        g = np.clip(a / np.percentile(mri, 99.5) * 255, 0, 255).astype(np.uint8)
        return np.stack([g] * 3, -1)

    def pet(a):
        return table[np.clip(a / hi * 255, 0, 255).astype(np.uint8)]

    picks = [les for les in lesions if les["kind"] in ("active", "pet_only")]
    rows = []
    for les in picks:
        k = im.mm_to_index(mri_img, les["center_mm"])[0]
        rows.append([gray(mri[k]), pet(reg[k]), pet(enh[k]), pet(truth[k])])
    labels = ["MRI (T1 + contrast)", "PET as acquired (aligned)", "FusionMap AI", "Ground truth"]
    s, pad, top = 2, 8, 34
    h, w = rows[0][0].shape[:2]
    canvas = Image.new("RGB", (4 * w * s + 5 * pad, len(rows) * (h * s + pad) + top + pad), (10, 14, 20))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for c, lab in enumerate(labels):
        draw.text((pad + c * (w * s + pad) + 6, 8), lab, fill=(125, 211, 252) if c == 2 else (255, 255, 255), font=font)
    for r, row in enumerate(rows):
        for c, tile in enumerate(row):
            canvas.paste(Image.fromarray(tile).resize((w * s, h * s), Image.BICUBIC),
                         (pad + c * (w * s + pad), top + r * (h * s + pad)))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, optimize=True)
    print(out, canvas.size)


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[2]))
