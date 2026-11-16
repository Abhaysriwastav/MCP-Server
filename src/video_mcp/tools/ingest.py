"""Ingest and media inspection tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from video_mcp.context import AppContext


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

