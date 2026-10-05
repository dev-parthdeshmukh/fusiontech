"""Printable, self-contained HTML case report (key images embedded as PNG data URIs)."""

from __future__ import annotations

import base64
import gzip
import html
import io
import json
from datetime import datetime
from pathlib import Path

import numpy as np
from skimage import io as skio

from .. import DISCLAIMER, __version__
from ..fusion import FusionSettings, fuse


def _load(viewer: Path, manifest: dict, name: str) -> np.ndarray | None:
    v = manifest["volumes"].get(name)
    if not v:
        return None
    raw = gzip.decompress((viewer / v["file"]).read_bytes())
    return np.frombuffer(raw, np.uint8).reshape(manifest["shape_zyx"]).astype(np.float32)


def _png(rgb: np.ndarray, scale: int = 2) -> str:
    if scale > 1:
        rgb = np.repeat(np.repeat(rgb, scale, 0), scale, 1)
    buf = io.BytesIO()
    skio.imsave(buf, rgb, format="png", check_contrast=False)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _gray(a: np.ndarray) -> np.ndarray:
    g = np.clip(a, 0, 255).astype(np.uint8)
    return np.stack([g] * 3, -1)


def render_report(case: dict, report: dict, case_dir: Path) -> str:
    viewer = case_dir / "viewer"
    manifest = json.loads((viewer / "manifest.json").read_text())
    mri = _load(viewer, manifest, "mri")
    naive = _load(viewer, manifest, "pet_naive")
    enh = _load(viewer, manifest, "pet_enhanced")
    an = report.get("analysis", {})
    disp = an.get("display", {})
    pet_hi = manifest["volumes"]["pet_enhanced"]["hi"]
    thr8 = disp.get("pet_threshold", 0) / pet_hi * 255
    top8 = disp.get("pet_max", pet_hi) / pet_hi * 255
    st = FusionSettings(colormap=manifest.get("colormap", "hot"), mri_window=(0, 255), pet_range=(thr8, top8),
                        opacity=0.8)
    spots = an.get("hotspots", [])
    shape = manifest["shape_zyx"]
    k0 = spots[0]["peak_index_zyx"][0] if spots else shape[0] // 2

    figs = []
    if mri is not None and naive is not None and enh is not None:
        figs.append(("Before: naive overlay (scanner coordinates)", _png(fuse(mri[k0], naive[k0], st))))
        figs.append(("After: FusionMap registered + enhanced", _png(fuse(mri[k0], enh[k0], st))))
    for s in spots[:4]:
        z, y, x = s["peak_index_zyx"]
        ax = fuse(mri[z], enh[z], st)
        co = fuse(mri[:, y, :][::-1], enh[:, y, :][::-1], st)
        figs.append((f"Hotspot {s['id']} — axial", _png(ax)))
        figs.append((f"Hotspot {s['id']} — coronal", _png(co)))

    reg = report.get("registration", {})
    val = report.get("validation") or {}
    rows = "".join(
        f"<tr><td>{s['id']}</td><td>{s['side']}</td><td>{s['suv_max']:.2f}</td><td>{s['suv_peak']:.2f}</td>"
        f"<td>{s['suv_mean']:.2f}</td><td>{s['mtv_ml']:.2f}</td><td>{s['tlg']:.2f}</td><td>{s['tbr_max']:.2f}</td>"
        f"<td>{', '.join(f'{v:.1f}' for v in s['peak_mm'])}</td></tr>" for s in spots) or \
        "<tr><td colspan=9>No hotspot above the TBR threshold.</td></tr>"
    qa = [
        ("Registration method", reg.get("method", "-")),
        ("Rigid correction", f"rot {reg.get('rigid', {}).get('rotation_deg', '-')}°, "
                             f"shift {reg.get('rigid', {}).get('translation_mm', '-')} mm"),
        ("Normalised mutual information", f"{reg.get('nmi_before', 0):.4f} → {reg.get('nmi_after', 0):.4f}"),
        ("MRI/PET edge alignment", f"{reg.get('edge_alignment_before', 0):.3f} → {reg.get('edge_alignment_after', 0):.3f}"),
        ("Enhancement", report.get("enhancement", {}).get("method", "-")),
        ("Total processing time", f"{report.get('total_seconds', 0):.1f} s"),
    ]
    if val:
        qa += [
            ("Target registration error (truth)", f"{val['tre_naive']['mean_mm']:.2f} mm → {val['tre_final']['mean_mm']:.2f} mm"),
            ("Lesion detection (truth)", f"{val['detection']['detected']}/{val['detection']['pet_positive_lesions']}, "
                                         f"{val['detection']['false_positives']} false positive(s)"),
        ]
    qa_rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in qa)
    fig_html = "".join(f"<figure><img src='{src}'/><figcaption>{html.escape(cap)}</figcaption></figure>"
                       for cap, src in figs)
    meta = report.get("inputs", {}).get("mri", {}).get("meta", {})
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>FusionMap report — {html.escape(case.get('name', ''))}</title>
<style>
body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#0f172a;margin:32px auto;max-width:1000px;padding:0 20px}}
h1{{font-size:22px;margin:0}} h2{{font-size:16px;margin:28px 0 8px;border-bottom:1px solid #e2e8f0;padding-bottom:4px}}
.sub{{color:#475569}} .warn{{background:#fff7ed;border:1px solid #fdba74;padding:8px 12px;border-radius:6px;margin:16px 0}}
table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid #e2e8f0;padding:6px 8px;text-align:left;font-variant-numeric:tabular-nums}}
th{{color:#334155;font-weight:600;width:38%}} thead th{{width:auto;background:#f8fafc}}
.figs{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}}
figure{{margin:0}} img{{width:100%;border-radius:6px;background:#000}} figcaption{{font-size:12px;color:#475569}}
@media print{{body{{margin:0}} .figs{{grid-template-columns:repeat(3,1fr)}}}}
</style></head><body>
<h1>FusionMap PET/MRI fusion report</h1>
<div class="sub">{html.escape(case.get('name', ''))} · Patient {html.escape(str(meta.get('patient_name', '-')))} ({html.escape(str(meta.get('patient_id', '-')))}) ·
generated {datetime.now():%Y-%m-%d %H:%M} · FusionMap v{__version__}</div>
<div class="warn">{html.escape(DISCLAIMER)}. Findings must be confirmed by a qualified nuclear medicine physician / radiologist.</div>
<h2>Quality assurance</h2><table>{qa_rows}</table>
<h2>PET hotspots (biological tumour volume, TBR ≥ {an.get('tbr_threshold', 1.6)}; background SUV {an.get('background_suv', 0):.2f})</h2>
<table><thead><tr><th>#</th><th>Side</th><th>SUVmax</th><th>SUVpeak</th><th>SUVmean</th><th>MTV (ml)</th><th>TLG</th><th>TBRmax</th><th>Peak (mm, LPS)</th></tr></thead>
<tbody>{rows}</tbody></table>
<h2>Key images</h2><div class="figs">{fig_html}</div>
</body></html>"""
