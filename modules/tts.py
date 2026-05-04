import asyncio
import os
import re

import edge_tts

# English Edge TTS voices: mix for variety
_EN_VOICES = [
    "en-US-ChristopherNeural",   # male, American
    "en-US-JennyNeural",         # female, American
    "en-GB-RyanNeural",          # male, British
    "en-GB-SoniaNeural",         # female, British
    "en-AU-WilliamNeural",       # male, Australian
]

OPENAI_VOICE = "onyx"
OPENAI_MODEL = "tts-1"

# Mood → (voice, speed) — different voice + tempo per story type for variety
_MOOD_VOICE: dict[str, tuple[str, float]] = {
    "drama":    ("onyx",    0.92),   # deep, serious, slightly slower
    "funny":    ("shimmer", 1.08),   # light, playful, slightly faster
    "sad":      ("nova",    0.88),   # soft, empathetic, slower
    "suspense": ("fable",   0.95),   # mysterious storyteller, slightly slower
}


def _tts_openai(text: str, audio_path: str, api_key: str,
                voice: str = OPENAI_VOICE, speed: float = 1.0) -> list[dict]:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    response = client.audio.speech.create(
        model=OPENAI_MODEL,
        voice=voice,
        input=text,
        speed=speed,
    )
    with open(audio_path, "wb") as f:
        f.write(response.content)

    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )

    word_timings = []
    for w in (transcript.words or []):
        word_timings.append({"word": w.word.strip(), "start": w.start, "end": w.end})
    return word_timings


async def _tts_edge_async(text: str, audio_path: str, voice_name: str) -> list[dict]:
    communicate  = edge_tts.Communicate(text, voice_name, boundary="WordBoundary")
    word_timings = []
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                dur   = chunk["duration"] / 1e7
                word_timings.append({"word": chunk["text"], "start": start, "end": start + dur})
    return word_timings


def text_to_speech(text: str, output_path: str, topic: str = "",
                   mood: str = "") -> tuple[str, list[dict]]:
    """
    OpenAI TTS (mood-adapted voice+speed) → Edge TTS fallback.
    mood: 'drama' | 'funny' | 'sad' | 'suspense' | ''
    """
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if openai_key:
        voice, speed = _MOOD_VOICE.get(mood, (OPENAI_VOICE, 1.0))
        try:
            print(f"   OpenAI TTS [{voice} @ {speed}x] ...")
            timings = _tts_openai(text, output_path, openai_key, voice=voice, speed=speed)
            return output_path, timings
        except Exception as e:
            print(f"   OpenAI TTS error: {e} — falling back to Edge TTS")

    import random
    voice_name = random.choice(_EN_VOICES)
    print(f"   Edge TTS: {voice_name}")
    timings = asyncio.run(_tts_edge_async(text, output_path, voice_name))
    return output_path, timings


def get_sentence_timings(text: str, word_timings: list[dict]) -> list[tuple]:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if not word_timings:
        return [(s, i * 3.0, (i + 1) * 3.0) for i, s in enumerate(sentences)]
    result, word_idx = [], 0
    for sentence in sentences:
        n  = len(re.findall(r'\w+', sentence))
        si = min(word_idx, len(word_timings) - 1)
        ei = min(word_idx + n - 1, len(word_timings) - 1)
        result.append((sentence, max(0, word_timings[si]["start"] - 0.1), word_timings[ei]["end"] + 0.2))
        word_idx += n
    return result
