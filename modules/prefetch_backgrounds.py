#!/usr/bin/env python3
"""
Minecraft Parkour Background Downloader
---------------------------------------
Lädt Minecraft-Parkour-Videos von YouTube herunter und speichert
sie in assets/backgrounds/ für die Video-Generierung.

Verwendung:
  python modules/prefetch_backgrounds.py           # 10 Videos herunterladen
  python modules/prefetch_backgrounds.py --count 20  # 20 Videos
  python modules/prefetch_backgrounds.py --list    # Bereits gecachte Videos anzeigen

Anforderungen:
  pip install yt-dlp
"""

import argparse
import os
import random
import subprocess
import sys
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / "assets" / "backgrounds"

# Search queries — only the viral, satisfying TikTok-style parkour videos
SEARCH_QUERIES = [
    "minecraft parkour satisfying tiktok",
    "satisfying minecraft parkour compilation",
    "minecraft smooth parkour no copyright",
    "minecraft parkour aesthetic satisfying",
    "minecraft parkour tiktok viral",
    "minecraft jump and run satisfying",
    "satisfying minecraft parkour gameplay",
    "minecraft parkour smooth no copyright free use",
    "minecraft parkour satisfying jumps compilation",
    "minecraft aesthetic parkour gameplay",
]


def _check_ytdlp():
    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _install_ytdlp():
    print("yt-dlp nicht gefunden — installiere...")
    subprocess.run([sys.executable, "-m", "pip", "install", "yt-dlp", "-q"], check=True)


def _count_cached() -> int:
    return len(list(CACHE_DIR.glob("*.mp4")))


def clear_cache():
    """Delete all cached background videos."""
    videos = list(CACHE_DIR.glob("*.mp4"))
    for v in videos:
        v.unlink(missing_ok=True)
    print(f"{len(videos)} videos cleared from cache.")


def download_backgrounds(count: int = 15, min_duration: int = 30, max_duration: int = 600):
    """
    Lädt Minecraft-Parkour-Videos herunter.
    count: Gewünschte Anzahl Videos (überspringt bereits heruntergeladene)
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    existing = _count_cached()
    if existing >= count:
        print(f"Bereits {existing} Videos im Cache — nichts zu tun.")
        print(f"Cache-Verzeichnis: {CACHE_DIR}")
        return

    if not _check_ytdlp():
        _install_ytdlp()

    needed = count - existing
    print(f"Lade {needed} Minecraft-Parkour-Videos herunter...")
    print(f"Ziel-Verzeichnis: {CACHE_DIR}\n")

    queries = SEARCH_QUERIES.copy()
    random.shuffle(queries)

    downloaded = 0
    for query in queries:
        if downloaded >= needed:
            break

        search_url = f"ytsearch{max(3, needed - downloaded)}:{query}"
        output_template = str(CACHE_DIR / "minecraft_%(id)s.%(ext)s")

        cmd = [
            "yt-dlp",
            search_url,
            "--output", output_template,
            "--format", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "--match-filter", f"duration >= {min_duration} & duration <= {max_duration}",
            "--max-downloads", str(max(2, needed - downloaded)),
            "--quiet",
            "--progress",
            "--no-warnings",
            # Metadaten nicht einbetten (kleinere Dateien)
            "--no-embed-metadata",
            "--no-embed-thumbnail",
        ]

        print(f"Suche: '{query}'")
        try:
            result = subprocess.run(cmd, timeout=300)
            new_count = _count_cached() - existing - downloaded
            if new_count > 0:
                downloaded += new_count
                print(f"  {downloaded}/{needed} Videos heruntergeladen\n")
        except subprocess.TimeoutExpired:
            print(f"  Timeout bei '{query}' — überspringe\n")
        except Exception as e:
            print(f"  Fehler: {e}\n")

    final = _count_cached()
    print(f"\nFertig! {final} Videos im Cache:")
    for v in sorted(CACHE_DIR.glob("*.mp4")):
        size_mb = v.stat().st_size / 1_048_576
        print(f"  {v.name} ({size_mb:.1f} MB)")


def list_cached():
    videos = sorted(CACHE_DIR.glob("*.mp4"))
    if not videos:
        print(f"Kein Video im Cache ({CACHE_DIR})")
        print("Führe 'python modules/prefetch_backgrounds.py' aus um Videos herunterzuladen.")
        return
    total_mb = sum(v.stat().st_size for v in videos) / 1_048_576
    print(f"{len(videos)} Videos im Cache ({total_mb:.0f} MB gesamt):")
    for v in videos:
        size_mb = v.stat().st_size / 1_048_576
        print(f"  {v.name} ({size_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Minecraft Parkour Background Downloader")
    parser.add_argument("--count", type=int, default=15,
                        help="Number of videos to download (default: 15)")
    parser.add_argument("--list", action="store_true",
                        help="Show already cached videos")
    parser.add_argument("--refresh", action="store_true",
                        help="Clear cache and download fresh videos")
    args = parser.parse_args()

    if args.list:
        list_cached()
    elif args.refresh:
        clear_cache()
        download_backgrounds(count=args.count)
    else:
        download_backgrounds(count=args.count)


if __name__ == "__main__":
    main()
