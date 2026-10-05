"""Render the pitch deck's motion graphics and stills from a real FusionMap case.

    python presentation/make_assets.py var/showcase/cases/<case_id>

Every frame comes from the pipeline's own outputs: the registration GIF interpolates the
transform FusionMap actually estimated and its counter is the true tumour position error
(computed against the phantom ground truth) at each step.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage as ndi

from fusionmap import imaging as im
from fusionmap.fusion import FusionSettings, fuse, lut
from fusionmap.phantom import Phantom

OUT = Path(__file__).resolve().parent / "assets"
BG = (10, 14, 20)
PANEL = (17, 24, 33)
CYAN = (125, 211, 252)
ORANGE = (255, 122, 61)
GREEN = (61, 220, 106)
RED = (255, 107, 107)
WHITE = (255, 255, 255)
GREY = (195, 201, 212)
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def font(size, bold=True):
    return ImageFont.truetype(FONT_B if bold else FONT_R, size)


def ease(t):
    return 0.5 - 0.5 * math.cos(math.pi * min(max(t, 0.0), 1.0))


def save_gif(frames, path, ms=70, holds=None):
    """Adaptive-palette GIF; ``holds`` maps frame index -> extra duration (ms)."""
    pal = [f.convert("RGB").quantize(colors=255, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
           for f in frames]
    durs = [ms + (holds or {}).get(i, 0) for i in range(len(frames))]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=durs, loop=0, optimize=True, disposal=2)
    print(f"{path.name}: {len(frames)} frames, {path.stat().st_size / 1e6:.2f} MB")


def outline(mask2d):
    er = ndi.binary_erosion(mask2d, iterations=1)
    return mask2d & ~er


class Case:
    def __init__(self, folder: Path):
        self.folder = folder
        self.rep = json.loads((folder / "report.json").read_text())
        self.manifest = json.loads((folder / "viewer" / "manifest.json").read_text())
        self.mri_img = sitk.ReadImage(str(folder / "work" / "mri.nii.gz"))
        self.mri = im.arr(self.mri_img)
        self.pet_raw = im.to_float(sitk.ReadImage(str(folder / "inputs" / "pet.nii.gz")))
        self.pet_reg = im.arr(sitk.ReadImage(str(folder / "work" / "pet_registered.nii.gz")))
        self.pet_enh = im.arr(sitk.ReadImage(str(folder / "work" / "pet_enhanced.nii.gz")))
        self.ph = Phantom.load(folder / "truth")
        self.labels = im.arr(sitk.Resample(self.ph.lesion_mask, self.mri_img, sitk.Transform(),
                                           sitk.sitkNearestNeighbor, 0)).astype(np.uint8)
        self.truth = im.arr(im.resample(self.ph.pet_truth, self.mri_img))
        v = self.manifest["volumes"]["mri"]
        self.mwin = (v["lo"], v["hi"])
        d = self.rep["analysis"]["display"]
        self.prange = (d["pet_threshold"], d["pet_max"])
        r = self.rep["registration"]["rigid"]
        self.center = r["center_mm"]
        self.angles = np.deg2rad(r["rotation_deg"])
        self.trans = np.array(r["translation_mm"])
        self.lesion = self.ph.lesions[0]
        self.k = im.mm_to_index(self.mri_img, self.lesion.center_mm)[0]
        head = self.mri > self.mwin[0] * 3
        ys, xs = np.where(head.any(0))
        zs = np.where(head.any((1, 2)))[0]
        m = 6
        self.crop = (slice(max(ys.min() - m, 0), ys.max() + m), slice(max(xs.min() - m, 0), xs.max() + m))
        self.zrange = (int(zs.min()), int(zs.max()))

    def rigid(self, t: float) -> sitk.Euler3DTransform:
        tx = sitk.Euler3DTransform()
        tx.SetCenter([float(c) for c in self.center])
        a = self.angles * t
        tx.SetRotation(float(a[0]), float(a[1]), float(a[2]))
        tx.SetTranslation([float(v) for v in self.trans * t])
        return tx

    def pet_slice(self, tx, k):
        ref = im.crop(self.mri_img, (slice(k, k + 1), slice(0, self.mri.shape[1]), slice(0, self.mri.shape[2])))
        return im.arr(im.resample(self.pet_raw, ref, tx))[0]

    def tumour_error(self, tx) -> float:
        return self.ph.tre(tx, np.array([self.lesion.center_mm]))["mean_mm"]

    def fused(self, k, pet2d, opacity=0.85, prange=None):
        return fuse(self.mri[k], pet2d, FusionSettings(colormap="hot", mri_window=self.mwin,
                                                      pet_range=prange or self.prange, opacity=opacity))

    def cropped(self, rgb, scale=2, outline_mask=None, color=GREEN):
        rgb = rgb.copy()
        if outline_mask is not None:
            rgb[outline(outline_mask)] = color
        tile = Image.fromarray(rgb[self.crop])
        return tile.resize((tile.width * scale, tile.height * scale), Image.BICUBIC)


def label(draw, xy, text, size=20, fill=WHITE, bold=True, anchor="la"):
    draw.text(xy, text, font=font(size, bold), fill=fill, anchor=anchor)


def pill(draw, xy, text, fg, bg, size=17):
    f = font(size)
    x, y = xy
    w = draw.textlength(text, font=f)
    draw.rounded_rectangle((x, y, x + w + 24, y + size + 16), radius=(size + 16) // 2, fill=bg)
    draw.text((x + 12, y + 7), text, font=f, fill=fg)


def registration_gif(c: Case):
    k = c.k
    target = c.labels[k] == c.lesion.id
    frames, holds = [], {}
    raw_range = (c.prange[0], float(np.percentile(c.pet_reg[c.pet_reg > 0], 99.98)))  # raw PET is blurrier: own peak
    steps = [0.0] * 1 + [ease(i / 34) for i in range(35)] + [1.0]
    for t in steps:
        tx = c.rigid(t)
        tile = c.cropped(c.fused(k, c.pet_slice(tx, k), prange=raw_range), scale=3, outline_mask=target)
        W, H = tile.size
        canvas = Image.new("RGB", (W, H + 92), (0, 0, 0))
        canvas.paste(tile, (0, 0))
        d = ImageDraw.Draw(canvas)
        err = c.tumour_error(tx)
        col = tuple(int(RED[j] + (GREEN[j] - RED[j]) * min(1.0, t * 1.1)) for j in range(3))
        d.rectangle((0, H, W, H + 92), fill=PANEL)
        label(d, (18, H + 14), "TUMOUR POSITION ERROR", 15, GREY)
        label(d, (18, H + 36), f"{err:4.1f} mm", 38, col)
        tag = "NAIVE OVERLAY" if t < 0.02 else ("FUSIONMAP" if t > 0.98 else "ALIGNING…")
        pill(d, (14, 14), tag, BG, RED if t < 0.02 else (GREEN if t > 0.98 else CYAN))
        label(d, (W - 18, H + 22), "outline = true tumour", 17, GREEN, False, "ra")
        label(d, (W - 18, H + 52), "colour = PET uptake", 17, ORANGE, False, "ra")
        frames.append(canvas)
    holds[0] = 1500
    holds[len(frames) - 1] = 2200
    save_gif(frames, OUT / "registration.gif", ms=60, holds=holds)
    frames[0].save(OUT / "naive_still.png")
    frames[-1].save(OUT / "aligned_still.png")


def pet_tile(c: Case, arr2d, scale=2):
    hi = float(np.percentile(c.truth, 99.95))
    table = lut("inferno")
    rgb = table[np.clip(arr2d / hi * 255, 0, 255).astype(np.uint8)]
    t = Image.fromarray(rgb[c.crop])
    return t.resize((t.width * scale, t.height * scale), Image.BICUBIC)


def sharpening_gif(c: Case):
    k = c.k
    a = pet_tile(c, c.pet_reg[k], scale=3)
    b = pet_tile(c, c.pet_enh[k], scale=3)
    W, H = a.size
    frames, holds = [], {}
    pos = [0.08] + [0.08 + 0.84 * ease(i / 30) for i in range(31)] + [0.92] + \
          [0.92 - 0.84 * ease(i / 30) for i in range(31)]
    for p in pos:
        cut = int(W * p)
        f = Image.new("RGB", (W, H + 56), (0, 0, 0))
        f.paste(b.crop((0, 0, cut, H)), (0, 56))
        f.paste(a.crop((cut, 0, W, H)), (cut, 56))
        d = ImageDraw.Draw(f)
        d.rectangle((0, 0, W, 56), fill=PANEL)
        label(d, (18, 15), "◀ FusionMap AI", 22, CYAN)
        label(d, (W - 18, 15), "PET as acquired ▶", 22, GREY, anchor="ra")
        d.line((cut, 56, cut, H + 56), fill=WHITE, width=3)
        d.ellipse((cut - 15, 56 + H // 2 - 15, cut + 15, 56 + H // 2 + 15), fill=WHITE)
        d.text((cut, 56 + H // 2), "⇆", font=font(18), fill=BG, anchor="mm")
        frames.append(f)
    holds[32] = 1200
    holds[0] = 900
    save_gif(frames, OUT / "sharpening.gif", ms=55, holds=holds)


def sweep_gif(c: Case):
    z0, z1 = c.zrange
    lo = int(z0 + 0.32 * (z1 - z0))
    hi = int(z0 + 0.86 * (z1 - z0))
    ks = list(range(lo, hi, 2))
    ks = ks + ks[::-1][1:-1]
    # open (and pause) on the tumour slice, so the first frame, which is also what static
    # viewers and PDF exports show, tells the story
    start = min(range(len(ks) // 2 + 1), key=lambda i: abs(ks[i] - c.k))
    ks = ks[start:] + ks[:start]
    frames = []
    for k in ks:
        tile = c.cropped(c.fused(k, c.pet_enh[k], opacity=0.9), scale=2)
        frames.append(tile)
    save_gif(frames, OUT / "sweep.gif", ms=70, holds={0: 1200})
    # a hero still at the tumour slice for the cover thumbnail
    c.cropped(c.fused(c.k, c.pet_enh[c.k], opacity=0.9), scale=2).save(OUT / "hero_still.png")


def mip_gif(c: Case):
    sheet = Image.open(c.folder / "viewer" / "mip.png").convert("RGB")
    n = c.manifest["mip"]["frames"]
    fw, fh = c.manifest["mip"]["frame_width"], c.manifest["mip"]["frame_height"]
    sx, _, sz = c.manifest["spacing_xyz"]
    frames = []
    for i in range(n):
        fr = sheet.crop((i * fw, 0, (i + 1) * fw, fh))
        w = fw * 5
        h = int(fh * 5 * (sz / sx))
        frames.append(fr.resize((w, h), Image.BICUBIC))
    save_gif(frames, OUT / "mip.gif", ms=85)


def equation_stills(c: Case):
    k = c.k
    mri = (np.clip((c.mri[k] - c.mwin[0]) / (c.mwin[1] - c.mwin[0]), 0, 1) * 255).astype(np.uint8)
    mri_rgb = np.stack([mri] * 3, -1)
    c.cropped(mri_rgb).save(OUT / "eq_mri.png")
    hot = lut("hot")
    p = np.clip((c.pet_reg[k] - 0) / c.prange[1], 0, 1)
    pet_rgb = hot[(p * 255).astype(np.uint8)]
    c.cropped(pet_rgb).save(OUT / "eq_pet.png")
    c.cropped(c.fused(k, c.pet_enh[k], opacity=0.9)).save(OUT / "eq_fused.png")


def glow(size, center, radius, color, alpha):
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt((xx - center[0]) ** 2 + (yy - center[1]) ** 2) / radius
    a = np.clip(1 - d, 0, 1) ** 2 * alpha
    return a[..., None] * np.array(color, np.float32)[None, None]


def backgrounds():
    W, H = 1920, 1080
    base = np.ones((H, W, 3), np.float32) * np.array(BG, np.float32)
    title = base + glow((W, H), (300, 180), 1100, CYAN, 0.16) + glow((W, H), (1700, 950), 1100, ORANGE, 0.14)
    img = Image.fromarray(np.clip(title, 0, 255).astype(np.uint8))
    # faint fusion rings motif on the right
    rings = Image.new("L", (W * 2, H * 2), 0)
    d = ImageDraw.Draw(rings)
    for cx in (2700, 3060):
        d.ellipse((cx - 620, 1080 - 620, cx + 620, 1080 + 620), outline=255, width=10)
    rings = rings.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1))
    ra = np.array(rings, np.float32)[..., None] / 255.0
    arr = np.array(img, np.float32)
    arr = arr * (1 - 0.07 * ra) + 0.07 * ra * np.array(WHITE, np.float32)
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(OUT / "bg_title.png")
    content = base + glow((W, H), (1750, 80), 900, CYAN, 0.06) + glow((W, H), (120, 1050), 800, ORANGE, 0.045)
    Image.fromarray(np.clip(content, 0, 255).astype(np.uint8)).save(OUT / "bg_content.png")


def logo(size=720):
    S = size * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    r = int(S * 0.27)
    wdt = int(S * 0.075)

    def ring(cx, c1, c2):
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).ellipse((cx - r, S // 2 - r, cx + r, S // 2 + r), outline=255, width=wdt)
        grad = np.zeros((S, S, 4), np.uint8)
        t = np.linspace(0, 1, S)[None, :, None]
        g = (np.array(c1)[None, None] * (1 - t) + np.array(c2)[None, None] * t).astype(np.uint8)
        grad[..., :3] = np.repeat(g, S, axis=0)
        grad[..., 3] = np.array(mask)
        layer = Image.fromarray(grad, "RGBA")
        return layer

    img = Image.alpha_composite(img, ring(int(S * 0.39), (125, 211, 252), (59, 130, 246)))
    img = Image.alpha_composite(img, ring(int(S * 0.61), (253, 224, 71), (244, 63, 94)))
    d = ImageDraw.Draw(img)
    cr = int(S * 0.055)
    d.ellipse((S // 2 - cr, S // 2 - cr, S // 2 + cr, S // 2 + cr), fill=(255, 255, 255, 255))
    img.resize((size, size), Image.LANCZOS).save(OUT / "logo.png")


def main(case_dir: str):
    OUT.mkdir(parents=True, exist_ok=True)
    c = Case(Path(case_dir))
    print("tumour error naive / final:", round(c.tumour_error(c.rigid(0)), 2), round(c.tumour_error(c.rigid(1)), 2))
    backgrounds()
    logo()
    equation_stills(c)
    registration_gif(c)
    sharpening_gif(c)
    sweep_gif(c)
    mip_gif(c)


if __name__ == "__main__":
    main(sys.argv[1])
