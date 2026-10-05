# FusionMap pitch deck

**[`FusionMap_Pitch.pptx`](FusionMap_Pitch.pptx)**: 17 slides, about 5½ minutes including a 60-second live demo.
There is a static [`FusionMap_Pitch.pdf`](FusionMap_Pitch.pdf) for submission portals.

Every image and animation in the deck is real FusionMap output from the showcase patient (seed 2026).
Every number comes from [`docs/benchmark.json`](../docs/benchmark.json) or that patient's report. The market
figures (scanner cost, centre and patient counts) are the team's research, and slide 5 labels them as such.

## Presenting

1. Open the deck in **PowerPoint 2019 or Microsoft 365** and press **F5**. Morph transitions need one of those
   versions. Older PowerPoint shows a fade instead. Keynote and Google Slides may drop some builds, so present from PowerPoint.
2. **One click = next slide.** Each slide's builds play by themselves, so you never click through
   bullets. The animated images (alignment, sharpening, slice sweep, rotating projection) loop on their own.
3. **The speaker notes are the script.** Each slide has a time cue, so use Presenter View
   (Alt+F5) and read from the notes. Slide 17 is a backup Q&A slide; show it only if asked.
4. **Live demo (slide 10).** Before the talk, run `fusionmap serve` (or `docker compose up`) and open
   <http://localhost:8000>. If anything fails, stay on slide 10 and click the picture: it is a
   50-second recording of the real app doing the same five steps.

Short slot (3 minutes)? Skip slides 5, 9 and 13, and do the demo from the slide-10 video.

| # | Slide | Motion |
|---|-------|--------|
| 1 | FusionMap · title | fused-slice sweep, staggered builds |
| 2 | 13 mm off target | number zooms in over the naive-overlay image |
| 3 | MRI sees two lesions, PET knows which is alive | lesions circled one by one |
| 4 | Fused | **Morph**: the MRI and PET slide together into the fused image |
| 5 | The gap: 700+ centres, ~10 hybrid scanners | cards float in |
| 6 | Three steps | step cards build left to right |
| 7–9 | Register · Sharpen · Fuse & export | **Morph**: the step circles fly up into a progress tracker; registration, sharpening and sweep animations |
| 10 | Live demo | embedded backup video |
| 11 | Validation | native charts wipe up |
| 12 | Trust: radionecrosis trap, AI gate | callouts draw onto the fused slice |
| 13 | Engineering | architecture builds left to right |
| 14 | Impact | PET-MRI scanner vs FusionMap |
| 15 | Roadmap | timeline draws, phases pop in |
| 16 | Close | fusion rings around the rotating projection |
| 17 | Backup: judge Q&A | |

## Rebuilding

```bash
cd presentation && npm install                      # pptxgenjs, react-icons, sharp
python make_assets.py ../var/showcase/cases/<id>    # GIFs and stills from a processed case
node make_icons.js                                  # icon PNGs
node build_deck.js && python animate.py             # deck, then animations and transitions
```

* `build_deck.js` lays out the slides with [pptxgenjs](https://gitbrent.github.io/PptxGenJS/). It uses a theme,
  three slide layouts and named shapes, and writes `build/animations.json`.
* `animate.py` injects what pptxgenjs cannot write: auto-starting entrance effects, Morph and fade
  transitions, click-to-play for the video, and the theme colours. It also de-duplicates media.
* `record_demo.mjs` + `make_video.sh` re-record `assets/demo.mp4` against a running server (Playwright and ffmpeg).
