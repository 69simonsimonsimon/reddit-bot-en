import os
import random
from pathlib import Path

import numpy as np
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


# ── Background ────────────────────────────────────────────────────────────────

def _solid_bg(duration: float):
    return ImageClip(np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)).with_duration(duration)


def _make_background(video_path: str | None, duration: float, zoom: bool = False):
    if video_path:
        try:
            clip  = VideoFileClip(video_path)
            ratio = WIDTH / HEIGHT
            if clip.w / clip.h > ratio:
                nw   = int(clip.h * ratio)
                clip = clip.cropped(x1=(clip.w - nw) // 2, x2=(clip.w + nw) // 2)
            else:
                nh   = int(clip.w / ratio)
                clip = clip.cropped(y1=(clip.h - nh) // 2, y2=(clip.h + nh) // 2)
            clip = clip.resized((WIDTH, HEIGHT))
            if clip.duration < duration:
                clip = concatenate_videoclips([clip] * (int(duration / clip.duration) + 2))
            clip = clip.subclipped(0, duration)
            if zoom:
                def _zoom_frame(get_frame, t):
                    frame = get_frame(t)
                    scale = 1.0 + 0.05 * (t / max(duration, 1))
                    new_h = int(HEIGHT * scale)
                    new_w = int(WIDTH  * scale)
                    img   = Image.fromarray(frame).resize((new_w, new_h), Image.BILINEAR)
                    off_x = (new_w - WIDTH)  // 2
                    off_y = (new_h - HEIGHT) // 2
                    return np.array(img)[off_y:off_y + HEIGHT, off_x:off_x + WIDTH]
                clip = clip.transform(_zoom_frame)
            # Darker overlay — compensates for no text boxes
            overlay = ColorClip((WIDTH, HEIGHT), color=(0, 0, 0)).with_opacity(0.65).with_duration(duration)
            return CompositeVideoClip([clip, overlay])
        except Exception as e:
            print(f"   Video error: {e}, using black bg")
    return _solid_bg(duration)


def _get_backgrounds(count: int = 3) -> list[str]:
    videos = list(CACHE_DIR.glob("*.mp4"))
    if not videos:
        print("   Keine Minecraft-Videos gefunden — nutze Farbverlauf (run prefetch_backgrounds.py)")
        return []
    random.shuffle(videos)
    return [str(v) for v in videos[:count]]


def _make_multi_background(duration: float, gradient_index: int = 0):
    paths = _get_backgrounds(count=3)
    if not paths:
        return _solid_bg(duration)
    seg_dur  = duration / len(paths)
    segments = [_make_background(p, seg_dur, zoom=True) for p in paths]
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

    # Auto-shrink title font if needed
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

    # Subreddit label — small, gray
    sub_text = f"r/{subreddit}"
    sub_tw   = int(font_sub.getlength(sub_text))
    draw.text(
        ((total_w - sub_tw) // 2, 2), sub_text, font=font_sub,
        fill=(155, 155, 155, 210),
        stroke_width=1, stroke_fill=(0, 0, 0, 180),
    )

    # Title — large white with stroke
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
    """2px white bar at very bottom."""
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

def _mix_background_music(speech: AudioFileClip, duration: float) -> AudioFileClip:
    tracks = (
        list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))
        + list(MUSIC_DIR.glob("*.m4a")) + list(MUSIC_DIR.glob("*.ogg"))
    )
    if not tracks:
        return speech
    try:
        track_path = random.choice(tracks)
        print(f"   Musik: {track_path.name}")
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

    background = _make_multi_background(total_dur, gradient_index)
    clips      = [background]

    # Minimal header
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

    mixed_audio = _mix_background_music(audio, total_dur)
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
