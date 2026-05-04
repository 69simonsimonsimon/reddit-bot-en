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
from datetime import datetime, date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=True)
sys.path.insert(0, str(ROOT / "modules"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("redditbot-en")

OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Trending hashtag rotation (daily seed keeps them fresh) ──────────────────
_TRENDING_POOL = [
    "#redditreadings", "#redditreads", "#redtok", "#asmrstory", "#storytok",
    "#mustwatch", "#unbelievable", "#crazy", "#shocking", "#mindblown",
    "#viralstory", "#stitch", "#duet", "#fypage", "#fypシ",
    "#drama2025", "#storydrama", "#relationshipdrama", "#redditdrama2025",
    "#viralreddit", "#redditstorytime", "#tiktokstory", "#storytelling",
]

def _daily_trending(n: int = 3) -> list[str]:
    """Returns n hashtags from trending pool, rotated by day."""
    seeded = _TRENDING_POOL.copy()
    rng = random.Random(date.today().toordinal())
    rng.shuffle(seeded)
    return seeded[:n]


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

        # Get mood early — needed for voice selection + caption
        from video_creator import SUBREDDIT_MOOD
        mood = SUBREDDIT_MOOD.get(story_data["subreddit"], "")

        # Part-2 cliffhanger: use pre-split part1 (long stories) or force-split (30% chance)
        is_part2_format = False
        if story_data.get("part2"):
            # story_fetcher already split this into cliffhanger + resolution
            is_part2_format = True
            logger.info("    → Part 2 format (long story split)")
        elif random.random() < 0.30:
            # Short story: artificially cut at ~70% for cliffhanger
            words_all = story_data["story"].split()
            cut_idx   = max(30, int(len(words_all) * 0.70))
            story_data["part2"] = " ".join(words_all[cut_idx:])
            story_data["story"] = " ".join(words_all[:cut_idx]) + "..."
            is_part2_format = True
            logger.info("    → Part 2 format (artificial cliffhanger)")

        # 2. TTS + Word Timings  (target: 45-55s = ~110-130 words)
        logger.info("🎙️   Generating voiceover (OpenAI)...")
        if is_part2_format:
            _ctas = [
                "Follow for Part 2 tomorrow! What do you think happens? 👇",
                "Stitch this with your reaction! Part 2 drops tomorrow 🔔",
                "Comment your prediction — Part 2 coming tomorrow!",
                "What would you have done? Part 2 drops tomorrow 👇",
            ]
        else:
            _ctas = [
                "What would you have done in this situation? Comment below! 👇",
                "Stitch this with your reaction — I want to hear your take!",
                "Comment: who's in the wrong here? 👇",
                "What do you think about this? Drop a comment! 🔥",
                "Send this to someone who needs to see it 👀 Comment your opinion!",
                "Would you have done the same? Let me know! 👇",
            ]
        cta = random.choice(_ctas)
        tts_text = f"{story_data['title']}. {story_data['story']} {cta}"
        words = tts_text.split()
        # TikTok monetization: 165 words → ~65-70 seconds at average TTS speed
        MAX_WORDS = 165
        if len(words) > MAX_WORDS:
            tts_text = " ".join(words[:MAX_WORDS])
            for end_char in [". ", "! ", "? "]:
                idx = tts_text.rfind(end_char)
                if idx > 50:
                    tts_text = tts_text[:idx + 1]
                    break

        _, word_timings = text_to_speech(tts_text, str(audio_path), mood=mood)
        logger.info(f"    → {len(word_timings)} words  [voice: {mood or 'default'}]")

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

        # 4. Caption — emoji hook + title + question + hashtags
        from video_creator import SUBREDDIT_QUESTIONS, DEFAULT_QUESTION
        question     = SUBREDDIT_QUESTIONS.get(story_data["subreddit"], DEFAULT_QUESTION)
        _emojis      = {"drama": "😤", "funny": "😂", "sad": "💔", "suspense": "👀"}
        mood_emoji   = _emojis.get(mood, "👀")
        description  = story_data.get("description", story_data["title"])

        # Part-2 cliffhanger marker in caption
        part2_line = "\n🔔 Part 2 dropping tomorrow — follow now!" if is_part2_format else ""
        # Stitch/duet bait in 35% of videos
        stitch_line = "\n🎭 Stitch this with your reaction 👇" if random.random() < 0.5 else ""
        # Daily-rotating trending hashtags
        trending = _daily_trending(3)

        full_caption = (
            f"{mood_emoji} {description}\n\n"
            f"{question}{part2_line}{stitch_line}\n\n"
            + " ".join(story_data["hashtags"] + trending)
        )

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

        # 6. Generate + upload Part 2 if available
        if is_part2_format and story_data.get("part2"):
            logger.info("🎞️   Generating Part 2...")
            stamp2   = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-3]
            audio2   = OUTPUT_DIR / f"audio2_{stamp2}.mp3"
            video2   = OUTPUT_DIR / f"video2_{stamp2}.mp4"
            try:
                p2_cta    = random.choice([
                    "Follow for more stories every day!",
                    "Drop a follow — new stories daily!",
                    "Follow us for more insane Reddit stories!",
                ])
                tts2_text = f"Part 2. {story_data['title']}. {story_data['part2']} {p2_cta}"
                words2    = tts2_text.split()
                if len(words2) > MAX_WORDS:
                    tts2_text = " ".join(words2[:MAX_WORDS])
                    for ec in [". ", "! ", "? "]:
                        idx = tts2_text.rfind(ec)
                        if idx > 50:
                            tts2_text = tts2_text[:idx + 1]
                            break
                _, wt2 = text_to_speech(tts2_text, str(audio2), mood=mood)
                create_video(
                    subreddit=story_data["subreddit"],
                    title=f"{story_data['title']} (Part 2)",
                    story=story_data["part2"],
                    audio_path=str(audio2),
                    output_path=str(video2),
                    word_timings=wt2,
                    gradient_index=random.randint(0, 4),
                )
                audio2.unlink(missing_ok=True)
                caption2 = (
                    f"{mood_emoji} {description} — Part 2 👀\n\n"
                    f"{question}\n\n"
                    + " ".join(story_data["hashtags"] + trending)
                )
                fn2 = f"reddit_en_{stamp2}.mp4"
                with open(str(video2), "rb") as f2:
                    requests.put(
                        f"https://{hostname}/{zone}/queue/{fn2}",
                        headers={"AccessKey": password, "Content-Type": "video/mp4"},
                        data=f2, verify=certifi.where(), timeout=300,
                    ).raise_for_status()
                requests.put(
                    f"https://{hostname}/{zone}/queue/{fn2.replace('.mp4', '.json')}",
                    headers={"AccessKey": password, "Content-Type": "application/json"},
                    data=json.dumps({
                        "title":     f"{story_data['title']} (Part 2)",
                        "caption":   caption2,
                        "subreddit": story_data["subreddit"],
                        "cdn_url":   f"{cdn_url}/queue/{fn2}",
                    }, ensure_ascii=False).encode(),
                    verify=certifi.where(), timeout=30,
                ).raise_for_status()
                video2.unlink(missing_ok=True)
                logger.info(f"✅  Part 2 Queued: {fn2}")
            except Exception as e:
                logger.error(f"❌  Part 2 failed: {e}", exc_info=True)
            finally:
                audio2.unlink(missing_ok=True)
                video2.unlink(missing_ok=True)

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
