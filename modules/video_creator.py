import os
import random
from pathlib import Path

import numpy as np
import requests
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
    vfx,
)
from PIL import Image, ImageDraw, ImageFont

WIDTH  = 1080
HEIGHT = 1920

# ── Fonts ─────────────────────────────────────────────────────────────────────

def _resolve_font(mac_path: str, linux_candidates: list) -> str:
    if Path(mac_path).exists():
        return mac_path
    for c in linux_candidates:
        if Path(c).exists():
            return c
    try:
        import subprocess
        out = subprocess.check_output(["fc-list", "--format=%{file}\n"], text=True, timeout=5)
        for line in out.splitlines():
            line = line.strip()
            if line and any(n in line for n in ["Liberation", "DejaVu", "Arial", "Helvetica"]):
                return line
    except Exception:
        pass
    return mac_path

BOLD = _resolve_font(
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ],
)

_bg_env   = os.environ.get("BACKGROUNDS_DIR", "")
CACHE_DIR = Path(_bg_env) if _bg_env else Path(__file__).parent.parent / "assets" / "backgrounds"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MUSIC_DIR = Path(__file__).parent.parent / "assets" / "music"
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

# ── Subreddit → Pexels query mapping ─────────────────────────────────────────

SUBREDDIT_QUERIES: dict[str, list[str]] = {
    "AmItheAsshole":         ["people arguing", "couple conflict", "family tension"],
    "AITAH":                 ["people arguing", "couple conflict", "family tension"],
    "AmIOverreacting":       ["emotional person", "relationship stress", "couple talking"],
    "tifu":                  ["accident fail", "awkward moment", "surprised reaction"],
    "mildlyinfuriating":     ["frustrated person", "annoying situation", "stress daily life"],
    "facepalm":              ["facepalm cringe", "disbelief reaction", "awkward fail"],
    "Unexpected":            ["surprise shock", "unexpected moment", "plot twist"],
    "relationship_advice":   ["couple romantic", "love relationship", "people talking"],
    "breakups":              ["heartbreak sad", "lonely person", "rain window sadness"],
    "confessions":           ["person alone thinking", "dark moody atmosphere", "confession emotional"],
    "teenagers":             ["young people city", "teen lifestyle", "youth social"],
    "college":               ["university campus", "student life", "college social"],
    "TwoHotTakes":           ["drama reaction", "shocked expression", "two people debate"],
    "pettyrevenge":          ["satisfying revenge", "karma justice", "victory moment"],
    "maliciouscompliance":   ["smart loophole", "office work", "subtle revenge"],
    "ProRevenge":            ["revenge success", "justice served", "victory celebration"],
    "entitledparents":       ["angry person", "entitled behavior", "parent child conflict"],
    "entitledpeople":        ["angry person", "entitled behavior", "rude customer"],
    "ChoosingBeggars":       ["negotiation disagreement", "money exchange", "entitled person"],
    "offmychest":            ["person crying emotional", "confession dark room", "vulnerable moment"],
    "TrueOffMyChest":        ["person crying emotional", "confession dark room", "vulnerable moment"],
    "raisedbynarcissists":   ["toxic family", "emotional abuse", "person escaping"],
    "BestofRedditorUpdates": ["satisfying resolution", "happy ending", "justice karma"],
}

DEFAULT_QUERIES = ["city life people", "urban lifestyle", "everyday moments"]

# ── Subreddit → Hook text (first 2.5s overlay) ────────────────────────────────

