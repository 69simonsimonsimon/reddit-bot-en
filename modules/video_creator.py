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


def _resolve_font(mac_path: str, linux_candidates: list) -> str:
    if Path(mac_path).exists():
        return mac_path
    for candidate in linux_candidates:
        if Path(candidate).exists():
            return candidate
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
REGULAR = _resolve_font(
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ],
)

_bg_env = os.environ.get("BACKGROUNDS_DIR", "")
CACHE_DIR = Path(_bg_env) if _bg_env else Path(__file__).parent.parent / "assets" / "backgrounds"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MUSIC_DIR = Path(__file__).parent.parent / "assets" / "music"
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

GRADIENTS = [
    ((10, 10, 35),  (30, 20, 80)),
    ((5, 30, 60),   (10, 80, 120)),
    ((20, 5, 40),   (70, 15, 90)),
    ((15, 25, 15),  (25, 70, 30)),
    ((35, 10, 10),  (80, 25, 20)),
]

# Reddit-Orange
REDDIT_ORANGE = (255, 69, 0)


# ── Hintergrund ───────────────────────────────────────────────────────────────

def _gradient_bg(c1, c2) -> np.ndarray:
    img  = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        r = int(c1[0]*(1-t) + c2[0]*t)
        g = int(c1[1]*(1-t) + c2[1]*t)
        b = int(c1[2]*(1-t) + c2[2]*t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))
    return np.array(img)


