"""Assemble swipe frames (PNG) captured from the viewer into an optimised GIF for the README.

    python scripts/make_gif.py FRAME_DIR docs/screenshots/swipe.gif [--width 620]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--width", type=int, default=620)
    ap.add_argument("--ms", type=int, default=110)
    a = ap.parse_args()
    files = sorted(a.frames.glob("*.png"))
    frames = []
    for f in files:
        im = Image.open(f).convert("RGB")
        h = round(im.height * a.width / im.width)
        frames.append(im.resize((a.width, h), Image.LANCZOS).quantize(colors=160, method=Image.Quantize.MEDIANCUT))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(a.out, save_all=True, append_images=frames[1:], duration=a.ms, loop=0, optimize=True, disposal=2)
    print(a.out, f"{a.out.stat().st_size / 1e6:.2f} MB", len(frames), "frames")


if __name__ == "__main__":
    main()
