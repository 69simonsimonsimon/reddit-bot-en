"""
Reddit Story Fetcher — English
-------------------------------
Fetches Reddit stories via the public JSON API (no API key needed),
condenses to max 130 words for TikTok via Claude.
"""

import json
import logging
import os
import random
import re
import threading
import time
from pathlib import Path


def _extract_json_fields(text: str) -> dict:
    """Extracts JSON fields robustly via regex — fallback when json.loads fails."""
    def extract(key: str) -> str:
        pattern = rf'"{key}"\s*:\s*"([\s\S]*?)"(?:\s*[,}}])'
        m = re.search(pattern, text)
        if m:
            return m.group(1).replace('\\"', '"').replace('\\n', '\n')
        pattern2 = rf'"{key}"\s*:\s*"([\s\S]+)"'
        m2 = re.search(pattern2, text)
        return m2.group(1).replace('\\"', '"').replace('\\n', '\n') if m2 else ""
    return {
        "title":       extract("title"),
        "story":       extract("story"),
        "part1":       extract("part1"),
        "part2":       extract("part2"),
        "description": extract("description"),
    }

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [story_fetcher] %(message)s", force=True)
_log = logging.getLogger("story_fetcher")

_generation_lock = threading.Lock()

_CLAUDE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

SUBREDDITS = [
    # ─── AITA / Judgment (Gen Z favorite) ────────────────────────────────────
    "AmItheAsshole",
    "AITAH",
    "AmIOverreacting",
    # ─── Fail / Cringe / Funny ───────────────────────────────────────────────
    "tifu",
    "mildlyinfuriating",    # Massive Gen Z community — extremely relatable
    "facepalm",             # Cringe moments — viral with 16–25
    "Unexpected",           # Short surprising stories — very shareable
    # ─── Relationship / Dating (young audience) ───────────────────────────────
    "relationship_advice",
    "breakups",             # Very relevant 16–25 — first heartbreaks
    "confessions",
    # ─── Youth / School / College ─────────────────────────────────────────────
    "teenagers",            # Direct Gen Z audience
    "college",              # Student drama — 18–24
    "TwoHotTakes",          # Already viral, younger audience
    # ─── Revenge / Karma ─────────────────────────────────────────────────────
    "pettyrevenge",
    "maliciouscompliance",
    "ProRevenge",
    # ─── Drama / Entitled ────────────────────────────────────────────────────
    "entitledparents",
    "entitledpeople",
    "ChoosingBeggars",
    "offmychest",
    "TrueOffMyChest",
    # ─── Family / Toxic ──────────────────────────────────────────────────────
    "raisedbynarcissists",  # Very popular with Gen Z — processing toxic childhood
    # ─── Updates / Resolutions ────────────────────────────────────────────────
    "BestofRedditorUpdates",
]

_USED_IDS_FILE = Path(__file__).parent.parent / "output" / "used_posts.json"

_HASHTAG_CORE = ["#fyp", "#reddit", "#storytime"]

_SUBREDDIT_HASHTAGS: dict[str, list[str]] = {
    "AmItheAsshole":        ["#aita", "#relationship", "#drama", "#judgment", "#aitatiktok", "#aitareddit"],
    "AITAH":                ["#aita", "#relationship", "#drama", "#judgment", "#aitatiktok", "#aitareddit"],
    "AmIOverreacting":      ["#aita", "#drama", "#relationship", "#judgment", "#redditdrama"],
    "tifu":                 ["#tifu", "#fail", "#funny", "#embarrassing", "#oops", "#redditfail"],
    "mildlyinfuriating":    ["#annoying", "#relatable", "#cringe", "#drama", "#genz"],
    "facepalm":             ["#facepalm", "#cringe", "#funny", "#smh", "#drama"],
    "Unexpected":           ["#unexpected", "#surprise", "#wow", "#shocking", "#viral"],
    "relationship_advice":  ["#relationship", "#love", "#drama", "#advice", "#dating", "#redditrelationship"],
    "breakups":             ["#breakup", "#heartbreak", "#love", "#drama", "#relatable"],
    "confessions":          ["#confession", "#secrets", "#anonymous", "#truestory", "#shocking"],
    "teenagers":            ["#teenager", "#highschool", "#genz", "#youth", "#drama"],
    "college":              ["#college", "#university", "#genz", "#drama", "#campuslife"],
    "TwoHotTakes":          ["#twohotttakes", "#drama", "#opinion", "#relationship", "#viral"],
    "pettyrevenge":         ["#pettyrevenge", "#satisfying", "#revenge", "#karma", "#justice"],
    "maliciouscompliance":  ["#maliciouscompliance", "#satisfying", "#clever", "#revenge", "#work"],
    "ProRevenge":           ["#revenge", "#prorevenge", "#satisfying", "#justice", "#karma"],
    "entitledparents":      ["#entitledparents", "#karen", "#drama", "#cringe", "#nope"],
    "entitledpeople":       ["#entitledpeople", "#karen", "#drama", "#cringe", "#redditdrama"],
    "ChoosingBeggars":      ["#choosingbeggars", "#entitlement", "#cringe", "#drama", "#nope"],
    "offmychest":           ["#offmychest", "#truestory", "#confession", "#emotional", "#anonymous"],
    "TrueOffMyChest":       ["#truestory", "#offmychest", "#confession", "#emotional", "#anonymous"],
    "raisedbynarcissists":  ["#narcissist", "#trauma", "#family", "#drama", "#healing"],
    "BestofRedditorUpdates":["#redditupdate", "#redditstories", "#drama", "#satisfying", "#update"],
}

