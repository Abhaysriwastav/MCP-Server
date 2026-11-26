"""Ingest and media inspection tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from video_mcp.context import AppContext
from video_mcp.media.viral_miner import (
    detect_viral_scenes,
    fuse_viral_moments,
    mine_catchy_dialogue,
    mine_comment_moments,
    mine_heatmap_peaks,
)
from video_mcp.models import SourceKind
from video_mcp.tools import editing


async def ingest_source(
    app: AppContext,
    uri: str,
    probe_media: bool = True,
) -> dict[str, Any]:
    """Resolve and register a local file, HTTP(S) URL, or S3 URI into the workspace."""
    asset = await app.resolver.resolve(uri, probe_media=probe_media)
    existing = app.store.get_source_by_sha256(asset.sha256)
    if existing is not None:
        return {"status": "deduplicated", "source": existing.model_dump()}
    saved = app.store.save_source(asset)
    app.store.log_activity(
        category="ingest",
        message=f"Ingested {saved.kind.value} source '{saved.filename}'",
        details={"source_id": saved.source_id, "uri": saved.uri, "size_bytes": saved.size_bytes},
    )
    return {"status": "ingested", "source": saved.model_dump()}


async def probe_media(app: AppContext, source_id_or_path: str) -> dict[str, Any]:
    """Inspect a registered source_id or allowed local file path using ffprobe."""
    src = app.store.get_source(source_id_or_path)
    if src is not None:
        probe_data = await app.runner.probe(Path(src.local_path))
        return {"source_id": src.source_id, "probe": probe_data}

    resolved = await app.resolver.resolve(source_id_or_path, probe_media=True)
    return {"uri": resolved.uri, "probe": resolved.probe}


def list_sources(app: AppContext, limit: int = 50) -> dict[str, Any]:
    """List recently ingested media sources."""
    sources = app.store.list_sources(limit=limit)
    return {"count": len(sources), "sources": [s.model_dump() for s in sources]}


async def transcribe_source(
    app: AppContext,
    source_id: str,
    start_sec: float | None = None,
    end_sec: float | None = None,
) -> dict[str, Any]:
    """Return timestamped transcript lines & structured segments for a source (cached in SQLite)."""
    src = app.store.get_source(source_id)
    if src is None:
        raise ValueError(f"Source not found: {source_id}")

    cached = True
    segments = app.store.get_transcript(source_id)
    if segments is None:
        cached = False
        segments = await app.transcriber.transcribe_media(
            Path(src.local_path), word_timestamps=True
        )
        app.store.save_transcript(source_id, segments)
        app.store.log_activity(
            category="transcribe",
            message=f"Transcribed source '{src.filename}' ({len(segments)} segments)",
            details={"source_id": source_id, "segment_count": len(segments)},
        )

    filtered = [
        seg
        for seg in segments
        if (start_sec is None or seg.end >= start_sec)
        and (end_sec is None or seg.start <= end_sec)
    ]
    formatted_lines = [
        f"[{seg.start:.2f}s -> {seg.end:.2f}s] {seg.text}" for seg in filtered
    ]
    return {
        "source_id": source_id,
        "cached": cached,
        "segment_count": len(filtered),
        "transcript_lines": formatted_lines,
        "segments": [seg.model_dump() for seg in filtered],
    }


async def find_dialogue_moments(
    app: AppContext,
    source_id: str,
    query: str | None = None,
    padding_sec: float = 2.0,
    limit: int = 10,
) -> dict[str, Any]:
    """Search a source's transcript for dialogue phrases (or top highlight moments) with clip bounds."""
    transcript = await transcribe_source(app, source_id=source_id)
    segments = transcript["segments"]
    q = (query or "").strip().lower()

    candidates: list[dict[str, Any]] = []
    for seg in segments:
        text = str(seg["text"]).strip()
        if not text:
            continue
        if q:
            if q not in text.lower():
                continue
            score = 10.0 + text.lower().count(q)
        else:
            # Heuristic highlight score: punchy speech + punctuation
            words = len(text.split())
            exclaim = text.count("!") * 2.0 + text.count("?") * 1.5
            score = min(words, 25) * 0.4 + exclaim

        start_sec = round(max(0.0, float(seg["start"]) - padding_sec), 2)
        end_sec = round(float(seg["end"]) + padding_sec, 2)
        candidates.append(
            {
                "start_sec": start_sec,
                "end_sec": end_sec,
                "dialogue_start": round(float(seg["start"]), 2),
                "dialogue_end": round(float(seg["end"]), 2),
                "text": text,
                "score": round(score, 2),
            }
        )

    if not q:
        candidates.sort(key=lambda c: c["score"], reverse=True)

    return {
        "source_id": source_id,
        "query": query or "",
        "match_count": len(candidates[:limit]),
        "matches": candidates[:limit],
        "transcript_lines": transcript["transcript_lines"],
    }


