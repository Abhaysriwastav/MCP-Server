"""Video editing job creation, rendering, and inspection tools."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from video_mcp.context import AppContext
from video_mcp.models import EditJob, EditOperation, JobStatus, OutputProfile, SourceAsset

_OP_ADAPTER: TypeAdapter[list[EditOperation]] = TypeAdapter(list[EditOperation])


def create_edit_job(
    app: AppContext,
    title: str,
    source_ids: list[str],
    operations: list[dict[str, Any]] | None = None,
    output_profile: str = OutputProfile.BOTH.value,
) -> dict[str, Any]:
    """Create a new DRAFT video editing job with validated operations and output profile."""
    if not source_ids:
        raise ValueError("source_ids must contain at least one registered source_id.")
    for sid in source_ids:
        if app.store.get_source(sid) is None:
            raise ValueError(f"Unknown source_id: {sid}")

    parsed_ops = _OP_ADAPTER.validate_python(operations or [])
    profile = OutputProfile(output_profile)

    job = EditJob(
        job_id=f"job_{uuid.uuid4().hex[:12]}",
        title=title,
        source_ids=source_ids,
        operations=[op.model_dump() for op in parsed_ops],
        output_profile=profile,
        status=JobStatus.DRAFT,
    )
    app.store.save_job(job)
    app.store.log_activity(
        category="job",
        message=f"Created edit job '{job.title}' ({job.output_profile.value})",
        job_id=job.job_id,
        details={"operations_count": len(parsed_ops), "source_ids": source_ids},
    )
    return {"job": job.model_dump()}


async def render_edit_job(app: AppContext, job_id: str) -> dict[str, Any]:
    """Execute the FFmpeg editing pipeline for a job and produce media + metadata outputs."""
    job = app.store.get_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    if job.status in {JobStatus.PENDING_APPROVAL, JobStatus.APPROVED, JobStatus.PUBLISHED}:
        raise ValueError(
            f"Cannot re-render job '{job_id}' in status '{job.status.value}'. "
            "Reject or create a new job instead."
        )

    sources: list[SourceAsset] = []
    for sid in job.source_ids:
        src = app.store.get_source(sid)
        if src is None:
            raise ValueError(f"Missing source '{sid}' for job '{job_id}'")
        sources.append(src)

    parsed_ops = _OP_ADAPTER.validate_python(job.operations)
    watermark_sources: dict[str, SourceAsset] = {}
    for op in parsed_ops:
        if op.op == "watermark":
            wm_src = app.store.get_source(op.image_source_id)
            if wm_src is None:
                raise ValueError(f"Missing watermark source: {op.image_source_id}")
            watermark_sources[op.image_source_id] = wm_src

    job.status = JobStatus.RENDERING
    job.error = None
    app.store.save_job(job)
    app.store.log_activity(
        category="render",
        message=f"Started rendering job '{job.title}'",
        job_id=job.job_id,
        details={"output_profile": job.output_profile.value},
    )

    try:
        artifacts = await app.pipeline.render_job(
            job_id=job.job_id,
            sources=sources,
            operations=parsed_ops,
            output_profile=job.output_profile,
            watermark_sources=watermark_sources,
        )
        job.artifacts = artifacts
        job.status = JobStatus.READY_FOR_REVIEW
        app.store.save_job(job)
        app.store.log_activity(
            category="render",
            message=f"Rendered {len(artifacts)} artifacts for '{job.title}'",
            job_id=job.job_id,
            details={"artifact_kinds": [a.kind for a in artifacts]},
        )
        return {"job": job.model_dump()}
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = str(exc)
        app.store.save_job(job)
        app.store.log_activity(
            category="render",
            level="error",
            message=f"Render failed for '{job.title}': {exc}",
            job_id=job.job_id,
        )
        raise


def get_job_status(app: AppContext, job_id: str) -> dict[str, Any]:
    """Return full status, artifacts, and approval linkage for an edit job."""
    job = app.store.get_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    return {"job": job.model_dump()}


def list_jobs(app: AppContext, status: str | None = None, limit: int = 50) -> dict[str, Any]:
    """List edit jobs, optionally filtered by JobStatus."""
    parsed_status = JobStatus(status) if status else None
    jobs = app.store.list_jobs(status=parsed_status, limit=limit)
    return {"count": len(jobs), "jobs": [j.model_dump() for j in jobs]}


async def generate_thumbnail(
    app: AppContext,
    source_id: str,
    timestamp_sec: float = 0.5,
) -> dict[str, Any]:
    """Extract a standalone preview JPEG thumbnail from a registered source."""
    src = app.store.get_source(source_id)
    if src is None:
        raise ValueError(f"Source not found: {source_id}")
    out_path = (
        app.settings.workspace_dir
        / "thumbnails"
        / f"{source_id}_{timestamp_sec:.2f}s.jpg"
    )
    await app.pipeline.generate_thumbnail(Path(src.local_path), out_path, timestamp_sec)
    return {"thumbnail_path": str(out_path), "source_id": source_id, "timestamp_sec": timestamp_sec}

