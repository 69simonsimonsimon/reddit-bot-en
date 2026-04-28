#!/usr/bin/env python3
"""
Reddit Story Bot — English
--------------------------
Fetches Reddit stories and creates TikTok videos.

Usage:
  python main.py                        # Create + upload one video
  python main.py --subreddit tifu       # Specific subreddit
  python main.py --only-create          # Create only, no upload
"""

import argparse
import os
import random
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

sys.path.insert(0, str(Path(__file__).parent / "modules"))

from story_fetcher import fetch_story, SUBREDDITS
from tts import text_to_speech
from video_creator import create_video
from tiktok_uploader_zernio import upload_video_browser

OUTPUT_DIR = Path(__file__).parent / "output"


def run_once(subreddit: str = None, only_create: bool = False) -> str:
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_path = OUTPUT_DIR / f"audio_{timestamp}.mp3"
    video_path = OUTPUT_DIR / f"video_{timestamp}.mp4"

    print(f"\n{'='*50}")
    print(f"Reddit Story Bot EN — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    print("1. Fetching Reddit story...")
    story_data = fetch_story(subreddit_override=subreddit)
    print(f"   r/{story_data['subreddit']}: {story_data['title']}")
    print(f"   Story: {story_data['story'][:80]}...")

    print("\n2. Creating voiceover...")
    tts_text = f"{story_data['title']}. {story_data['story']}"
    words    = tts_text.split()
    if len(words) > 155:
        tts_text = " ".join(words[:155])
        for end_char in [". ", "! ", "? "]:
            idx = tts_text.rfind(end_char)
            if idx > 50:
                tts_text = tts_text[:idx + 1]
                break

    _, word_timings = text_to_speech(tts_text, str(audio_path))
    print(f"   Audio: {audio_path.name} ({len(word_timings)} words)")

    print("\n3. Creating video...")
    create_video(
        subreddit=story_data["subreddit"],
        title=story_data["title"],
        story=story_data["story"],
        audio_path=str(audio_path),
        output_path=str(video_path),
        word_timings=word_timings,
        gradient_index=random.randint(0, 4),
    )
    audio_path.unlink(missing_ok=True)
    print(f"   Video: {video_path.name}")

    description  = story_data.get("description", story_data["title"])
    full_caption = description + "\n" + " ".join(story_data["hashtags"])

    import json as _json
    meta = {
        "title":     story_data["title"],
        "subreddit": story_data["subreddit"],
        "caption":   full_caption,
        "uploaded":  False,
    }
    Path(str(video_path).replace(".mp4", ".json")).write_text(
        _json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if only_create:
        print(f"\nVideo saved (no upload): {video_path}")
        return str(video_path)

    print("\n4. Uploading to platforms...")
    try:
        success = upload_video_browser(str(video_path), full_caption)
        if success:
            print("\nSuccessfully uploaded!")
        else:
            print(f"\nUpload incomplete — video saved locally: {video_path}")
    except Exception as e:
        print(f"\nUpload failed: {e}")

    return str(video_path)


def main():
    parser = argparse.ArgumentParser(description="Reddit Story Bot EN")
    parser.add_argument("--subreddit", type=str, default=None,
                        help=f"Subreddit: {', '.join(SUBREDDITS[:5])}...")
    parser.add_argument("--only-create", action="store_true",
                        help="Create video only, no upload")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    run_once(subreddit=args.subreddit, only_create=args.only_create)


if __name__ == "__main__":
    main()