def _make_background(video_path: str | None, duration: float, gradient_index: int, zoom: bool = False):
    if video_path:
        try:
            clip  = VideoFileClip(video_path)
            ratio = WIDTH / HEIGHT
            if clip.w / clip.h > ratio:
                nw   = int(clip.h * ratio)
                clip = clip.cropped(x1=(clip.w-nw)//2, x2=(clip.w+nw)//2)
            else:
                nh   = int(clip.w / ratio)
                clip = clip.cropped(y1=(clip.h-nh)//2, y2=(clip.h+nh)//2)
            clip = clip.resized((WIDTH, HEIGHT))
            if clip.duration < duration:
                clip = concatenate_videoclips([clip] * (int(duration / clip.duration) + 2))
            clip = clip.subclipped(0, duration)

            if zoom:
                def _zoom_frame(get_frame, t):
                    frame  = get_frame(t)
                    scale  = 1.0 + 0.05 * (t / max(duration, 1))
                    new_h  = int(HEIGHT * scale)
                    new_w  = int(WIDTH  * scale)
                    img    = Image.fromarray(frame).resize((new_w, new_h), Image.BILINEAR)
                    off_x  = (new_w - WIDTH)  // 2
                    off_y  = (new_h - HEIGHT) // 2
                    return np.array(img)[off_y:off_y + HEIGHT, off_x:off_x + WIDTH]
                clip = clip.transform(_zoom_frame)

            overlay = ColorClip((WIDTH, HEIGHT), color=(0, 0, 0)).with_opacity(0.52).with_duration(duration)
            return CompositeVideoClip([clip, overlay])
        except Exception as e:
            print(f"   Video-Fehler: {e}, nutze Farbverlauf")
    idx = gradient_index % len(GRADIENTS)
    return ImageClip(_gradient_bg(*GRADIENTS[idx])).with_duration(duration)


def _get_minecraft_backgrounds(count: int = 3) -> list[str]:
    """Gibt zufällig ausgewählte lokale Minecraft-Parkour-Videos zurück."""
    videos = list(CACHE_DIR.glob("*.mp4"))
    if not videos:
        print("   Keine Minecraft-Videos gefunden — nutze Farbverlauf (run prefetch_backgrounds.py)")
        return []
    random.shuffle(videos)
    return [str(v) for v in videos[:count]]


def _make_multi_background(duration: float, gradient_index: int):
    video_paths = _get_minecraft_backgrounds(count=3)
    if not video_paths:
        idx = gradient_index % len(GRADIENTS)
        return ImageClip(_gradient_bg(*GRADIENTS[idx])).with_duration(duration)
    n        = len(video_paths)
    seg_dur  = duration / n
    segments = [_make_background(p, seg_dur, gradient_index, zoom=True) for p in video_paths]
    return concatenate_videoclips(segments)


# ── Header: Reddit-Stil ───────────────────────────────────────────────────────

def _render_header(subreddit: str, title: str) -> np.ndarray:
    """
    Reddit-Stil Header:
    - Oben: r/subreddit Badge in Reddit-Orange
    - Darunter: Titel in Weiß, fett
    """
    MAX_W       = WIDTH - 100
    badge_text  = f"r/{subreddit}"
    font_badge  = ImageFont.truetype(BOLD, 36)
    font_title  = ImageFont.truetype(BOLD, 58)
    MIN_TITLE   = 34

    # Schriftgröße anpassen
    while int(font_title.getlength(title)) > MAX_W and font_title.size > MIN_TITLE:
        font_title = ImageFont.truetype(BOLD, font_title.size - 3)

    # Titel-Zeilen umbrechen
    def _wrap(text, font, max_w):
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

    title_lines = _wrap(title, font_title, MAX_W)
    line_h      = font_title.size + 12
    title_h     = len(title_lines) * line_h

    # Badge dimensions
    badge_tw  = int(font_badge.getlength(badge_text))
    badge_px  = 24
    badge_py  = 10
    badge_w   = badge_tw + badge_px * 2
    badge_h   = 36 + badge_py * 2

    gap       = 16
    total_w   = min(max(badge_w, max(int(font_title.getlength(l)) for l in title_lines) + 60, 700), WIDTH - 20)
    total_h   = badge_h + gap + title_h + 10

    img  = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Badge zeichnen (Reddit-Orange)
    bx = (total_w - badge_w) // 2
    draw.rounded_rectangle(
        [(bx, 0), (bx + badge_w - 1, badge_h - 1)],
        radius=badge_h // 2,
        fill=(*REDDIT_ORANGE, 230),
    )
    tx = bx + (badge_w - badge_tw) // 2
    ty = (badge_h - 36) // 2
    draw.text((tx + 1, ty + 1), badge_text, font=font_badge, fill=(0, 0, 0, 120))
    draw.text((tx, ty), badge_text, font=font_badge, fill=(255, 255, 255, 255))

    # Titel-Zeilen (weiß mit Schatten)
    ty = badge_h + gap
    for line in title_lines:
        lw = int(font_title.getlength(line))
        tx2 = (total_w - lw) // 2
        draw.text((tx2 + 2, ty + 2), line, font=font_title, fill=(0, 0, 0, 180))
        draw.text((tx2, ty), line, font=font_title, fill=(255, 255, 255, 255))
        ty += line_h

    return np.array(img)


# ── Karaoke ───────────────────────────────────────────────────────────────────

def _render_karaoke_frame(
    words: list[str],
    highlight_indices: set[int],
    font_size: int = 88,
    max_width: int = 940,
) -> np.ndarray:
    font_bold = ImageFont.truetype(BOLD, font_size)
    space_w   = font_bold.getlength(" ")

    lines:    list[list[tuple[int, str]]] = []
    cur_line: list[tuple[int, str]]       = []
    cur_w = 0.0

    for idx, word in enumerate(words):
        w = font_bold.getlength(word)
        if cur_line and cur_w + space_w + w > max_width:
            lines.append(cur_line)
            cur_line = [(idx, word)]
            cur_w    = w
        else:
            cur_line.append((idx, word))
            cur_w += (space_w if cur_line else 0) + w
    if cur_line:
        lines.append(cur_line)

    line_h  = font_size + 16
    total_h = len(lines) * line_h
    total_w = max_width + 80
    pad     = 28

    img  = Image.new("RGBA", (total_w, total_h + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [(0, 0), (total_w - 1, total_h + pad * 2 - 1)],
        radius=24, fill=(0, 0, 0, 170)
    )

    for li, line_words in enumerate(lines):
        line_text_w = sum(font_bold.getlength(w) for _, w in line_words) + space_w * (len(line_words) - 1)
        x = (total_w - line_text_w) / 2
        y = pad + li * line_h
        for idx, word in line_words:
            color = "#FFE600" if idx in highlight_indices else "white"
            draw.text((x + 2, y + 2), word, font=font_bold, fill=(0, 0, 0, 200))
            draw.text((x, y), word, font=font_bold, fill=color)
            x += font_bold.getlength(word) + space_w

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
            total_duration
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
    pos_x = (WIDTH  - clip_w) // 2
    pos_y = int(HEIGHT * 0.62) - clip_h // 2

    empty = np.zeros_like(first_frame)

    def make_frame(t: float) -> np.ndarray:
        for t_start, t_end, group_words, highlight in events:
            if t_start <= t < t_end:
                return frame_cache[(group_words, highlight)]
        return empty

    return [
        VideoClip(make_frame, duration=total_duration, is_mask=False)
        .with_position((pos_x, pos_y))
    ]


# ── Wasserzeichen ─────────────────────────────────────────────────────────────

def _render_watermark() -> np.ndarray:
    handle = os.environ.get("BOT_HANDLE", "@redditstories")
    font   = ImageFont.truetype(BOLD, 26)
    tw     = int(font.getlength(handle)) + 22
    th     = 40
    img    = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(img)
    draw.rounded_rectangle([(0, 0), (tw - 1, th - 1)], radius=8, fill=(0, 0, 0, 120))
    draw.text((11, 9), handle, font=font, fill=(0, 0, 0, 130))
    draw.text((10, 8), handle, font=font, fill=(255, 255, 255, 195))
    return np.array(img)


# ── Fortschrittsleiste ────────────────────────────────────────────────────────

def _make_progress_bar(total_dur: float):
    BAR_H = 5
    color = np.array([255, 69, 0], dtype=np.uint8)  # Reddit-Orange

    def make_frame(t: float) -> np.ndarray:
        progress = min(t / max(total_dur, 0.001), 1.0)
        bar_w    = max(1, int(WIDTH * progress))
        frame    = np.zeros((BAR_H, WIDTH, 3), dtype=np.uint8)
        frame[:, :bar_w] = color
        return frame

    return VideoClip(make_frame, duration=total_dur).with_position((0, HEIGHT - BAR_H - 2))


# ── Hintergrundmusik ──────────────────────────────────────────────────────────

def _mix_background_music(speech: AudioFileClip, duration: float) -> AudioFileClip:
    tracks = (
        list(MUSIC_DIR.glob("*.mp3"))
        + list(MUSIC_DIR.glob("*.wav"))
        + list(MUSIC_DIR.glob("*.m4a"))
        + list(MUSIC_DIR.glob("*.ogg"))
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
        print(f"   Musik-Fehler (übersprungen): {e}")
        return speech


# ── Hook-Overlay (erste 3s) ───────────────────────────────────────────────────

def _render_hook_frame(title: str, subreddit: str) -> np.ndarray:
    """Zeigt den Reddit-Post-Titel dramatisch am Anfang."""
    font_sub  = ImageFont.truetype(BOLD, 44)
    font_txt  = ImageFont.truetype(BOLD, 62)
    MAX_W     = WIDTH - 80

    def _wrap(text, font, max_w):
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

    sub_text  = f"r/{subreddit}"
    sub_tw    = int(font_sub.getlength(sub_text))
    sub_h     = 44 + 20
    title_lines = _wrap(title, font_txt, MAX_W)
    line_h    = 62 + 14
    title_h   = len(title_lines) * line_h
    gap       = 18
    total_h   = sub_h + gap + title_h + 50
    total_w   = WIDTH - 40

    img  = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(0, 0), (total_w - 1, total_h - 1)], radius=28, fill=(0, 0, 0, 190))

    # Subreddit Badge
    badge_w = sub_tw + 40
    badge_h = sub_h - 4
    bx      = (total_w - badge_w) // 2
    draw.rounded_rectangle([(bx, 8), (bx + badge_w - 1, 8 + badge_h - 1)],
                            radius=badge_h // 2, fill=(*REDDIT_ORANGE, 220))
    draw.text(((total_w - sub_tw) // 2 + 1, 16), sub_text, font=font_sub, fill=(0, 0, 0, 120))
    draw.text(((total_w - sub_tw) // 2, 15), sub_text, font=font_sub, fill=(255, 255, 255, 255))

    # Titel
    ty = sub_h + gap
    for line in title_lines:
        lw = int(font_txt.getlength(line))
        tx = (total_w - lw) // 2
        draw.text((tx + 2, ty + 2), line, font=font_txt, fill=(0, 0, 0, 180))
        draw.text((tx, ty), line, font=font_txt, fill=(255, 255, 255, 255))
        ty += line_h

    return np.array(img)


def _make_hook_clip(title: str, subreddit: str, total_dur: float, hook_dur: float = 3.5):
    frame = _render_hook_frame(title, subreddit)
    fh, fw = frame.shape[:2]
    pos_x  = (WIDTH  - fw) // 2
    pos_y  = int(HEIGHT * 0.26) - fh // 2

    return (
        ImageClip(frame)
        .with_duration(hook_dur)
        .with_position((pos_x, pos_y))
        .with_effects([vfx.FadeIn(0.2), vfx.FadeOut(0.5)])
    )


# ── Haupt-Funktion ────────────────────────────────────────────────────────────

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

    # Reddit-Header oben
    header_img = _render_header(subreddit, title)
    clips.append(
        ImageClip(header_img)
        .with_duration(total_dur)
        .with_position(("center", 80))
        .with_effects([vfx.FadeIn(0.4)])
    )

    # Hook (erste 3.5s)
    clips.append(_make_hook_clip(title, subreddit, total_dur))

    # Karaoke-Untertitel
    if word_timings:
        clips.extend(_make_karaoke_clips(word_timings, total_dur, group_size=4))

    # Wasserzeichen
    wm_img  = _render_watermark()
    wm_h, wm_w = wm_img.shape[:2]
    clips.append(
        ImageClip(wm_img)
        .with_duration(total_dur)
        .with_position((WIDTH - wm_w - 24, HEIGHT - wm_h - 110))
        .with_effects([vfx.FadeIn(0.6)])
    )

    # Fortschrittsleiste (Reddit-Orange)
    clips.append(_make_progress_bar(total_dur))

    mixed_audio = _mix_background_music(audio, total_dur)

    video = CompositeVideoClip(clips, size=(WIDTH, HEIGHT)).with_audio(mixed_audio)
    video.write_videofile(
        output_path, fps=30, codec="libx264", audio_codec="aac", logger=None,
        ffmpeg_params=[
            "-preset", "ultrafast",   # was: medium — ultrafast uses ~60% less RAM (no B-frame lookahead)
            "-crf", "26",             # was: 22 — slightly smaller file, TikTok re-encodes anyway
            "-profile:v", "high",
            "-level", "4.2",
            "-pix_fmt", "yuv420p",
            "-b:a", "192k",
            "-threads", "2",          # was: 0 (all cores) — limits parallel thread buffers
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