async def analyze_viral_clips(
    app: AppContext,
    source_id: str,
    query: str | None = None,
    max_clips: int = 8,
    min_clip_sec: float = 6.0,
    max_clip_sec: float = 25.0,
    include_scene_detection: bool = True,
    refresh_comments: bool = False,
) -> dict[str, Any]:
    """Analyze a source using YouTube comments/likes, heatmap, Whisper dialogue, and FFmpeg scenes."""
    src = app.store.get_source(source_id)
    if src is None:
        raise ValueError(f"Source not found: {source_id}")

    yt_meta = dict((src.probe or {}).get("youtube") or {})
    if src.kind == SourceKind.YOUTUBE and (refresh_comments or not yt_meta.get("comments")):
        try:
            engagement = await app.resolver.fetch_youtube_engagement(src.uri)
            yt_meta.update(engagement)
            src.probe = {**(src.probe or {}), "youtube": yt_meta}
            app.store.save_source(src)
        except Exception:
            pass

    segments: list[dict[str, Any]] = []
    transcript_warning: str | None = None
    has_audio = bool((src.probe or {}).get("has_audio", True))
    if has_audio:
        try:
            transcript = await transcribe_source(app, source_id=source_id)
            segments = list(transcript.get("segments") or [])
        except Exception as exc:
            transcript_warning = str(exc)

    duration_sec = float(
        (src.probe or {}).get("duration_sec") or yt_meta.get("duration_sec") or 0.0
    )
    comments = list(yt_meta.get("comments") or [])
    heatmap = list(yt_meta.get("heatmap") or [])

    comment_moments = mine_comment_moments(
        comments=comments,
        segments=segments,
        duration_sec=duration_sec,
        min_clip_sec=min_clip_sec,
        max_clip_sec=max_clip_sec,
    )
    heatmap_peaks = mine_heatmap_peaks(
        heatmap=heatmap,
        duration_sec=duration_sec,
        min_clip_sec=min_clip_sec,
        max_clip_sec=max_clip_sec,
    )
    dialogue_moments = mine_catchy_dialogue(
        segments=segments,
        query=query,
        duration_sec=duration_sec,
        min_clip_sec=min_clip_sec,
        max_clip_sec=max_clip_sec,
    )
    scene_moments: list[dict[str, Any]] = []
    if include_scene_detection:
        scene_moments = await detect_viral_scenes(
            runner=app.runner,
            video_path=Path(src.local_path),
            duration_sec=duration_sec,
            has_audio=has_audio,
            min_clip_sec=min_clip_sec,
            max_clip_sec=max_clip_sec,
        )

    fused = fuse_viral_moments(
        comment_moments=comment_moments,
        heatmap_peaks=heatmap_peaks,
        dialogue_moments=dialogue_moments,
        scene_moments=scene_moments,
        segments=segments,
        youtube_meta=yt_meta,
        title=src.filename,
        duration_sec=duration_sec,
        max_clips=max(1, min(20, max_clips)),
        min_clip_sec=min_clip_sec,
        max_clip_sec=max_clip_sec,
    )
    app.store.log_activity(
        category="viral_analysis",
        message=f"Found {fused['moment_count']} viral moments for '{src.filename}'",
        details={
            "source_id": source_id,
            "comments_analyzed": fused["video_engagement"]["comments_analyzed"],
            "engagement_grade": fused["video_engagement"]["engagement_grade"],
        },
    )
    return {
        "source_id": source_id,
        "transcript_warning": transcript_warning,
        **fused,
    }


async def extract_viral_clips(
    app: AppContext,
    source_id: str,
    top_n: int = 3,
    output_profile: str = "vertical_9x16",
    query: str | None = None,
    min_clip_sec: float = 6.0,
    max_clip_sec: float = 25.0,
    auto_caption: bool = True,
    smart_crop: bool = True,
    audio_normalize: bool = True,
    add_hook_overlay: bool = True,
    remove_silences: bool = False,
    color_preset: str = "original",
    include_scene_detection: bool = True,
    refresh_comments: bool = False,
    auto_render: bool = True,
) -> dict[str, Any]:
    """Analyze and extract the top `top_n` viral clips as ready-to-review edit jobs."""
    analysis = await analyze_viral_clips(
        app,
        source_id=source_id,
        query=query,
        max_clips=max(1, top_n),
        min_clip_sec=min_clip_sec,
        max_clip_sec=max_clip_sec,
        include_scene_detection=include_scene_detection,
        refresh_comments=refresh_comments,
    )
    selected = list(analysis["moments"][: max(1, top_n)])
    jobs: list[dict[str, Any]] = []
    for idx, moment in enumerate(selected, start=1):
        ops: list[dict[str, Any]] = [
            {
                "op": "trim",
                "start_sec": float(moment["start_sec"]),
                "end_sec": float(moment["end_sec"]),
            }
        ]
        if color_preset and color_preset != "original":
            ops.append({"op": "color_preset", "preset": color_preset})
        if remove_silences:
            ops.append({"op": "remove_silences"})
        if audio_normalize:
            ops.append({"op": "audio_normalize", "target_i": -14.0})
        if add_hook_overlay and moment.get("hook_text"):
            ops.append(
                {
                    "op": "text_overlay",
                    "text": str(moment["hook_text"])[:120],
                    "position": "top",
                }
            )
        if smart_crop:
            ops.append({"op": "smart_crop", "enabled": True})
        if auto_caption:
            ops.append({"op": "auto_caption"})

        title = f"Viral #{idx} [{moment['viral_score']}/100] ({moment['start_sec']}s-{moment['end_sec']}s)"
        created = editing.create_edit_job(
            app,
            title=title,
            source_ids=[source_id],
            operations=ops,
            output_profile=output_profile,
        )
        job_dict = created["job"]
        if auto_render:
            rendered = await editing.render_edit_job(app, job_dict["job_id"])
            job_dict = rendered["job"]
        jobs.append(job_dict)

    return {
        "source_id": source_id,
        "video_engagement": analysis["video_engagement"],
        "extracted_count": len(jobs),
        "jobs": jobs,
        "moments": selected,
    }

