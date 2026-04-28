"""
Reddit Story Bot EN — Dashboard
Start with: python dashboard/app.py
"""

import json
import logging
import os
import random
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "modules"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

IS_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"))

_log_base = Path(os.environ.get("OUTPUT_DIR", str(ROOT / "output")))
LOG_DIR   = _log_base / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)
LOG_FILE  = LOG_DIR / "bot.log"

_handler = RotatingFileHandler(str(LOG_FILE), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
logger = logging.getLogger("reddit-en")
logger.setLevel(logging.INFO)
logger.addHandler(_handler)
logger.addHandler(logging.StreamHandler())


def _tg_credentials():
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return token, chat_id

def notify(title: str, message: str):
    """Send Telegram notification. Falls back silently if env vars not set."""
    try:
        import urllib.request as _ur, json as _j
        _token, _chat_id = _tg_credentials()
        if not _token or not _chat_id:
            return
        _body = _j.dumps({
            "chat_id": _chat_id,
            "text": f"<b>{title}</b>\n{message}",
            "parse_mode": "HTML",
        }).encode()
        _req = _ur.Request(
            f"https://api.telegram.org/bot{_token}/sendMessage",
            data=_body, headers={"Content-Type": "application/json"},
        )
        _ur.urlopen(_req, timeout=10)
    except Exception:
        pass

def notify_photo(image_path: str, caption: str):
    """Sends a thumbnail photo via Telegram for manual YouTube upload."""
    try:
        import requests as _req
        _token, _chat_id = _tg_credentials()
        if not _token or not _chat_id:
            return
        from pathlib import Path as _P
        p = _P(image_path)
        if not p.exists():
            return
        with open(p, "rb") as f:
            _req.post(
                f"https://api.telegram.org/bot{_token}/sendPhoto",
                data={"chat_id": _chat_id, "caption": caption[:1024]},
                files={"photo": (p.name, f, "image/jpeg")},
                timeout=30,
            )
    except Exception:
        pass


try:
    from story_fetcher import fetch_story, SUBREDDITS
    from tts import text_to_speech
    from video_creator import create_video
    from tiktok_uploader_zernio import upload_video_browser, DuplicateContentError
except Exception as _import_err:
    logger.error(f"Import-Fehler beim Start: {_import_err}")
    raise

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(ROOT / "output")))
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

_CTAS = [
    "Who was wrong here? Comment below 👇",
    "Would you have done the same? Drop a 👍 or ❌",
    "Follow for more wild Reddit stories 🔥",
    "What would YOU have done? 💬",
    "Daily drama — follow so you don't miss it ✨",
    "Drop your verdict in the comments 😮",
    "Red flag or overreaction? You decide 👇",
    "Tag someone who needs to see this 😳",
    "This one still has me speechless... Follow for more 🤯",
    "NGL this one got me 😤 Follow for daily stories",
    "Was this justified? Let me know 👇",
    "The comments on this one are WILD 💬 Follow to discuss",
]

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
jobs:       dict[str, dict] = {}
uploads:    dict[str, str]  = {}   # filename → "running" | "done" | "error" | "duplicate"
batch_jobs: dict[str, dict] = {}


