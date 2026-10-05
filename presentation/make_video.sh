#!/usr/bin/env bash
# WebM from record_demo.mjs -> presentation/assets/demo.mp4 (H.264, plays in PowerPoint)
# usage: presentation/make_video.sh <video dir written by record_demo.mjs>
set -euo pipefail
DIR=${1:-presentation/build/video}
read -r FILE READY END < <(python3 -c "import json,sys;t=json.load(open('$DIR/timing.json'));print(t['file'],t['ready'],t['end'])")
START=$(python3 -c "print(max(0, $READY - 0.2))")
LEN=$(python3 -c "print($END - $START)")
OUT="$(dirname "$0")/assets/demo.mp4"
ffmpeg -y -loglevel error -ss "$START" -t "$LEN" -i "$FILE" \
  -vf "fps=30,scale=1600:-2:flags=lanczos,format=yuv420p" \
  -c:v libx264 -preset slow -crf 26 -profile:v high -movflags +faststart -an "$OUT"
ffmpeg -y -loglevel error -ss 0.5 -i "$OUT" -frames:v 1 "$(dirname "$0")/assets/demo_poster.png"
echo "wrote $OUT ($(du -h "$OUT" | cut -f1), $(python3 -c "print(round($LEN,1))") s)"
