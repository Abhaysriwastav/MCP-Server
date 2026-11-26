"""Lightweight async text & transcript translation for multi-language AI dubbing."""

from __future__ import annotations

import httpx

from video_mcp.models import TranscriptSegment


async def translate_text(text: str, target_language: str, source_language: str = "en") -> str:
    """Translate `text` into `target_language` via MyMemory free API (falls back to original on error)."""
    cleaned = text.strip()
    src = source_language.split("-")[0].lower()
    tgt = target_language.split("-")[0].lower()
    if not cleaned or src == tgt:
        return cleaned

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.mymemory.translated.net/get",
                params={"q": cleaned[:490], "langpair": f"{src}|{tgt}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                translated = str(
                    (data.get("responseData") or {}).get("translatedText") or ""
                ).strip()
                if translated:
                    return translated
    except Exception:
        pass
    return cleaned


async def translate_segments(
    segments: list[TranscriptSegment],
    target_language: str,
    source_language: str = "en",
) -> list[TranscriptSegment]:
    """Translate each TranscriptSegment's text while preserving timing for synced captions."""
    tgt = target_language.split("-")[0].lower()
    src = source_language.split("-")[0].lower()
    if src == tgt:
        return segments

    translated_segments: list[TranscriptSegment] = []
    for seg in segments:
        new_text = await translate_text(seg.text, target_language=tgt, source_language=src)
        translated_segments.append(
            TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=new_text,
                words=[],  # Clear source-language word timings so generate_srt splits translated text cleanly
            )
        )
    return translated_segments