@app.on_event("startup")
async def startup_recovery():
    """Upload videos that were generated but not uploaded due to a service restart.
    Also detects slots whose generation was interrupted mid-flight and re-triggers them."""
    def _do_recovery():
        time.sleep(15)
        now = time.time()

        # ── Phase 1: Upload unfertige Videos ─────────────────────────────────
        for mp4 in sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True):
            age_h = (now - mp4.stat().st_mtime) / 3600
            if age_h > 6:
                break
            if age_h < (2 / 60):  # Weniger als 2 Min alt → wird gerade generiert, überspringen
                continue
            meta_file = mp4.with_suffix(".json")
            if not meta_file.exists():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if meta.get("uploaded"):
                    continue
                caption  = meta.get("caption", "")
                filename = mp4.name
                if filename in uploads:
                    continue
                logger.info(f"Startup-Recovery: nicht hochgeladenes Video gefunden: {filename} ({age_h:.1f}h alt)")
                uploads[filename] = "running"
                _run_upload(filename, str(mp4), caption)
            except Exception as e:
                logger.warning(f"Startup-Recovery Fehler für {mp4.name}: {e}")

        # ── Phase 2: Unterbrochene Slot-Generierung erkennen & nachholen ─────
        try:
            _now_dt    = datetime.now()
            _today     = _now_dt.strftime("%Y-%m-%d")
            _now_epoch = time.time()
            _fired     = _load_fired_keys()
            _cfg       = _load_schedule_cfg()
            _SKIP_JSON = {"used_facts.json", "fired_keys.json", "schedule.json", "used_posts.json"}

            if _cfg.get("enabled"):
                for _slot in _cfg.get("slots", []):
                    _slot_time = _slot.get("time", "")
                    if not _slot_time or ":" not in _slot_time:
                        continue
                    _key = f"{_today}_{_slot_time}"
                    if _key not in _fired:
                        continue

                    _t_h, _t_m = int(_slot_time.split(":")[0]), int(_slot_time.split(":")[1])
                    _slot_epoch = _now_dt.replace(
                        hour=_t_h, minute=_t_m, second=0, microsecond=0
                    ).timestamp()

                    if _now_epoch - _slot_epoch > 30 * 60 or _slot_epoch > _now_epoch:
                        continue

                    _post_mp4  = [f for f in OUTPUT_DIR.glob("*.mp4")  if f.stat().st_mtime >= _slot_epoch - 30]
                    _post_json = [f for f in OUTPUT_DIR.glob("*.json")
                                  if f.name not in _SKIP_JSON and f.stat().st_mtime >= _slot_epoch - 30]
                    if _post_mp4 or _post_json:
                        continue

                    logger.info(f"Startup-Recovery: Slot {_slot_time} wurde mid-generation unterbrochen — starte Neugenerierung")
                    _job_id = str(uuid.uuid4())[:8]
                    jobs[_job_id] = {"status": "running", "progress": 0, "message": "Startet (Slot-Recovery)…", "video": None}
                    threading.Thread(target=_run_scheduled_single, args=(_job_id, _slot), daemon=True).start()
                    break
        except Exception as _e:
            logger.warning(f"Startup-Recovery Slot-Check Fehler: {_e}")

    threading.Thread(target=_do_recovery, daemon=True).start()


# ── Healthcheck ───────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Video-Liste ───────────────────────────────────────────────────────────────

@app.get("/api/videos")
def list_videos():
    videos = []
    for mp4 in sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True):
        meta_file = mp4.with_suffix(".json")
        meta: dict = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        videos.append({
            "filename": mp4.name,
            "size_mb":  round(mp4.stat().st_size / 1_048_576, 1),
            "created":  datetime.fromtimestamp(mp4.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
            "title":    meta.get("title", mp4.stem),
            "topic":    meta.get("subreddit", meta.get("topic", "")),
            "caption":  meta.get("caption", ""),
            "uploaded": meta.get("uploaded", False),
        })
    return videos


# ── Video generieren ──────────────────────────────────────────────────────────

@app.post("/api/generate")
def start_generate(topic: str = "", long: bool = False):
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "running", "progress": 0, "message": "Startet...", "video": None}
    t = threading.Thread(target=_run_generation, args=(job_id, topic or None), daemon=True)
    t.start()
    return {"job_id": job_id}


def _free_disk_mb() -> float:
    import shutil
    check_path = str(OUTPUT_DIR) if OUTPUT_DIR.exists() else "/"
    return shutil.disk_usage(check_path).free / 1_048_576


def _cleanup_old_videos(keep: int = 10):
    """Löscht älteste hochgeladene Videos wenn Output-Verzeichnis zu voll wird."""
    try:
        uploaded = sorted(
            [f for f in OUTPUT_DIR.glob("*.mp4")
             if f.with_suffix(".json").exists() and
             json.loads(f.with_suffix(".json").read_text()).get("uploaded", False)],
            key=lambda f: f.stat().st_mtime
        )
        for f in uploaded[:-keep] if len(uploaded) > keep else []:
            f.unlink(missing_ok=True)
            f.with_suffix(".json").unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"Cleanup fehlgeschlagen: {e}")