SUBREDDIT_HOOKS: dict[str, list[str]] = {
    "AmItheAsshole":         ["Wait until you hear what they did… 😤", "You won't believe this story 👀", "This will make you angry 😠"],
    "AITAH":                 ["Wait until you hear what they did… 😤", "This person needs to hear the truth 👀", "The audacity… 😤"],
    "AmIOverreacting":       ["Her reaction was totally justified 👀", "Would YOU be upset? 👇", "This would make anyone angry 😤"],
    "tifu":                  ["This guy actually did this 😂", "Biggest fail of the year 💀", "I can't believe this happened 😂"],
    "mildlyinfuriating":     ["This is so infuriating 😤", "Why do people do this?? 😤", "This will annoy you 😠"],
    "facepalm":              ["People never learn 💀", "The stupidity is unreal 🤦", "I have no words 💀"],
    "Unexpected":            ["Nobody saw this coming 😱", "Wait for it… 👀", "The ending will shock you 😱"],
    "relationship_advice":   ["This relationship is a red flag 🚩", "Would you stay? 👀", "They need to hear this 💔"],
    "breakups":              ["This will break your heart 💔", "Sometimes love isn't enough 💔", "The saddest story 😢"],
    "confessions":           ["They finally told the truth… 👀", "This person needed to get this off their chest", "This secret changes everything 😱"],
    "teenagers":             ["Gen Z really said this 💀", "Teens be like… 😂", "This is so real 💀"],
    "college":               ["College life hits different 😂", "Every student can relate 👀", "The college experience 💀"],
    "TwoHotTakes":           ["The internet is divided on this 👀", "Hot take incoming 🔥", "What side are you on? 👇"],
    "pettyrevenge":          ["The most satisfying revenge ever 😤", "They deserved every bit of it 🙌", "Karma works fast 🔥"],
    "maliciouscompliance":   ["Technically not wrong 😂", "Following the rules perfectly 💀", "The most genius move 🧠"],
    "ProRevenge":            ["The ultimate revenge story 🔥", "They went full nuclear 😤", "Justice was served 🙌"],
    "entitledparents":       ["Karen energy is real 😤", "This parent has no limits 😤", "The audacity of some people 👀"],
    "entitledpeople":        ["Some people have no shame 😤", "This person actually said this 😤", "The entitlement is unreal 👀"],
    "ChoosingBeggars":       ["They actually said this 💀", "The audacity… 😤", "Beggars can't be choosers 😂"],
    "offmychest":            ["They finally said it… 💔", "This needed to be said 👀", "Carrying this alone was too much 💔"],
    "TrueOffMyChest":        ["They finally said it… 💔", "This is so heavy 😢", "The truth comes out 👀"],
    "raisedbynarcissists":   ["No child deserves this 😢", "This is not okay 😤", "Finally free 💪"],
    "BestofRedditorUpdates": ["The update nobody expected 😱", "Wait for the ending 👀", "Justice was finally served 🙌"],
}

DEFAULT_HOOKS = ["Wait for the ending 👀", "You won't believe this 😱", "This actually happened 😤"]

# ── Subreddit → Comment question ──────────────────────────────────────────────

SUBREDDIT_QUESTIONS: dict[str, str] = {
    "AmItheAsshole":         "Who was in the wrong? Comment 👇",
    "AITAH":                 "Was this person wrong? Comment 👇",
    "AmIOverreacting":       "Would YOU be upset? Comment 👇",
    "tifu":                  "What would you have done? Comment 👇",
    "mildlyinfuriating":     "Does this annoy you too? Comment 👇",
    "facepalm":              "What's the dumbest thing you've seen? 👇",
    "Unexpected":            "Did you see that coming? Comment 👇",
    "relationship_advice":   "What's your advice? Comment 👇",
    "breakups":              "Have you been through this? Comment 👇",
    "confessions":           "Can you relate? Comment 👇",
    "teenagers":             "Can you relate? Comment 👇",
    "college":               "College students, can you relate? 👇",
    "TwoHotTakes":           "What side are you on? Comment 👇",
    "pettyrevenge":          "Was this revenge justified? Comment 👇",
    "maliciouscompliance":   "Genius or too far? Comment 👇",
    "ProRevenge":            "Was this revenge justified? Comment 👇",
    "entitledparents":       "How would you have reacted? Comment 👇",
    "entitledpeople":        "Have you dealt with someone like this? 👇",
    "ChoosingBeggars":       "How would you have responded? Comment 👇",
    "offmychest":            "Have you felt this way? Comment 👇",
    "TrueOffMyChest":        "Can you relate? Comment 👇",
    "raisedbynarcissists":   "You are not alone. Comment 💙",
    "BestofRedditorUpdates": "Did you expect that ending? Comment 👇",
}

DEFAULT_QUESTION = "What do you think? Comment 👇"

# ── Subreddit → Music mood ────────────────────────────────────────────────────

SUBREDDIT_MOOD: dict[str, str] = {
    "AmItheAsshole":         "drama",
    "AITAH":                 "drama",
    "AmIOverreacting":       "drama",
    "tifu":                  "funny",
    "mildlyinfuriating":     "drama",
    "facepalm":              "funny",
    "Unexpected":            "suspense",
    "relationship_advice":   "sad",
    "breakups":              "sad",
    "confessions":           "sad",
    "teenagers":             "funny",
    "college":               "funny",
    "TwoHotTakes":           "drama",
    "pettyrevenge":          "suspense",
    "maliciouscompliance":   "funny",
    "ProRevenge":            "suspense",
    "entitledparents":       "drama",
    "entitledpeople":        "drama",
    "ChoosingBeggars":       "funny",
    "offmychest":            "sad",
    "TrueOffMyChest":        "sad",
    "raisedbynarcissists":   "sad",
    "BestofRedditorUpdates": "suspense",
}


