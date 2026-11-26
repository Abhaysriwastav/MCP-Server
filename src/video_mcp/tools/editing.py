"""Video editing job creation, rendering, and inspection tools."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from video_mcp.context import AppContext
from video_mcp.media.job_control import RenderCancelledError
from video_mcp.models import EditJob, EditOperation, JobStatus, OutputProfile, SourceAsset, utc_now_iso

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
    voice_reference_sources: dict[str, SourceAsset] = {}
    for op in parsed_ops:
        if op.op == "watermark":
            wm_src = app.store.get_source(op.image_source_id)
            if wm_src is None:
                raise ValueError(f"Missing watermark source: {op.image_source_id}")
            watermark_sources[op.image_source_id] = wm_src
        elif op.op == "voice_clone" and op.reference_audio_source_id:
            ref_src = app.store.get_source(op.reference_audio_source_id)
            if ref_src is None:
                raise ValueError(f"Missing voice reference source: {op.reference_audio_source_id}")
            voice_reference_sources[op.reference_audio_source_id] = ref_src

    job.status = JobStatus.RENDERING
    job.progress_pct = 0.0
    job.progress_stage = "Starting"
    job.render_started_at = utc_now_iso()
    job.eta_sec = None
    job.approval_id = None
    job.artifacts = []
    job.error = None
    app.store.save_job(job)
    app.store.log_activity(
        category="render",
        message=f"Started rendering job '{job.title}'",
        job_id=job.job_id,
        details={"output_profile": job.output_profile.value},
    )

    t0 = time.monotonic()
    last_saved = {"pct": -1.0, "stage": ""}

    def _on_progress(pct: float, stage: str) -> None:
        rounded = round(pct, 1)
        if stage != last_saved["stage"] or (rounded - last_saved["pct"]) >= 1.0:
            last_saved["pct"] = rounded
            last_saved["stage"] = stage
            job.progress_pct = rounded
            job.progress_stage = stage
            elapsed = max(0.0, time.monotonic() - t0)
            if rounded >= 2.0 and rounded < 100.0:
                job.eta_sec = round(elapsed * (100.0 - rounded) / rounded, 1)
            elif rounded >= 100.0:
                job.eta_sec = 0.0
            app.store.save_job(job)

    handle = app.controller.create_handle(job_id)
    try:
        artifacts = await app.pipeline.render_job(
            job_id=job.job_id,
            sources=sources,
            operations=parsed_ops,
            output_profile=job.output_profile,
            watermark_sources=watermark_sources,
            voice_reference_sources=voice_reference_sources,
            progress_cb=_on_progress,
            control=handle,
        )
        job.artifacts = artifacts
        job.progress_pct = 100.0
        job.progress_stage = "Complete"
        job.eta_sec = 0.0
        job.status = JobStatus.READY_FOR_REVIEW
        app.store.save_job(job)
        app.store.log_activity(
            category="render",
            message=f"Rendered {len(artifacts)} artifacts for '{job.title}'",
            job_id=job.job_id,
            details={"artifact_kinds": [a.kind for a in artifacts]},
        )
        return {"job": job.model_dump()}
    except RenderCancelledError:
        job.status = JobStatus.CANCELLED
        job.progress_stage = "Cancelled"
        job.eta_sec = None
        job.error = "Cancelled by user"
        app.store.save_job(job)
        app.store.log_activity(
            category="render",
            level="warning",
            message=f"Render cancelled for '{job.title}'",
            job_id=job.job_id,
        )
        return {"job": job.model_dump()}
    except Exception as exc:
        if handle.is_cancelled():
            job.status = JobStatus.CANCELLED
            job.progress_stage = "Cancelled"
            job.eta_sec = None
            job.error = "Cancelled by user"
            app.store.save_job(job)
            app.store.log_activity(
                category="render",
                level="warning",
                message=f"Render cancelled for '{job.title}'",
                job_id=job.job_id,
            )
            return {"job": job.model_dump()}
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
    finally:
        app.controller.remove_handle(job_id)


def pause_job(app: AppContext, job_id: str) -> dict[str, Any]:
    """Pause an actively rendering job."""
    job = app.store.get_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    if job.status != JobStatus.RENDERING:
        raise ValueError(f"Job '{job_id}' is not rendering (status: '{job.status.value}').")
    handle = app.controller.get_handle(job_id)
    if handle is None:
        raise ValueError(f"No active render handle found for job '{job_id}'.")
    handle.pause()
    job.status = JobStatus.PAUSED
    job.progress_stage = "Paused"
    app.store.save_job(job)
    app.store.log_activity(
        category="render",
        level="warning",
        message=f"Paused rendering job '{job.title}' at {job.progress_pct:.0f}%",
        job_id=job.job_id,
    )
    return {"job": job.model_dump()}


def resume_job(app: AppContext, job_id: str) -> dict[str, Any]:
    """Resume a paused rendering job."""
    job = app.store.get_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    if job.status != JobStatus.PAUSED:
        raise ValueError(f"Job '{job_id}' is not paused (status: '{job.status.value}').")
    handle = app.controller.get_handle(job_id)
    if handle is None:
        raise ValueError(f"No active render handle found for job '{job_id}'.")
    handle.resume()
    job.status = JobStatus.RENDERING
    job.progress_stage = "Resuming"
    app.store.save_job(job)
    app.store.log_activity(
        category="render",
        message=f"Resumed rendering job '{job.title}' from {job.progress_pct:.0f}%",
        job_id=job.job_id,
    )
    return {"job": job.model_dump()}


def cancel_job(app: AppContext, job_id: str) -> dict[str, Any]:
    """Cancel an active or paused rendering job."""
    job = app.store.get_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    if job.status not in {JobStatus.RENDERING, JobStatus.PAUSED}:
        raise ValueError(f"Job '{job_id}' cannot be cancelled from '{job.status.value}'.")
    handle = app.controller.get_handle(job_id)
    if handle is not None:
        handle.cancel()
    job.status = JobStatus.CANCELLED
    job.progress_stage = "Cancelled"
    job.eta_sec = None
    job.error = "Cancelled by user"
    app.store.save_job(job)
    app.store.log_activity(
        category="render",
        level="warning",
        message=f"Cancelled job '{job.title}'",
        job_id=job.job_id,
    )
    return {"job": job.model_dump()}


def update_edit_job(
    app: AppContext,
    job_id: str,
    title: str | None = None,
    operations: list[dict[str, Any]] | None = None,
    output_profile: str | None = None,
) -> dict[str, Any]:
    """Update a job's plan and reset status to DRAFT, clearing stale approvals/artifacts."""
    job = app.store.get_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    if job.status in {JobStatus.RENDERING, JobStatus.PAUSED, JobStatus.PUBLISHED}:
        raise ValueError(f"Cannot modify job '{job_id}' while status is '{job.status.value}'.")

    if title is not None:
        job.title = title
    if operations is not None:
        parsed_ops = _OP_ADAPTER.validate_python(operations)
        job.operations = [op.model_dump() for op in parsed_ops]
    if output_profile is not None:
        job.output_profile = OutputProfile(output_profile)

    job.status = JobStatus.DRAFT
    job.approval_id = None
    job.artifacts = []
    job.error = None
    app.store.save_job(job)
    app.store.log_activity(
        category="job",
        message=f"Updated edit job '{job.title}' and reset to draft",
        job_id=job.job_id,
    )
    return {"job": job.model_dump()}


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

