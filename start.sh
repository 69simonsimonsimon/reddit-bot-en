#!/bin/bash
set -e

BACKGROUNDS_DIR="${BACKGROUNDS_DIR:-/data/backgrounds}"
mkdir -p "$BACKGROUNDS_DIR"

# ── Phase 1: GitHub-Paket (immer prüfen, falls Dateien fehlen) ────────────────
GITHUB_BASE="https://github.com/69simonsimonsimon/minecraft-backgrounds/releases/download/v1.0"
VIDEOS=(
  "minecraft_jEe6rlZmc68.f136.mp4"
  "minecraft_CX8pRir5pLc.f399.mp4"
  "minecraft_zKoYyLeuwto.f137.mp4"
  "minecraft_Rdwg1Iq2Wx8.f137.mp4"
  "minecraft_WVjzTcoO6l0.f136.mp4"
  "minecraft_nyc4WgnNkrc.f299.mp4"
  "minecraft_otvrdG5tS5g.f137.mp4"
  "minecraft_ZWQQSFOV1Ok.f299.mp4"
  "minecraft_lC4RGhlGjFg.f137.mp4"
  "minecraft_6iGJYL7Y484.f299.mp4"
  "minecraft_aNwDMKzYfgo.f399.mp4"
)

for VIDEO in "${VIDEOS[@]}"; do
  DEST="$BACKGROUNDS_DIR/$VIDEO"
  if [ ! -f "$DEST" ]; then
    echo "  Downloading $VIDEO ..."
    curl -L -o "$DEST" "$GITHUB_BASE/$VIDEO" || echo "  WARN: $VIDEO failed"
  fi
done

# ── Phase 2: Delete old yt-dlp videos, re-download with correct queries ────────
# Always refresh — old queries (bedwars, dropper, skyblock) have been removed
echo "Refreshing yt-dlp backgrounds with satisfying parkour queries..."
find "$BACKGROUNDS_DIR" -name "mc_ytdlp_*.mp4" -delete 2>/dev/null || true

pip install yt-dlp -q 2>/dev/null || true

TARGET=25
QUERIES=(
  "minecraft parkour satisfying tiktok"
  "satisfying minecraft parkour compilation"
  "minecraft smooth parkour no copyright"
  "minecraft parkour aesthetic satisfying"
  "minecraft parkour tiktok viral"
  "minecraft jump and run satisfying"
  "satisfying minecraft parkour gameplay"
  "minecraft parkour smooth no copyright free use"
  "minecraft parkour satisfying jumps compilation"
  "minecraft aesthetic parkour gameplay"
)

for QUERY in "${QUERIES[@]}"; do
  CURRENT=$(find "$BACKGROUNDS_DIR" -name "*.mp4" | wc -l | tr -d ' ')
  if [ "$CURRENT" -ge "$TARGET" ]; then
    break
  fi
  echo "  Searching: $QUERY"
  yt-dlp "ytsearch3:$QUERY" \
    --output "$BACKGROUNDS_DIR/mc_ytdlp_%(id)s.%(ext)s" \
    --format "bestvideo[height<=1080][ext=mp4]/best[height<=1080][ext=mp4]/best" \
    --merge-output-format mp4 \
    --no-playlist \
    --match-filter "duration >= 30 & duration <= 600" \
    --max-downloads 3 \
    --quiet --no-warnings \
    --no-embed-metadata --no-embed-thumbnail \
    2>/dev/null || true
done

echo "Backgrounds ready: $(find "$BACKGROUNDS_DIR" -name "*.mp4" | wc -l | tr -d ' ') videos"

exec python dashboard/app.py