def _is_valid_video(path: Path) -> bool:
    try:
        if path.stat().st_size < 500_000:
            path.unlink(missing_ok=True)
            return False
        import subprocess
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def _fetch_pexels_videos(subreddit: str, api_key: str, count: int = 3) -> list[str]:
    """Fetch Pexels videos matching the subreddit topic. Returns list of local paths."""
    queries = SUBREDDIT_QUERIES.get(subreddit, DEFAULT_QUERIES)
    query   = random.choice(queries)
    slug    = f"reddit_{query.replace(' ', '_')}"

    # Check cache first
    cached = [p for p in sorted(CACHE_DIR.glob(f"{slug}_*.mp4")) if _is_valid_video(p)]
    if len(cached) >= count:
        random.shuffle(cached)
        return [str(p) for p in cached[:count]]

    try:
        import certifi
        headers = {"Authorization": api_key}
        verify  = certifi.where()

        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers=headers,
            params={"query": query, "per_page": 15, "orientation": "portrait"},
            timeout=15, verify=verify,
        )
        videos = r.json().get("videos", [])
        if not videos:
            # Fallback: no orientation filter
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers=headers,
                params={"query": query, "per_page": 15},
                timeout=15, verify=verify,
            )
            videos = r.json().get("videos", [])

        random.shuffle(videos)
        downloaded = []

        for video in videos:
            if len(downloaded) + len(cached) >= count + 3:
                break
            idx        = len(cached) + len(downloaded) + 1
            cache_file = CACHE_DIR / f"{slug}_{idx:02d}.mp4"
            if cache_file.exists():
                continue

            files = sorted(video["video_files"], key=lambda f: f.get("width", 0), reverse=True)
            url   = next((f["link"] for f in files if f.get("width", 0) >= 1080), None)
            if not url:
                url = files[0]["link"] if files else None
            if not url:
                continue

            try:
                dl = requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pexels.com/"},
                    verify=verify, timeout=60, stream=True,
                )
                dl.raise_for_status()
                with open(str(cache_file), "wb") as f:
                    for chunk in dl.iter_content(1024 * 1024):
                        f.write(chunk)
                if _is_valid_video(cache_file):
                    downloaded.append(cache_file)
                    print(f"   BG downloaded: {cache_file.name}")
                else:
                    cache_file.unlink(missing_ok=True)
            except Exception:
                cache_file.unlink(missing_ok=True)

        all_cached = [p for p in sorted(CACHE_DIR.glob(f"{slug}_*.mp4")) if _is_valid_video(p)]
        random.shuffle(all_cached)
        return [str(p) for p in all_cached[:count]]

    except Exception as e:
        print(f"   Pexels error: {e}")
        return []


# ── Background ────────────────────────────────────────────────────────────────

def _solid_bg(duration: float):
    return ImageClip(np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)).with_duration(duration)