_HASHTAG_REACH = [
    "#viral", "#foryou", "#foryoupage", "#redditstories", "#redditreads",
    "#redditdrama", "#redditreadings", "#storytelling", "#truestory",
    "#shocking", "#unbelievable", "#relatable", "#redtok",
    "#storytime", "#mustwatch", "#crazy",
]

_HEADERS = {
    "User-Agent": "reddit-story-bot/1.0",
}

_PULLPUSH_URL = "https://api.pullpush.io/reddit/search/submission/"


def _load_used_ids() -> set:
    try:
        if _USED_IDS_FILE.exists():
            return set(json.loads(_USED_IDS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return set()


def _save_used_id(post_id: str):
    try:
        _USED_IDS_FILE.parent.mkdir(exist_ok=True, parents=True)
        ids      = _load_used_ids()
        ids.add(post_id)
        ids_list = list(ids)[-500:]
        _USED_IDS_FILE.write_text(json.dumps(ids_list, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _get_hashtags(subreddit: str) -> list[str]:
    topic_tags = list(_SUBREDDIT_HASHTAGS.get(subreddit, ["#reddit", "#story", "#drama"]))
    random.shuffle(topic_tags)
    reach_pool = [t for t in _HASHTAG_REACH if t not in topic_tags and t not in _HASHTAG_CORE]
    random.shuffle(reach_pool)
    return _HASHTAG_CORE + topic_tags[:4] + reach_pool[:2]


def _fetch_reddit_posts(subreddit: str, sort: str = "hot") -> list[dict]:
    """Fetches posts via Pullpush.io — bypasses Reddit's datacenter IP blocks."""
    params = {
        "subreddit": subreddit,
        "is_self": "true",
        "size": 50,
    }
    try:
        resp = requests.get(_PULLPUSH_URL, headers=_HEADERS, params=params, timeout=20)
        _log.info(f"Pullpush HTTP {resp.status_code} for r/{subreddit}")
        resp.raise_for_status()
        posts = resp.json().get("data", [])
        _log.info(f"Pullpush returned {len(posts)} posts for r/{subreddit}")
        return posts
    except Exception as e:
        _log.warning(f"Pullpush API error ({subreddit}): {e}")
        return []


def _llm_call(prompt: str, max_tokens: int = 1800) -> str:
    """Call Anthropic — falls back to OpenAI GPT-4o-mini if credits exhausted."""
    import anthropic as _anthropic
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        try:
            client = _anthropic.Anthropic(api_key=anthropic_key)
            msg = client.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text.strip()
        except _anthropic.BadRequestError as e:
            if "credit balance" in str(e).lower():
                import logging
                logging.getLogger("redditbot-en").warning("[llm] Anthropic credits exhausted — OpenAI fallback")
            else:
                raise
    import openai
    oai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not oai_key:
        raise RuntimeError("Neither Anthropic nor OpenAI API key available")
    oai = openai.OpenAI(api_key=oai_key)
    resp = oai.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


def _adapt_for_tiktok_en(title: str, text: str, subreddit: str) -> dict:
    """Prepares the story for TikTok — complete story, English.
    For long posts (>500 words) returns part1 + part2 for a two-video split."""

    _is_long = len(text.split()) > 500

    if _is_long:
        prompt = f"""You are a viral TikTok content creator targeting a 16–25 year old audience, specializing in Reddit story videos.

Subreddit: r/{subreddit}
Post title: {title}
Story text:
{text[:6000]}

This is a LONG story — split it into TWO back-to-back TikTok videos for maximum engagement and follows.

**Part 1 (~65 words):**
- Open with a SCROLL-STOPPING first sentence — write the actual shocking/emotional content, NOT "you won't believe this"
- Set up the story, build tension
- End on a DRAMATIC cliffhanger — the most suspenseful possible stopping point
- Last line must drive follows: end with "Part 2 dropping tomorrow..." or "Follow to see how it ends..."

**Part 2 (~200 words):**
- Continue directly from the Part 1 cliffhanger
- Deliver ALL the important details, twists, and the full resolution
- End with a satisfying, emotionally resonant conclusion

**Title** (max 8 words): Should be a shocking statement or question — first-person if possible. Examples: "My husband's secret destroyed our family", "I found out my boss lied about everything"

**Caption** (1-2 sentences): Create FOMO. Make viewers feel they MUST watch.

Reply ONLY with this JSON (no markdown, no other text):
{{
  "title": "Shocking title (max 8 words)",
  "part1": "Part 1 story (~65 words, ends in cliffhanger)",
  "part2": "Part 2 story (~200 words, full resolution)",
  "description": "TikTok caption creating FOMO (1-2 sentences)"
}}"""
    else:
        prompt = f"""You are a viral TikTok content creator targeting a 16–25 year old audience, specializing in Reddit story videos.

Subreddit: r/{subreddit}
Post title: {title}
Story text:
{text[:6000]}

Your task:
1. SCROLL-STOPPING first sentence — write the actual shocking/emotional content. NOT "you won't believe this" — write the actual thing that makes someone stop scrolling. Example: "My husband of 7 years casually told me our marriage was a business arrangement — on our anniversary."
2. Tell the story in SHORT, punchy sentences. Build tension step by step. Include all important details, twists, and the ending (max 350 words).
3. Only cut genuine repetitions or irrelevant tangents — the story must feel complete and satisfying.
4. TikTok title (max 8 words): shocking statement or question, first-person if possible. NOT a summary — make it emotional/intriguing.
5. TikTok caption (1-2 sentences): create FOMO, make viewers feel they MUST watch and share.

Reply ONLY with this JSON format (no markdown, no other text):
{{
  "title": "Shocking/intriguing title (max 8 words)",
  "story": "The complete story (max 350 words)",
  "description": "FOMO-inducing caption (1-2 sentences)"
}}"""

    raw   = _llm_call(prompt, max_tokens=1800)
    match = re.search(r'\{[\s\S]*\}', raw)
    raw   = match.group(0) if match else raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: extract fields individually via regex — robust against unescaped special chars
        data = _extract_json_fields(raw)
        if not data.get("story") and not data.get("part1"):
            raise RuntimeError(f"Could not parse Claude response: {raw[:200]}")

    if _is_long:
        # Normalize: part1 → story; apply per-part word limits
        part1 = data.get("part1", "")
        part2 = data.get("part2", "")

        p1_words = part1.split()
        if len(p1_words) > 80:
            part1 = " ".join(p1_words[:80])
            for ec in [". ", "! ", "? "]:
                idx = part1.rfind(ec)
                if idx > 20:
                    part1 = part1[:idx + 1]
                    break

        p2_words = part2.split()
        if len(p2_words) > 220:
            part2 = " ".join(p2_words[:220])
            for ec in [". ", "! ", "? "]:
                idx = part2.rfind(ec)
                if idx > 50:
                    part2 = part2[:idx + 1]
                    break

        data["story"] = part1
        data["part2"] = part2
    else:
        words = data.get("story", "").split()
        if len(words) > 360:
            data["story"] = " ".join(words[:360])
            last_end = max(data["story"].rfind(". "), data["story"].rfind("! "), data["story"].rfind("? "))
            if last_end > 50:
                data["story"] = data["story"][:last_end + 1]

    return data


def fetch_story(subreddit_override: str = None) -> dict:
    """
    Fetches a suitable Reddit story and returns it TikTok-ready.
    Uses the public Reddit JSON API — no API key needed.
    Lock is held only for file I/O so parallel workers don't block each other.
    """
    with _generation_lock:
        used_ids       = _load_used_ids()
        subreddit_name = subreddit_override or random.choice(SUBREDDITS)

    for attempt in range(len(SUBREDDITS)):
        sort  = "hot" if random.random() < 0.6 else "top"
        posts = _fetch_reddit_posts(subreddit_name, sort)

        time.sleep(0.5)

        with _generation_lock:
            used_ids = _load_used_ids()  # refresh — another worker may have added IDs

        candidates = [
            p for p in posts
            if not p.get("stickied", False)
            and p.get("is_self", False)
            and p.get("id") not in used_ids
            and len(p.get("selftext", "")) >= 300
            and p.get("selftext", "") not in ["[removed]", "[deleted]", ""]
            and len(p.get("selftext", "")) <= 8000
        ]

        _log.info(f"r/{subreddit_name}: {len(posts)} posts → {len(candidates)} candidates")
        if candidates:
            post = random.choice(candidates[:15])
            _log.info(f"Post selected: r/{subreddit_name} — {post['title'][:60]}")
            adapted = _adapt_for_tiktok_en(post["title"], post["selftext"], subreddit_name)  # LLM — no lock
            with _generation_lock:
                _save_used_id(post["id"])
            result = {
                "title":       adapted["title"],
                "story":       adapted["story"],
                "description": adapted.get("description", adapted["title"]),
                "hashtags":    _get_hashtags(subreddit_name),
                "subreddit":   subreddit_name,
                "post_id":     post["id"],
            }
            if adapted.get("part2"):
                result["part2"] = adapted["part2"]
            return result

        _log.info(f"No suitable posts in r/{subreddit_name} — trying next")
        subreddit_name = random.choice(SUBREDDITS)

    raise RuntimeError("No suitable Reddit post found after multiple attempts")
