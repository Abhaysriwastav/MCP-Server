"""Human-in-the-loop approval workflow tools."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from video_mcp.context import AppContext
from video_mcp.media.ffmpeg_runner import sha256_file
from video_mcp.models import (
    ApprovalDecision,
    ApprovalRecord,
    JobStatus,
    utc_now_iso,
)


def request_approval(
    app: AppContext,
    job_id: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Stage a rendered job for human approval and snapshot artifact SHA-256 checksums."""
    job = app.store.get_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    if job.status not in {JobStatus.READY_FOR_REVIEW, JobStatus.REJECTED}:
        raise ValueError(
            f"Job '{job_id}' must be 'ready_for_review' or 'rejected' to request approval "
            f"(current: '{job.status.value}')."
        )
    if not job.artifacts:
        raise ValueError(f"Job '{job_id}' has no rendered artifacts to approve.")

    checksums: dict[str, str] = {}
    for artifact in job.artifacts:
        path = Path(artifact.path)
        if not path.is_file():
            raise FileNotFoundError(f"Artifact missing on disk: {artifact.path}")
        checksums[artifact.artifact_id] = sha256_file(path)

    record = ApprovalRecord(
        approval_id=f"apr_{uuid.uuid4().hex[:12]}",
        job_id=job.job_id,
        decision=ApprovalDecision.PENDING,
        notes=notes,
        artifact_checksums=checksums,
    )
    app.store.save_approval(record)

    job.approval_id = record.approval_id
    job.status = JobStatus.PENDING_APPROVAL
    app.store.save_job(job)
    app.store.log_activity(
        category="approval",
        message=f"Approval requested for '{job.title}'",
        job_id=job.job_id,
        details={"approval_id": record.approval_id, "notes": notes},
    )
    return {
        "approval": record.model_dump(),
        "review_summary": {
            "job_id": job.job_id,
            "title": job.title,
            "output_profile": job.output_profile.value,
            "artifacts": [
                {"artifact_id": a.artifact_id, "kind": a.kind, "path": a.path}
                for a in job.artifacts
            ],
        },
    }


def approve_job(
    app: AppContext,
    approval_id: str,
    reviewer: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Approve a pending job, unlocking publishing."""
    if not reviewer.strip():
        raise ValueError("reviewer is required.")
    record = app.store.get_approval(approval_id)
    if record is None:
        raise ValueError(f"Approval record not found: {approval_id}")
    if record.decision != ApprovalDecision.PENDING:
        raise ValueError(
            f"Approval '{approval_id}' is already finalized as '{record.decision.value}'."
        )

    job = app.store.get_job(record.job_id)
    if job is None:
        raise ValueError(f"Job not found: {record.job_id}")

    record.decision = ApprovalDecision.APPROVED
    record.reviewer = reviewer.strip()
    record.notes = notes
    record.decided_at = utc_now_iso()
    app.store.save_approval(record)

    job.status = JobStatus.APPROVED
    app.store.save_job(job)
    app.store.log_activity(
        category="approval",
        message=f"Job '{job.title}' approved by {record.reviewer}",
        job_id=job.job_id,
        details={"approval_id": record.approval_id, "notes": notes},
    )
    return {"approval": record.model_dump(), "job_status": job.status.value}


def reject_job(
    app: AppContext,
    approval_id: str,
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    """Reject a pending job with reviewer feedback; job can be re-edited and re-rendered."""
    if not reviewer.strip():
        raise ValueError("reviewer is required.")
    if not reason.strip():
        raise ValueError("reason is required when rejecting a job.")

    record = app.store.get_approval(approval_id)
    if record is None:
        raise ValueError(f"Approval record not found: {approval_id}")
    if record.decision != ApprovalDecision.PENDING:
        raise ValueError(
            f"Approval '{approval_id}' is already finalized as '{record.decision.value}'."
        )

    job = app.store.get_job(record.job_id)
    if job is None:
        raise ValueError(f"Job not found: {record.job_id}")

    record.decision = ApprovalDecision.REJECTED
    record.reviewer = reviewer.strip()
    record.notes = reason.strip()
    record.decided_at = utc_now_iso()
    app.store.save_approval(record)

    job.status = JobStatus.REJECTED
    app.store.save_job(job)
    app.store.log_activity(
        category="approval",
        level="warning",
        message=f"Job '{job.title}' rejected by {record.reviewer}: {record.notes}",
        job_id=job.job_id,
        details={"approval_id": record.approval_id},
    )
    return {"approval": record.model_dump(), "job_status": job.status.value}


def get_approval_status(app: AppContext, approval_id: str) -> dict[str, Any]:
    """Retrieve an approval record and its current decision."""
    record = app.store.get_approval(approval_id)
    if record is None:
        raise ValueError(f"Approval record not found: {approval_id}")
    return {"approval": record.model_dump()}


def list_pending_approvals(app: AppContext, limit: int = 50) -> dict[str, Any]:
    """List all jobs currently awaiting human approval."""
    records = app.store.list_approvals(decision=ApprovalDecision.PENDING, limit=limit)
    return {"count": len(records), "approvals": [r.model_dump() for r in records]}