def _make_background(video_path: str | None, duration: float):
    if video_path:
        try:
            clip = VideoFileClip(video_path)
            # Strip audio — background must never contribute sound
            try:
                clip = clip.without_audio()
            except Exception:
                pass
            ratio = WIDTH / HEIGHT
            if clip.w / clip.h > ratio:
                nw   = int(clip.h * ratio)
                clip = clip.cropped(x1=(clip.w - nw) // 2, x2=(clip.w + nw) // 2)
            else:
                nh   = int(clip.w / ratio)
                clip = clip.cropped(y1=(clip.h - nh) // 2, y2=(clip.h + nh) // 2)
            clip = clip.resized((WIDTH, HEIGHT))
            if clip.duration < duration:
                loops = int(duration / clip.duration) + 2
                clip  = concatenate_videoclips([clip] * loops)
            clip = clip.subclipped(0, duration)
            overlay = ColorClip((WIDTH, HEIGHT), color=(0, 0, 0)).with_opacity(0.62).with_duration(duration)
            return CompositeVideoClip([clip, overlay])
        except Exception as e:
            print(f"   Video error: {e}, using black bg")
    return _solid_bg(duration)


def _make_multi_background(video_paths: list[str], duration: float):
    if not video_paths:
        return _solid_bg(duration)
    seg_dur  = duration / len(video_paths)
    segments = [_make_background(p, seg_dur) for p in video_paths]
    return concatenate_videoclips(segments)


# ── Helper ────────────────────────────────────────────────────────────────────

def _wrap(text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        probe = (cur + " " + w).strip()
        if font.getlength(probe) <= max_w:
            cur = probe
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


# ── Header ────────────────────────────────────────────────────────────────────

def _render_header(subreddit: str, title: str) -> np.ndarray:
    """Minimal header: small gray subreddit label + large white title. No card."""
    MAX_W      = WIDTH - 120
    font_sub   = ImageFont.truetype(BOLD, 30)
    font_title = ImageFont.truetype(BOLD, 64)

    while font_title.size > 36 and font_title.getlength(title) > MAX_W * 1.5:
        font_title = ImageFont.truetype(BOLD, font_title.size - 3)

    title_lines = _wrap(title, font_title, MAX_W)
    line_h      = font_title.size + 14
    sub_h       = 36
    gap         = 16
    total_h     = sub_h + gap + len(title_lines) * line_h
    total_w     = WIDTH - 80

    img  = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    sub_text = f"r/{subreddit}"
    sub_tw   = int(font_sub.getlength(sub_text))
    draw.text(
        ((total_w - sub_tw) // 2, 2), sub_text, font=font_sub,
        fill=(155, 155, 155, 210),
        stroke_width=1, stroke_fill=(0, 0, 0, 180),
    )

    ty = sub_h + gap
    for line in title_lines:
        lw = int(font_title.getlength(line))
        tx = (total_w - lw) // 2
        draw.text(
            (tx, ty), line, font=font_title,
            fill=(255, 255, 255, 255),
            stroke_width=3, stroke_fill=(0, 0, 0, 235),
        )
        ty += line_h

    return np.array(img)


# ── Karaoke ───────────────────────────────────────────────────────────────────

def _render_karaoke_frame(
    words: list[str],
    highlight_indices: set[int],
    font_size: int = 92,
    max_width: int = 960,
) -> np.ndarray:
    """No background box. Active word full white+large, others dimmed."""
    font_active   = ImageFont.truetype(BOLD, font_size)
    font_inactive = ImageFont.truetype(BOLD, int(font_size * 0.85))
    space_w       = font_active.getlength(" ")

    lines:    list[list[tuple[int, str]]] = []
    cur_line: list[tuple[int, str]]       = []
    cur_w = 0.0
    for idx, word in enumerate(words):
        w = font_active.getlength(word)
        if cur_line and cur_w + space_w + w > max_width:
            lines.append(cur_line)
            cur_line = [(idx, word)]
            cur_w    = w
        else:
            cur_line.append((idx, word))
            cur_w += (space_w if cur_line else 0) + w
    if cur_line:
        lines.append(cur_line)

    line_h  = font_size + 20
    total_h = len(lines) * line_h + 20
    total_w = max_width + 60

    img  = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for li, line_words in enumerate(lines):
        line_text_w = sum(font_active.getlength(w) for _, w in line_words) + space_w * (len(line_words) - 1)
        x = (total_w - line_text_w) / 2
        y = li * line_h + 10

        for idx, word in line_words:
            if idx in highlight_indices:
                draw.text(
                    (x, y), word, font=font_active,
                    fill=(255, 255, 255, 255),
                    stroke_width=3, stroke_fill=(0, 0, 0, 255),
                )
                x += font_active.getlength(word) + space_w
            else:
                draw.text(
                    (x, y + int(font_size * 0.07)),
                    word, font=font_inactive,
                    fill=(200, 200, 200, 130),
                    stroke_width=2, stroke_fill=(0, 0, 0, 200),
                )
                x += font_active.getlength(word) + space_w

    return np.array(img)


def _make_karaoke_clips(
    word_timings: list[dict],
    total_duration: float,
    group_size: int = 4,
) -> list:
    n = len(word_timings)
    if n == 0:
        return []

    events: list[tuple[float, float, tuple, int]] = []
    for i, wt in enumerate(word_timings):
        g0          = (i // group_size) * group_size
        g1          = min(g0 + group_size, n)
        group_words = tuple(word_timings[j]["word"] for j in range(g0, g1))
        highlight   = i - g0
        t_start     = wt["start"]
        t_end       = min(
            word_timings[i + 1]["start"] if i + 1 < n else wt["end"] + 0.3,
            total_duration,
        )
        if t_end > t_start:
            events.append((t_start, t_end, group_words, highlight))

    if not events:
        return []

    frame_cache: dict[tuple, np.ndarray] = {}
    for _, _, group_words, highlight in events:
        key = (group_words, highlight)
        if key not in frame_cache:
            frame_cache[key] = _render_karaoke_frame(list(group_words), {highlight})

    first_frame = next(iter(frame_cache.values()))
    clip_h, clip_w = first_frame.shape[:2]
    pos_x  = (WIDTH  - clip_w) // 2
    pos_y  = int(HEIGHT * 0.63) - clip_h // 2
    empty  = np.zeros_like(first_frame)

    def make_frame(t: float) -> np.ndarray:
        for t_start, t_end, group_words, highlight in events:
            if t_start <= t < t_end:
                return frame_cache[(group_words, highlight)]
        return empty

    return [VideoClip(make_frame, duration=total_duration).with_position((pos_x, pos_y))]


# ── Watermark ─────────────────────────────────────────────────────────────────

def _render_watermark() -> np.ndarray:
    handle = os.environ.get("BOT_HANDLE", "@redditstories")
    font   = ImageFont.truetype(BOLD, 24)
    tw     = int(font.getlength(handle))
    th     = 32
    img    = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(img)
    draw.text(
        (0, 4), handle, font=font,
        fill=(255, 255, 255, 100),
        stroke_width=1, stroke_fill=(0, 0, 0, 170),
    )
    return np.array(img)


# ── Progress bar ──────────────────────────────────────────────────────────────

def _make_progress_bar(total_dur: float):
    BAR_H = 2
    white = np.array([255, 255, 255], dtype=np.uint8)

    def make_frame(t: float) -> np.ndarray:
        progress = min(t / max(total_dur, 0.001), 1.0)
        bar_w    = max(1, int(WIDTH * progress))
        frame    = np.zeros((BAR_H, WIDTH, 3), dtype=np.uint8)
        frame[:, :bar_w] = white
        return frame

    return VideoClip(make_frame, duration=total_dur).with_position((0, HEIGHT - BAR_H))


# ── Music ─────────────────────────────────────────────────────────────────────

def _render_hook_frame(text: str) -> np.ndarray:
    """Big centered hook text with dark semi-transparent background box."""
    font_size = 62
    font = ImageFont.truetype(BOLD, font_size)
    max_w = WIDTH - 80
    lines = _wrap(text, font, max_w)
    line_h = font_size + 16
    pad_x, pad_y = 40, 28
    total_w = WIDTH
    total_h = len(lines) * line_h + pad_y * 2

    img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    # dark box
    box = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 185))
    img.paste(box, (0, 0))
    draw = ImageDraw.Draw(img)

    for i, line in enumerate(lines):
        lw = int(font.getlength(line))
        x = (total_w - lw) // 2
        y = pad_y + i * line_h
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255),
                  stroke_width=3, stroke_fill=(0, 0, 0, 255))
    return np.array(img)


def _render_comment_cta_frame(question: str) -> np.ndarray:
    """Comment-bait question shown at the end of the video."""
    font_size = 54
    font = ImageFont.truetype(BOLD, font_size)
    max_w = WIDTH - 80
    lines = _wrap(question, font, max_w)
    line_h = font_size + 14
    pad_x, pad_y = 40, 24
    total_w = WIDTH
    total_h = len(lines) * line_h + pad_y * 2

    img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    box = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 170))
    img.paste(box, (0, 0))
    draw = ImageDraw.Draw(img)

    for i, line in enumerate(lines):
        lw = int(font.getlength(line))
        x = (total_w - lw) // 2
        y = pad_y + i * line_h
        draw.text((x, y), line, font=font, fill=(255, 230, 0, 255),
                  stroke_width=3, stroke_fill=(0, 0, 0, 255))
    return np.array(img)


