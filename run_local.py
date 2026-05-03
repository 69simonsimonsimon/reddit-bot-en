#!/usr/bin/env python3
"""
SynCin Reddit Story Bot EN — Local Video Generator
====================================================
Generates a Reddit story video and uploads it to the Bunny queue.
GitHub Actions posts it automatically on schedule.

Usage:
  python run_local.py              # random subreddit
  python run_local.py tifu
  python run_local.py aita 3       # generate 3 videos
"""

import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=True)
sys.path.insert(0, str(ROOT / "modules"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("redditbot-en")

OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def _cleanup_stale_files():
    """Delete temp audio/video files older than 20 min left by previous crashes."""
    cutoff = time.time() - 20 * 60
    for pattern in ["audio_*.mp3", "video_*.mp4"]:
        for f in OUTPUT_DIR.glob(pattern):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    logger.info(f"🧹  Stale file removed: {f.name}")
            except Exception:
                pass


def generate_and_queue(subreddit: str = None) -> bool:
    import certifi
    import requests

    from story_fetcher import fetch_story, SUBREDDITS
    from tts import text_to_speech
    from video_creator import create_video
    from quality_check import quality_check

    stamp      = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-3]
    audio_path = OUTPUT_DIR / f"audio_{stamp}.mp3"
    video_path = OUTPUT_DIR / f"video_{stamp}.mp4"

    try:
        # 1. Fetch Reddit story
        logger.info("📖  Fetching Reddit story...")
        story_data = fetch_story(subreddit_override=subreddit)
        logger.info(f"    → r/{story_data['subreddit']}: {story_data['title'][:60]}")

        # 1b. AI Quality Check
        logger.info("🤖  AI quality check...")
        approved, reason = quality_check(
            title=story_data["title"],
            content=story_data["story"],
            context=f"r/{story_data['subreddit']}",
            lang="en",
        )
        logger.info(f"    → {reason}")
        if not approved:
            logger.info("    ❌  Rejected — skipping this video")
            return False

        # 2. TTS + Word Timings
        logger.info("🎙️   Generating voiceover (OpenAI)...")
        _ctas = [
            "Follow for more stories like this every day!",
            "Drop a follow so you never miss a story!",
            "Follow us for daily stories that will blow your mind!",
            "If this got you, follow — new stories every single day!",
            "Follow for more insane stories posted daily!",
            "Hit follow — we post the best Reddit stories every day!",
        ]
        cta = random.choice(_ctas)
        tts_text = f"{story_data['title']}. {story_data['story']} {cta}"
        words = tts_text.split()
        if len(words) > 155:
            tts_text = " ".join(words[:155])
            for end_char in [". ", "! ", "? "]:
                idx = tts_text.rfind(end_char)
                if idx > 50:
                    tts_text = tts_text[:idx + 1]
                    break

        _, word_timings = text_to_speech(tts_text, str(audio_path))
        logger.info(f"    → {len(word_timings)} words")

        # 3. Render video
        logger.info("🎞️   Rendering video...")
        create_video(
            subreddit=story_data["subreddit"],
            title=story_data["title"],
            story=story_data["story"],
            audio_path=str(audio_path),
            output_path=str(video_path),
            word_timings=word_timings,
            gradient_index=random.randint(0, 4),
        )
        audio_path.unlink(missing_ok=True)  # free space early

        mb = video_path.stat().st_size / 1024 / 1024
        logger.info(f"    → {video_path.name} ({mb:.1f} MB)")

        # 4. Caption
        description  = story_data.get("description", story_data["title"])
        full_caption = description + "\n" + " ".join(story_data["hashtags"])

        # 5. Upload to Bunny queue
        logger.info("☁️   Uploading to Bunny queue...")
        password = os.environ["BUNNY_STORAGE_PASSWORD"]
        zone     = os.environ.get("BUNNY_STORAGE_NAME", "syncin")
        cdn_url  = os.environ.get("BUNNY_CDN_URL", "https://syncin.b-cdn.net")
        hostname = os.environ.get("BUNNY_STORAGE_HOSTNAME", "storage.bunnycdn.com")

        filename = f"reddit_en_{stamp}.mp4"

        with open(str(video_path), "rb") as f:
            r = requests.put(
                f"https://{hostname}/{zone}/queue/{filename}",
                headers={"AccessKey": password, "Content-Type": "video/mp4"},
                data=f, verify=certifi.where(), timeout=300,
            )
        r.raise_for_status()

        meta = {
            "title":     story_data["title"],
            "caption":   full_caption,
            "subreddit": story_data["subreddit"],
            "cdn_url":   f"{cdn_url}/queue/{filename}",
        }
        mr = requests.put(
            f"https://{hostname}/{zone}/queue/{filename.replace('.mp4', '.json')}",
            headers={"AccessKey": password, "Content-Type": "application/json"},
            data=json.dumps(meta, ensure_ascii=False).encode(),
            verify=certifi.where(), timeout=30,
        )
        mr.raise_for_status()

        video_path.unlink(missing_ok=True)  # uploaded — delete local copy
        logger.info(f"✅  Queued: {filename}")
        logger.info(f"    Title: {story_data['title'][:60]}")
        return True

    finally:
        # Safety net: always clean up temp files even if a step crashed
        audio_path.unlink(missing_ok=True)
        video_path.unlink(missing_ok=True)


if __name__ == "__main__":
    import concurrent.futures
    _cleanup_stale_files()

    subreddit = sys.argv[1] if len(sys.argv) > 1 else None
    count     = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    workers   = min(count, int(sys.argv[3]) if len(sys.argv) > 3 else 3)

    done = []

    def _task(i):
        if count > 1:
            logger.info(f"\n{'='*50}\nVideo {i+1}/{count}\n{'='*50}")
        if generate_and_queue(subreddit):
            done.append(1)

    if workers > 1 and count > 1:
        logger.info(f"🚀  Parallel: {count} videos × {workers} workers")
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_task, range(count)))
    else:
        for i in range(count):
            _task(i)

    logger.info(f"\n🏁  Done: {len(done)}/{count} videos queued on Bunny")
