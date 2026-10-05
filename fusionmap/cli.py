"""Command-line interface.

    fusionmap serve                     # web app + API on http://localhost:8000
    fusionmap demo --seed 2026          # simulate a patient and run the whole pipeline
    fusionmap run --mri MRI --pet PET   # DICOM folder/zip or NIfTI inputs
    fusionmap phantom --seed 3 --dicom  # write a simulated patient as hospital-style DICOM
    fusionmap benchmark --cases 12      # quantitative validation table
    fusionmap push --folder F --host H --port P --aet A   # C-STORE to a PACS
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _print_summary(rep: dict) -> None:
    reg, an = rep.get("registration", {}), rep.get("analysis", {})
    print("\n== FusionMap summary ==")
    print(f"registration : {reg.get('method')}  NMI {reg.get('nmi_before', 0):.4f} -> {reg.get('nmi_after', 0):.4f}")
    print(f"enhancement  : {rep.get('enhancement', {}).get('method')}")
    for h in an.get("hotspots", []):
        print(f"hotspot {h['id']}: SUVmax {h['suv_max']:.2f}  SUVpeak {h['suv_peak']:.2f}  MTV {h['mtv_ml']:.2f} ml"
              f"  TBR {h['tbr_max']:.2f}  {h['side']}")
    v = rep.get("validation")
    if v:
        print(f"TRE          : {v['tre_naive']['mean_mm']:.2f} mm (naive) -> {v['tre_rigid']['mean_mm']:.2f} (rigid)"
              f" -> {v['tre_final']['mean_mm']:.2f} mm (final)")
        q0, q1 = v["quality_registered"], v.get("quality_enhanced") or {}
        print(f"PSNR / SSIM  : {q0['psnr_db']:.2f} dB / {q0['ssim']:.3f}  ->  {q1.get('psnr_db', float('nan')):.2f} dB"
              f" / {q1.get('ssim', float('nan')):.3f}")
        rc0 = [r["rc"] for r in v["recovery_registered"]]
        rc1 = [r["rc"] for r in v["recovery_enhanced"]]
        print(f"lesion RC    : {rc0} -> {rc1}")
        d = v["detection"]
        print(f"detection    : {d['detected']}/{d['pet_positive_lesions']}  FP {d['false_positives']}")
    if "export" in rep:
        print(f"DICOM export : {rep['export']['zip']} ({rep['export']['size_mb']} MB)")
    print(f"total        : {rep.get('total_seconds', 0):.1f} s  {rep.get('timings_s')}")


def _emit(e: dict) -> None:
    if e.get("type") == "step" and e.get("status") in ("done", "skipped", "error"):
        extra = f"{e['seconds']:.2f}s" if e.get("seconds") is not None else e.get("message", "")
        print(f"  [{e['status']:>7}] {e.get('label', e['step'])}  {extra}", flush=True)


def cmd_serve(a):
    import uvicorn

    uvicorn.run("fusionmap.api.app:app", host=a.host, port=a.port, reload=False, log_level="info")


def cmd_demo(a):
    from .io import Scan, ScanMeta
    from .phantom import PhantomConfig, make_phantom
    from .pipeline import PipelineOptions, run_pipeline

    cfg = PhantomConfig(seed=a.seed, tracer=a.tracer, lesion_mix=a.mix, n_lesions=a.lesions, mri_spacing=a.spacing)
    t = time.perf_counter()
    ph = make_phantom(cfg)
    print(f"simulated patient (seed {a.seed}, {a.tracer.upper()}) in {time.perf_counter() - t:.1f}s")
    out = Path(a.out or f"var/demo_{a.seed}")
    rep = run_pipeline(out, Scan(ph.mri, ScanMeta(modality="MR", patient_name=f"PHANTOM^SEED{a.seed}",
                                                  patient_id=f"FM-PH-{a.seed:04d}")),
                       Scan(ph.pet, ScanMeta(modality="PT")),
                       PipelineOptions(registration=a.registration, enhancement=a.enhancement,
                                       working_spacing_mm=a.spacing), _emit, ph)
    _print_summary(rep)
    print(f"\noutputs in {out}/")


def cmd_run(a):
    from .io import load_scan
    from .pipeline import PipelineOptions, run_pipeline

    mri = load_scan(a.mri, "MR")
    pet = load_scan(a.pet, "PT")
    rep = run_pipeline(Path(a.out), mri, pet, PipelineOptions(registration=a.registration, enhancement=a.enhancement,
                                                              pet_fwhm_mm=a.fwhm), _emit)
    _print_summary(rep)


def cmd_phantom(a):
    from .export.dicom import write_acquisition_dicom
    from .phantom import PhantomConfig, make_phantom

    ph = make_phantom(PhantomConfig(seed=a.seed, tracer=a.tracer, lesion_mix=a.mix))
    out = Path(a.out)
    ph.save(out / "truth")
    if a.dicom:
        info = write_acquisition_dicom(ph.mri, ph.pet, out / "dicom", patient_id=f"FM-PH-{a.seed:04d}",
                                       patient_name=f"PHANTOM^SEED{a.seed}", tracer=a.tracer)
        print(json.dumps(info, indent=2))
    print(json.dumps(ph.summary(), indent=2))


def cmd_benchmark(a):
    from .benchmark import run_benchmark

    res = run_benchmark(n_cases=a.cases, start_seed=a.start, out=Path(a.out), spacing=a.spacing)
    print(json.dumps(res["summary"], indent=2))


def cmd_push(a):
    from .export import push_folder

    print(json.dumps(push_folder(Path(a.folder), a.host, a.port, a.aet), indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fusionmap", description="AI software PET/MRI fusion (research prototype)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    for name, fn in (("demo", cmd_demo), ("run", cmd_run)):
        s = sub.add_parser(name)
        s.add_argument("--registration", default="auto")
        s.add_argument("--enhancement", default="auto")
        s.add_argument("--out", default=None if name == "demo" else "var/run")
        if name == "demo":
            s.add_argument("--seed", type=int, default=2026)
            s.add_argument("--tracer", default="fdg", choices=["fdg", "fet"])
            s.add_argument("--mix", default="showcase", choices=["active", "mixed", "showcase"])
            s.add_argument("--lesions", type=int, default=3)
            s.add_argument("--spacing", type=float, default=1.0, help="phantom/fusion grid in mm (2 = quick)")
        else:
            s.add_argument("--mri", required=True)
            s.add_argument("--pet", required=True)
            s.add_argument("--fwhm", type=float, default=6.0, help="PET scanner resolution (mm FWHM)")
        s.set_defaults(fn=fn)

    s = sub.add_parser("phantom")
    s.add_argument("--seed", type=int, default=2026)
    s.add_argument("--tracer", default="fdg", choices=["fdg", "fet"])
    s.add_argument("--mix", default="showcase", choices=["active", "mixed", "showcase"])
    s.add_argument("--out", default="var/phantom")
    s.add_argument("--dicom", action="store_true", help="also write hospital-style DICOM (separate studies)")
    s.set_defaults(fn=cmd_phantom)

    s = sub.add_parser("benchmark")
    s.add_argument("--cases", type=int, default=10)
    s.add_argument("--start", type=int, default=1000)
    s.add_argument("--spacing", type=float, default=1.0)
    s.add_argument("--out", default="docs/benchmark.json")
    s.set_defaults(fn=cmd_benchmark)

    s = sub.add_parser("push")
    s.add_argument("--folder", required=True)
    s.add_argument("--host", required=True)
    s.add_argument("--port", type=int, default=104)
    s.add_argument("--aet", default="ANY-SCP")
    s.set_defaults(fn=cmd_push)

    a = ap.parse_args(argv)
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