def _mix_background_music(speech: AudioFileClip, duration: float, mood: str = "") -> AudioFileClip:
    # Try mood subfolder first, then root music dir
    mood_dir = MUSIC_DIR / mood if mood else None
    tracks = []
    if mood_dir and mood_dir.exists():
        tracks = (list(mood_dir.glob("*.mp3")) + list(mood_dir.glob("*.wav"))
                  + list(mood_dir.glob("*.m4a")) + list(mood_dir.glob("*.ogg")))
    if not tracks:
        tracks = (list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))
                  + list(MUSIC_DIR.glob("*.m4a")) + list(MUSIC_DIR.glob("*.ogg")))
    if not tracks:
        return speech
    try:
        track_path = random.choice(tracks)
        print(f"   Musik [{mood or 'random'}]: {track_path.name}")
        music = AudioFileClip(str(track_path))
        music = music.with_effects([afx.AudioLoop(duration=duration)])
        music = music.with_effects([
            afx.MultiplyVolume(0.10),
            afx.AudioFadeIn(1.0),
            afx.AudioFadeOut(1.5),
        ])
        return CompositeAudioClip([speech, music])
    except Exception as e:
        print(f"   Musik-Fehler: {e}")
        return speech


# ── Main ──────────────────────────────────────────────────────────────────────

