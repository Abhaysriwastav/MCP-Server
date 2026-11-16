"""Approval-gated publishing tools."""

from __future__ import annotations

from typing import Any

from video_mcp.context import AppContext
from video_mcp.models import JobStatus


async def publish_job(
    app: AppContext,
    job_id: str,
    target: str = "local_release",
    destination: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publish an APPROVED job to local_release, webhook, or s3."""
    job = app.store.get_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")

    approval = app.store.get_approval(job.approval_id) if job.approval_id else None
    result = await app.publisher.publish(
        job=job,
        approval=approval,
        target=target,
        destination=destination,
        dry_run=dry_run,
    )

    if not dry_run:
        job.publish_records.append(result)
        job.status = JobStatus.PUBLISHED
        app.store.save_job(job)
        app.store.log_activity(
            category="publish",
            message=f"Published '{job.title}' to {target}",
            job_id=job.job_id,
            details={"target": target, "destination": destination},
        )

    return {"job_id": job.job_id, "job_status": job.status.value, "publish": result}


def list_publish_targets(app: AppContext) -> dict[str, Any]:
    """Describe available publishing targets and their configuration status."""
    return {
        "targets": [
            {
                "name": "local_release",
                "configured": True,
                "default_destination": str(app.settings.release_dir),
            },
            {
                "name": "webhook",
                "configured": bool(app.settings.webhook_url),
                "default_destination": app.settings.webhook_url,
            },
            {
                "name": "s3",
                "configured": True,
                "note": "Requires s3://bucket/prefix destination and boto3 extra.",
            },
        ]
    }

