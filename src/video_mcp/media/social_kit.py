"""Auto-chapters, viral hook titles, hashtags, and social copy generator."""

from __future__ import annotations

import re
from collections import Counter

from video_mcp.models import TranscriptSegment

_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "you", "your", "are", "was",
    "were", "have", "has", "had", "not", "but", "from", "they", "his", "her",
    "she", "him", "its", "our", "out", "can", "will", "just", "like", "what",
    "when", "how", "who", "why", "all", "one", "two", "about", "into", "more",
    "very", "here", "there", "then", "than", "them", "been", "being", "also",
}


def _fmt_chapter_ts(seconds: float) -> str:
    total = max(0, int(seconds))
    mins, secs = divmod(total, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _clean_phrase(text: str, max_words: int = 6) -> str:
    words = re.findall(r"[A-Za-z0-9']+", text)
    if not words:
        return "Highlight"
    return " ".join(words[:max_words]).strip().capitalize()


def generate_social_kit(
    segments: list[TranscriptSegment] | None,
    title: str,
) -> dict[str, object]:
    """Build YouTube chapters, viral title hooks, hashtags, and social descriptions."""
    clean_title = (title or "Studio Video").strip()
    segs = [s for s in (segments or []) if s.text.strip()]

    # 1. Auto-chapters (always start at 00:00, group roughly every 30s)
    chapters: list[dict[str, object]] = []
    if segs:
        chapters.append({"time": "00:00", "seconds": 0.0, "label": _clean_phrase(segs[0].text)})
        last_chapter_sec = 0.0
        for seg in segs[1:]:
            if seg.start - last_chapter_sec >= 28.0:
                chapters.append(
                    {
                        "time": _fmt_chapter_ts(seg.start),
                        "seconds": round(seg.start, 1),
                        "label": _clean_phrase(seg.text),
                    }
                )
                last_chapter_sec = seg.start
    else:
        chapters.append({"time": "00:00", "seconds": 0.0, "label": clean_title[:48]})

    # 2. Extract top keywords for hashtags
    full_text = " ".join(s.text for s in segs) if segs else clean_title
    tokens = [
        w.lower()
        for w in re.findall(r"[A-Za-z]{4,}", full_text)
        if w.lower() not in _STOPWORDS
    ]
    top_words = [word for word, _ in Counter(tokens).most_common(5)]
    hashtags = [f"#{w}" for w in top_words]
    for base_tag in ("#shorts", "#reels", "#video"):
        if base_tag not in hashtags:
            hashtags.append(base_tag)

    # 3. Viral hook titles
    lead_hook = _clean_phrase(segs[0].text, max_words=8) if segs else clean_title
    viral_titles = [
        f"{clean_title} (Must Watch)",
        f"Why Everyone Is Talking About: {lead_hook}",
        f"{lead_hook} — Full Breakdown",
    ]

    chapters_text = "\n".join(f"{c['time']} {c['label']}" for c in chapters)
    tags_line = " ".join(hashtags[:8])
    youtube_description = (
        f"{clean_title}\n\n"
        f"Chapters:\n{chapters_text}\n\n"
        f"{tags_line}"
    )
    reels_caption = f"{lead_hook}\n\n{tags_line}"

    return {
        "chapters": chapters,
        "viral_titles": viral_titles,
        "hashtags": hashtags[:8],
        "youtube_description": youtube_description,
        "reels_caption": reels_caption,
    }