def create_video(
    subreddit: str,
    title: str,
    story: str,
    audio_path: str,
    output_path: str,
    word_timings: list[dict] | None = None,
    gradient_index: int = 0,
) -> str:
    audio     = AudioFileClip(audio_path)
    total_dur = audio.duration + 0.5

    # Derive hook, comment question and mood from subreddit
    hook_text       = random.choice(SUBREDDIT_HOOKS.get(subreddit, DEFAULT_HOOKS))
    comment_question = SUBREDDIT_QUESTIONS.get(subreddit, DEFAULT_QUESTION)
    mood             = SUBREDDIT_MOOD.get(subreddit, "")

    # Fetch topic-relevant Pexels videos
    pexels_key  = os.environ.get("PEXELS_API_KEY", "").strip()
    video_paths = []
    if pexels_key:
        print(f"   Fetching Pexels BG for r/{subreddit}...")
        video_paths = _fetch_pexels_videos(subreddit, pexels_key, count=4)
        if video_paths:
            print(f"   → {len(video_paths)} BG video(s) loaded")
        else:
            print("   → No Pexels BG found, using black")

    background = _make_multi_background(video_paths, total_dur)
    clips      = [background]

    # ── Hook overlay: first 2.5 seconds ──────────────────────────────────────
    hook_dur = min(2.5, total_dur * 0.15)
    hook_img = _render_hook_frame(hook_text)
    hook_h   = hook_img.shape[0]
    clips.append(
        ImageClip(hook_img)
        .with_start(0)
        .with_duration(hook_dur)
        .with_position(("center", HEIGHT // 2 - hook_h // 2))
        .with_effects([vfx.FadeIn(0.2), vfx.FadeOut(0.3)])
    )

    # Minimal header (fades in after hook)
    header_img = _render_header(subreddit, title)
    clips.append(
        ImageClip(header_img)
        .with_duration(total_dur)
        .with_position(("center", 100))
        .with_effects([vfx.FadeIn(0.3)])
    )

    # Karaoke — no box
    if word_timings:
        clips.extend(_make_karaoke_clips(word_timings, total_dur, group_size=4))

    # ── Comment-bait question: last 3 seconds ─────────────────────────────────
    cta_dur   = min(3.0, total_dur * 0.2)
    cta_start = max(0, total_dur - cta_dur)
    cta_img   = _render_comment_cta_frame(comment_question)
    cta_h     = cta_img.shape[0]
    clips.append(
        ImageClip(cta_img)
        .with_start(cta_start)
        .with_duration(cta_dur)
        .with_position(("center", HEIGHT // 2 + 80))
        .with_effects([vfx.FadeIn(0.3)])
    )

    # Watermark — text only
    wm_img     = _render_watermark()
    wm_h, wm_w = wm_img.shape[:2]
    clips.append(
        ImageClip(wm_img)
        .with_duration(total_dur)
        .with_position((WIDTH - wm_w - 28, HEIGHT - wm_h - 80))
        .with_effects([vfx.FadeIn(0.5)])
    )

    # White 2px progress bar
    clips.append(_make_progress_bar(total_dur))

    mixed_audio = _mix_background_music(audio, total_dur, mood=mood)
    video = CompositeVideoClip(clips, size=(WIDTH, HEIGHT)).with_audio(mixed_audio)
    video.write_videofile(
        output_path, fps=30, codec="libx264", audio_codec="aac", logger=None,
        ffmpeg_params=[
            "-preset", "ultrafast", "-crf", "26",
            "-profile:v", "high", "-level", "4.2",
            "-pix_fmt", "yuv420p", "-b:a", "192k", "-threads", "2",
        ],
    )
    audio.close()
    if mixed_audio is not audio:
        try:
            mixed_audio.close()
        except Exception:
            pass
    video.close()
    return output_path