def _run_generation(job_id: str, subreddit: str | None):
    def upd(msg: str, pct: int):
        jobs[job_id]["message"]  = msg
        jobs[job_id]["progress"] = pct

    try:
        if _free_disk_mb() < 400:
            _cleanup_old_videos()

        stamp      = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_path = OUTPUT_DIR / f"audio_{stamp}.mp3"
        video_path = OUTPUT_DIR / f"video_{stamp}.mp4"

        upd("Hole Reddit-Geschichte ...", 10)
        story_data = fetch_story(subreddit_override=subreddit)

        upd("Erstelle Voiceover ...", 30)
        tts_text = f"{story_data['title']}. {story_data['story']}"
        words    = tts_text.split()
        if len(words) > 360:
            tts_text = " ".join(words[:360])
            for end_char in [". ", "! ", "? "]:
                idx = tts_text.rfind(end_char)
                if idx > 50:
                    tts_text = tts_text[:idx + 1]
                    break
        logger.info(f"TTS-Text: {len(tts_text.split())} Wörter")
        _, word_timings = text_to_speech(tts_text, str(audio_path))

        upd("Erstelle Video ...", 55)
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

        description  = story_data.get("description", story_data["title"])
        cta          = random.choice(_CTAS)
        hashtag_str  = " ".join(story_data["hashtags"])
        has_part2    = bool(story_data.get("part2"))

        if has_part2:
            full_caption = description + "\n🧵 Part 2 coming soon — follow so you don't miss it! 👀\n" + cta + "\n" + hashtag_str
        else:
            full_caption = description + "\n" + cta + "\n" + hashtag_str

        # Generate thumbnail
        upd("Erstelle Thumbnail ...", 68)
        thumb_path = ""
        try:
            from thumbnail_creator import create_thumbnail as _make_thumb
            thumbs = _make_thumb(str(video_path), story_data["title"], str(OUTPUT_DIR), subreddit=story_data["subreddit"])
            thumb_path = Path(thumbs.get("thumbnail", "")).name
        except Exception as _te:
            logger.warning(f"Thumbnail generation failed: {_te}")

        meta = {
            "title":     story_data["title"],
            "subreddit": story_data["subreddit"],
            "caption":   full_caption,
            "uploaded":  False,
            "thumbnail": thumb_path,
        }
        video_path.with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if has_part2:
            upd("Part 1 done — generating Part 2...", 70)
            try:
                stamp2      = datetime.now().strftime("%Y%m%d_%H%M%S") + "_p2"
                audio2_path = OUTPUT_DIR / f"audio_{stamp2}.mp3"
                video2_path = OUTPUT_DIR / f"video_{stamp2}.mp4"

                tts2_text = f"{story_data['title']} - Part 2. {story_data['part2']}"
                _, word_timings2 = text_to_speech(tts2_text, str(audio2_path))
                create_video(
                    subreddit=story_data["subreddit"],
                    title=f"{story_data['title']} - Part 2",
                    story=story_data["part2"],
                    audio_path=str(audio2_path),
                    output_path=str(video2_path),
                    word_timings=word_timings2,
                    gradient_index=random.randint(0, 4),
                )
                audio2_path.unlink(missing_ok=True)

                # Thumbnail for Part 2
                thumb2_path = ""
                try:
                    from thumbnail_creator import create_thumbnail as _make_thumb2
                    thumbs2 = _make_thumb2(str(video2_path), f"{story_data['title']} - Part 2", str(OUTPUT_DIR), subreddit=story_data["subreddit"])
                    thumb2_path = Path(thumbs2.get("thumbnail", "")).name
                except Exception as _te2:
                    logger.warning(f"Thumbnail Part 2 failed: {_te2}")

                cta2     = random.choice(_CTAS)
                caption2 = f"Part 2 of: {description}\n🎬 Here's how it ended...\n{cta2}\n{hashtag_str}"
                meta2 = {
                    "title":     f"{story_data['title']} - Part 2",
                    "subreddit": story_data["subreddit"],
                    "caption":   caption2,
                    "uploaded":  False,
                    "is_part2":  True,
                    "thumbnail": thumb2_path,
                }
                video2_path.with_suffix(".json").write_text(
                    json.dumps(meta2, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                logger.info(f"Part 2 created: {video2_path.name}")
                notify("Reddit Bot EN", f"Part 1+2 ready: {story_data['title'][:45]}")
            except Exception as e2:
                logger.error(f"Part 2 generation failed: {e2}")
                notify("Reddit Bot EN", f"⚠️ Part 2 failed: {str(e2)[:60]}")
        else:
            notify("Reddit Bot EN", f"Video ready: {story_data['title'][:50]}")

        upd(f"Done: {video_path.name}", 100)
        jobs[job_id]["status"] = "done"
        jobs[job_id]["video"]  = video_path.name
        logger.info(f"Video created: {video_path.name} (r/{story_data['subreddit']})")

    except Exception as e:
        jobs[job_id]["status"]  = "error"
        jobs[job_id]["message"] = str(e)
        logger.error(f"Video-Generierung fehlgeschlagen: {e}", exc_info=True)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return jobs.get(job_id, {"status": "not_found"})


# ── Batch-Generierung ─────────────────────────────────────────────────────────

@app.post("/api/generate-batch")
def start_batch(count: int = 3, topic: str = "", long: bool = False):
    batch_id = str(uuid.uuid4())[:8]
    batch_jobs[batch_id] = {
        "status": "running", "total": count, "done": 0,
        "current": 0, "current_job": None, "videos": [], "message": "Startet...",
    }
    t = threading.Thread(target=_run_batch, args=(batch_id, count, topic or None), daemon=True)
    t.start()
    return {"batch_id": batch_id}


def _run_batch(batch_id: str, count: int, subreddit: str | None):
    for i in range(count):
        job_id = str(uuid.uuid4())[:8]
        jobs[job_id] = {"status": "running", "progress": 0, "message": "Startet...", "video": None}
        batch_jobs[batch_id]["current_job"] = job_id
        batch_jobs[batch_id]["current"]     = i + 1
        batch_jobs[batch_id]["message"]     = f"Video {i+1} von {count}..."
        _run_generation(job_id, subreddit)
        if jobs[job_id].get("video"):
            batch_jobs[batch_id]["videos"].append(jobs[job_id]["video"])
        batch_jobs[batch_id]["done"] = i + 1

    total = len(batch_jobs[batch_id]["videos"])
    batch_jobs[batch_id]["status"]  = "done"
    batch_jobs[batch_id]["message"] = f"Fertig! {total} Video{'s' if total != 1 else ''} erstellt."


@app.get("/api/batch/{batch_id}")
def get_batch(batch_id: str):
    b = batch_jobs.get(batch_id)
    if not b:
        return {"status": "not_found"}
    result = dict(b)
    if b.get("current_job"):
        j = jobs.get(b["current_job"], {})
        result["job_progress"] = j.get("progress", 0)
        result["job_message"]  = j.get("message", "")
    return result


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/api/upload/{filename}")
def start_upload(filename: str, custom_caption: str = ""):
    video_path = OUTPUT_DIR / filename
    if not video_path.exists():
        return {"error": "Datei nicht gefunden"}
    meta_file = video_path.with_suffix(".json")
    caption   = custom_caption
    if not caption and meta_file.exists():
        try:
            caption = json.loads(meta_file.read_text(encoding="utf-8")).get("caption", "")
        except Exception:
            pass
    if custom_caption and meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            meta["caption"] = custom_caption
            meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    uploads[filename] = "running"
    t = threading.Thread(target=_run_upload, args=(filename, str(video_path), caption), daemon=True)
    t.start()
    return {"status": "started"}


def _run_upload(filename: str, video_path: str, caption: str):
    meta_file  = Path(video_path).with_suffix(".json")
    video_size = Path(video_path).stat().st_size if Path(video_path).exists() else 0
    size_mb    = round(video_size / 1_048_576, 1)
    title      = filename
    thumb_path = ""
    try:
        if meta_file.exists():
            _m = json.loads(meta_file.read_text(encoding="utf-8"))
            title       = _m.get("title", filename)
            _thumb_name = _m.get("thumbnail", "")
            if _thumb_name:
                _thumb_full = OUTPUT_DIR / _thumb_name
                if _thumb_full.exists():
                    thumb_path = str(_thumb_full)
    except Exception:
        pass

    if video_size < 500_000:
        logger.error(f"Upload abgebrochen: {filename} ist zu klein ({video_size // 1024} KB)")
        uploads[filename] = "error"
        _append_upload_history(filename, title, "failed", size_mb)
        return

    try:
        if meta_file.exists() and json.loads(meta_file.read_text(encoding="utf-8")).get("uploaded"):
            logger.info(f"Upload übersprungen: {filename} bereits hochgeladen")
            uploads[filename] = "done"
            return
    except Exception:
        pass

    logger.info(f"Upload: {filename}")
    try:
        ok = upload_video_browser(video_path, caption, thumbnail_path=thumb_path)
    except DuplicateContentError as e:
        logger.error(f"   ✗ Duplikat (409) — neues Video wird generiert: {e}")
        uploads[filename] = "duplicate"
        _append_upload_history(filename, title, "duplicate", size_mb)
        return
    except Exception as e:
        logger.error(f"Upload-Fehler: {e}")
        ok = False

    if ok:
        try:
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta["uploaded"] = True
                meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        uploads[filename] = "done"
        _append_upload_history(filename, title, "success", size_mb)
        logger.info(f"Upload erfolgreich: {filename}")
        notify("Reddit Bot EN",f"Video hochgeladen: {Path(video_path).stem[:40]}")
        try:
            Path(video_path).unlink(missing_ok=True)
            Path(video_path).with_suffix(".mp3").unlink(missing_ok=True)
            Path(video_path).with_suffix(".json").unlink(missing_ok=True)
        except Exception:
            pass
    else:
        uploads[filename] = "error"
        _append_upload_history(filename, title, "failed", size_mb)
        logger.error(f"Upload fehlgeschlagen: {filename}")
        notify("Reddit Bot EN",f"Upload fehlgeschlagen: {Path(video_path).stem[:40]}")


@app.get("/api/upload-status/{filename}")
def upload_status(filename: str):
    return {"status": uploads.get(filename, "idle")}


@app.delete("/api/videos/{filename}")
def delete_video(filename: str):
    video_file = OUTPUT_DIR / filename
    meta_file  = video_file.with_suffix(".json")
    if not video_file.exists():
        return {"error": "Datei nicht gefunden"}
    video_file.unlink()
    if meta_file.exists():
        meta_file.unlink()
    uploads.pop(filename, None)
    return {"status": "deleted"}


@app.get("/api/upload-history")
def get_upload_history():
    if not UPLOAD_HISTORY_FILE.exists():
        return []
    try:
        return json.loads(UPLOAD_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


@app.post("/api/mark-uploaded/{filename}")
def mark_uploaded(filename: str):
    meta_file = (OUTPUT_DIR / filename).with_suffix(".json")
    if meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    else:
        meta = {"title": filename.replace(".mp4", ""), "subreddit": "", "caption": "", "uploaded": False}
    meta["uploaded"] = True
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    uploads[filename] = "done"
    return {"status": "ok"}


@app.get("/api/config")
def get_config():
    return {"is_railway": IS_RAILWAY, "output_dir": str(OUTPUT_DIR)}


# ── Upload-Warteschlange ──────────────────────────────────────────────────────

QUEUE_FILE          = OUTPUT_DIR / "upload_queue.json"
SCHEDULE_FILE       = OUTPUT_DIR / "schedule.json"
UPLOAD_HISTORY_FILE = OUTPUT_DIR / "upload_history.json"


def _append_upload_history(filename: str, title: str, status: str, size_mb: float):
    history = []
    if UPLOAD_HISTORY_FILE.exists():
        try:
            history = json.loads(UPLOAD_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    history.append({
        "filename": filename,
        "title":    title or filename,
        "time":     datetime.now().strftime("%d.%m. %H:%M"),
        "status":   status,
        "size_mb":  size_mb,
    })
    UPLOAD_HISTORY_FILE.write_text(
        json.dumps(history[-20:], ensure_ascii=False, indent=2), encoding="utf-8"
    )

upload_queue: list[dict] = []
_queue_lock = threading.Lock()


def _load_queue():
    global upload_queue
    if QUEUE_FILE.exists():
        try:
            upload_queue = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            upload_queue = []


def _save_queue():
    QUEUE_FILE.write_text(json.dumps(upload_queue, ensure_ascii=False, indent=2), encoding="utf-8")


def _queue_processor():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            with _queue_lock:
                for item in upload_queue:
                    if item["status"] == "waiting" and item["scheduled_time"] <= now:
                        item["status"] = "uploading"
                        vp = str(OUTPUT_DIR / item["filename"])
                        threading.Thread(
                            target=_run_upload,
                            args=(item["filename"], vp, item.get("caption", "")),
                            daemon=True,
                        ).start()
                        logger.info(f"Queue: starte Upload für {item['filename']}")
                _save_queue()
        except Exception as e:
            logger.error(f"Queue-Processor-Fehler: {e}")
        time.sleep(30)


@app.get("/api/queue")
def get_queue():
    return upload_queue


@app.post("/api/queue/add")
def add_to_queue(filename: str, scheduled_time: str, custom_caption: str = ""):
    video_path = OUTPUT_DIR / filename
    if not video_path.exists():
        return {"error": "Datei nicht gefunden"}
    caption = custom_caption
    if not caption:
        meta_file = video_path.with_suffix(".json")
        if meta_file.exists():
            try:
                caption = json.loads(meta_file.read_text(encoding="utf-8")).get("caption", "")
            except Exception:
                pass
    with _queue_lock:
        upload_queue[:] = [q for q in upload_queue if q["filename"] != filename]
        upload_queue.append({
            "filename": filename, "caption": caption,
            "scheduled_time": scheduled_time, "status": "waiting",
        })
        upload_queue.sort(key=lambda x: x["scheduled_time"])
        _save_queue()
    return {"status": "queued"}


@app.delete("/api/queue/{filename}")
def remove_from_queue(filename: str):
    with _queue_lock:
        upload_queue[:] = [q for q in upload_queue if q["filename"] != filename]
        _save_queue()
    return {"status": "removed"}


# ── Auto-Zeitplan ─────────────────────────────────────────────────────────────

class ScheduleSlot(BaseModel):
    time:     str  = "18:00"
    mode:     str  = "new"
    topic:    str  = ""
    filename: str  = ""
    long:     bool = False

class ScheduleConfig(BaseModel):
    enabled:         bool               = False
    recovery_until:  str | None         = None
    recovery_reason: str                = ""
    slots:           list[ScheduleSlot] = [ScheduleSlot()]

DEFAULT_SCHEDULE = {
    "enabled": True,
    "recovery_until": None,
    "recovery_reason": "",
    "slots": [
        {"time": "09:00", "mode": "new", "topic": "", "filename": "", "long": False},
        {"time": "14:00", "mode": "new", "topic": "", "filename": "", "long": False},
        {"time": "19:00", "mode": "new", "topic": "", "filename": "", "long": False},
        {"time": "00:00", "mode": "new", "topic": "", "filename": "", "long": False},
    ],
}
# Note: Live times managed via /api/schedule — defaults only used on first deploy


def _load_schedule_cfg() -> dict:
    if SCHEDULE_FILE.exists():
        try:
            raw = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
            return {**DEFAULT_SCHEDULE, **raw}
        except Exception:
            pass
    return dict(DEFAULT_SCHEDULE)


def _save_schedule_cfg(cfg: dict):
    SCHEDULE_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


FIRED_KEYS_FILE = OUTPUT_DIR / "fired_keys.json"


def _load_fired_keys() -> set:
    try:
        if FIRED_KEYS_FILE.exists():
            return set(json.loads(FIRED_KEYS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return set()


def _save_fired_keys(keys: set):
    try:
        today  = datetime.now().strftime("%Y-%m-%d")
        pruned = {k for k in keys if today in k}
        FIRED_KEYS_FILE.write_text(json.dumps(list(pruned)), encoding="utf-8")
    except Exception:
        pass


def _scheduler_loop():
    fired_keys: set[str] = _load_fired_keys()
    while True:
        try:
            cfg = _load_schedule_cfg()
            if cfg.get("enabled"):
                now      = datetime.now()
                today    = now.strftime("%Y-%m-%d")

                # Recovery-Modus
                recovery_until = cfg.get("recovery_until")
                if recovery_until and today <= recovery_until:
                    time.sleep(30)
                    continue
                if recovery_until and today > recovery_until:
                    cfg["recovery_until"]  = None
                    cfg["recovery_reason"] = ""
                    _save_schedule_cfg(cfg)
                    logger.info("Recovery-Modus beendet")

                # Fired-Keys täglich zurücksetzen
                fired_keys = {k for k in fired_keys if k.startswith(today)}

                for slot in cfg.get("slots", []):
                    target   = slot.get("time", "18:00")
                    key      = f"{today}_{target}"
                    t_h, t_m = int(target.split(":")[0]), int(target.split(":")[1])
                    slot_min = t_h * 60 + t_m
                    now_min  = now.hour * 60 + now.minute
                    if slot_min <= now_min <= slot_min + 4 and key not in fired_keys:
                        fired_keys.add(key)
                        _save_fired_keys(fired_keys)
                        logger.info(f"Zeitplan: Slot um {target} feuert")
                        notify("Reddit Bot EN",f"Zeitplan: Story um {target}...")
                        job_id = str(uuid.uuid4())[:8]
                        jobs[job_id] = {"status": "running", "progress": 0, "message": "Startet...", "video": None}
                        threading.Thread(
                            target=_run_scheduled_single,
                            args=(job_id, slot),
                            daemon=True,
                        ).start()
        except Exception as e:
            logger.error(f"Scheduler-Fehler: {e}")
        time.sleep(30)


def _run_scheduled_single(job_id: str, slot: dict):
    # Random jitter 0-12 min so posts don't always land at machine-precise times
    _jitter = random.randint(0, 720)
    if _jitter:
        logger.info(f"Schedule: jitter {_jitter}s")
        time.sleep(_jitter)

    mode     = slot.get("mode", "new")
    filename = slot.get("filename", "")

    if mode == "auto":
        candidates = sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime)
        picked = None
        for f in candidates:
            meta_f = f.with_suffix(".json")
            if meta_f.exists():
                try:
                    m = json.loads(meta_f.read_text(encoding="utf-8"))
                    # Part-2 files are handled by the dedicated Part 2 block
                    if not m.get("uploaded", False) and not m.get("is_part2", False):
                        picked = f
                        break
                except Exception:
                    pass
        if picked:
            filename = picked.name
            mode     = "existing"
        else:
            mode = "new"

    if mode == "existing" and filename:
        vp = OUTPUT_DIR / filename
        if not vp.exists():
            jobs[job_id].update({"status": "error", "message": f"Datei nicht gefunden: {filename}"})
            return
        meta_f  = vp.with_suffix(".json")
        caption = ""
        if meta_f.exists():
            try:
                caption = json.loads(meta_f.read_text(encoding="utf-8")).get("caption", "")
            except Exception:
                pass
        if not caption:
            caption = f"Reddit Story 🔥\n{random.choice(_CTAS)}\n#fyp #reddit #redditstories #storytime"
        jobs[job_id].update({"status": "done", "message": f"Uploade {filename}...", "video": filename})
        _run_upload(filename, str(vp), caption)
    else:
        # ── Part 2 priority: upload pending Part 2 before generating new content ──
        for _pf in sorted(OUTPUT_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime):
            try:
                _pm = json.loads(_pf.read_text(encoding="utf-8"))
                if _pm.get("is_part2") and not _pm.get("uploaded"):
                    _p2_vid = _pf.with_suffix(".mp4")
                    if _p2_vid.exists():
                        _p2_cap = _pm.get("caption", "")
                        logger.info(f"Zeitplan: Pending Part 2 found — uploading {_p2_vid.name}")
                        notify("Reddit Bot EN", f"🎬 Part 2 upload: {_pm.get('title', _p2_vid.stem)[:50]}")
                        jobs[job_id].update({"status": "done", "message": f"Uploading Part 2: {_p2_vid.name}", "video": _p2_vid.name})
                        _run_upload(_p2_vid.name, str(_p2_vid), _p2_cap)
                        # Check if upload succeeded (uploaded=True set in JSON)
                        try:
                            _uploaded_ok = json.loads(_pf.read_text(encoding="utf-8")).get("uploaded", False)
                        except Exception:
                            _uploaded_ok = False
                        if _uploaded_ok:
                            return  # success
                        # Upload failed — delete Part 2 and generate fresh content instead
                        logger.warning(f"Part 2 upload failed — deleting {_p2_vid.name} and generating new story")
                        _p2_vid.unlink(missing_ok=True)
                        _pf.unlink(missing_ok=True)
                        break  # exit loop → fall through to _run_generation
                    else:
                        # MP4 missing — delete orphaned JSON
                        logger.warning(f"Part 2 JSON without MP4 ({_pf.name}) — deleting")
                        _pf.unlink(missing_ok=True)
            except Exception:
                pass

        subreddit  = slot.get("topic") or None
        _slot_time = slot.get("time", "?")
        for _attempt in range(3):  # max 3 Versuche
            _run_generation(job_id, subreddit)
            job = jobs.get(job_id, {})
            if job.get("video"):
                break  # Erfolg
            _err = job.get("message", "")
            if "Broken pipe" in _err or "BrokenPipe" in _err or "OSError" in _err:
                _delay, _reason = 30, "BrokenPipe (OOM)"
            elif "529" in _err or "verload" in _err.lower():
                _delay, _reason = 90, "Anthropic 529"
            elif "not able to create" in _err or "parse" in _err.lower():
                _delay, _reason = 5, "Claude-Ablehnung"
            else:
                _delay, _reason = 30, _err[:40] or "Unbekannter Fehler"
            if _attempt < 2:
                logger.warning(f"Zeitplan: Slot {_slot_time} — {_reason}, Retry {_attempt+1}/2 in {_delay}s")
                notify("Reddit Bot EN", f"⚠️ Slot {_slot_time}: {_reason}\nRetry {_attempt+1}/2 in {_delay}s…")
                time.sleep(_delay)
                jobs[job_id] = {"status": "running", "progress": 0, "message": f"Retry {_attempt+1}…", "video": None}
            else:
                logger.error(f"Zeitplan: Slot {_slot_time} endgültig fehlgeschlagen: {_err}")
                notify("Reddit Bot EN", f"❌ Slot {_slot_time}: Aufgegeben nach 3 Versuchen\n{_reason}: {_err[:60]}")
                return
        job = jobs.get(job_id, {})
        if job.get("video"):
            vp      = str(OUTPUT_DIR / job["video"])
            meta_f  = Path(vp).with_suffix(".json")
            caption = ""
            if meta_f.exists():
                try:
                    caption = json.loads(meta_f.read_text(encoding="utf-8")).get("caption", "")
                except Exception:
                    pass
            if not caption:
                caption = f"Reddit Story 🔥\n{random.choice(_CTAS)}\n#fyp #reddit #redditstories #storytime"
            _run_upload(job["video"], vp, caption)
            # 409-Duplikat: neue Story generieren und erneut hochladen
            if uploads.get(job["video"]) == "duplicate":
                logger.warning("Zeitplan: 409-Duplikat — generiere neue Reddit-Story...")
                job_id2 = str(uuid.uuid4())[:8]
                jobs[job_id2] = {"status": "running", "progress": 0, "message": "Retry (duplicate)...", "video": None}
                _run_generation(job_id2, subreddit)
                job2 = jobs.get(job_id2, {})
                if job2.get("video"):
                    vp2   = str(OUTPUT_DIR / job2["video"])
                    meta2 = Path(vp2).with_suffix(".json")
                    cap2  = json.loads(meta2.read_text(encoding="utf-8")).get("caption", caption) if meta2.exists() else caption
                    logger.info(f"Zeitplan: Retry-Upload nach Duplikat für {job2['video']}")
                    _run_upload(job2["video"], vp2, cap2)


@app.get("/api/videos/unuploaded")
def list_unuploaded():
    result = []
    for mp4 in sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True):
        meta_file = mp4.with_suffix(".json")
        meta: dict = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        if not meta.get("uploaded", False):
            result.append({
                "filename": mp4.name,
                "title":    meta.get("title", mp4.stem),
                "topic":    meta.get("subreddit", ""),
                "created":  datetime.fromtimestamp(mp4.stat().st_mtime).strftime("%d.%m. %H:%M"),
            })
    return result


@app.get("/api/schedule")
def get_schedule():
    return _load_schedule_cfg()


@app.post("/api/schedule")
def save_schedule(cfg: ScheduleConfig):
    data = cfg.model_dump()
    _save_schedule_cfg(data)
    logger.info(f"Zeitplan gespeichert: {'aktiv' if data['enabled'] else 'inaktiv'}, "
                f"{len(data['slots'])} Slot(s)")
    return {"status": "ok", **data}


@app.post("/api/schedule/pause")
def manual_pause(days: int = 7, reason: str = "Manuell pausiert"):
    cfg   = _load_schedule_cfg()
    until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    cfg["recovery_until"]  = until
    cfg["recovery_reason"] = reason
    _save_schedule_cfg(cfg)
    return {"status": "paused", "recovery_until": until}


@app.post("/api/schedule/resume")
def manual_resume():
    cfg = _load_schedule_cfg()
    cfg["enabled"]         = True
    cfg["recovery_until"]  = None
    cfg["recovery_reason"] = ""
    _save_schedule_cfg(cfg)
    return {"status": "resumed"}


# ── Static Files + Start ──────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"

@app.get("/")
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _start_background_threads():
    _load_queue()
    threading.Thread(target=_queue_processor, daemon=True).start()
    threading.Thread(target=_scheduler_loop,  daemon=True).start()
    logger.info(f"Reddit Story Bot EN started — {'Railway' if IS_RAILWAY else 'Local'}")


if __name__ == "__main__":
    _start_background_threads()
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
