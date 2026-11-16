"""Approval-gated publishing engine with integrity verification."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from video_mcp.config import Settings
from video_mcp.media.ffmpeg_runner import sha256_file
from video_mcp.models import (
    ApprovalDecision,
    ApprovalRecord,
    EditJob,
    JobStatus,
    utc_now_iso,
)


class PublishError(RuntimeError):
    """Raised when publishing is blocked by approval policy, integrity check, or target error."""


class PublishingService:
    """Publishes only human-approved jobs whose artifacts match the approved checksum snapshot."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def verify_approval_integrity(self, job: EditJob, approval: ApprovalRecord | None) -> None:
        """Enforce that the job is APPROVED and no rendered artifact has been modified."""
        if job.status != JobStatus.APPROVED:
            raise PublishError(
                f"Job '{job.job_id}' cannot be published from status '{job.status.value}'. "
                "Human approval is required first."
            )
        if approval is None or approval.decision != ApprovalDecision.APPROVED:
            raise PublishError(
                f"Job '{job.job_id}' lacks a valid APPROVED record."
            )
        if not job.artifacts:
            raise PublishError(f"Job '{job.job_id}' has no rendered artifacts to publish.")

        for artifact in job.artifacts:
            path = Path(artifact.path)
            if not path.is_file():
                raise PublishError(f"Missing artifact file: {artifact.path}")
            expected_sha = approval.artifact_checksums.get(artifact.artifact_id)
            if not expected_sha:
                raise PublishError(
                    f"Artifact '{artifact.artifact_id}' was not part of the approved snapshot."
                )
            actual_sha = sha256_file(path)
            if actual_sha != expected_sha:
                raise PublishError(
                    f"Integrity mismatch for artifact '{artifact.artifact_id}': "
                    f"expected {expected_sha[:12]}..., got {actual_sha[:12]}..."
                )

    async def publish(
        self,
        job: EditJob,
        approval: ApprovalRecord | None,
        target: str = "local_release",
        destination: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Publish an approved job to `local_release`, `webhook`, or `s3`."""
        self.verify_approval_integrity(job, approval)
        assert approval is not None

        if target == "local_release":
            return await self._publish_local(job, approval, destination, dry_run)
        if target == "webhook":
            return await self._publish_webhook(job, approval, destination, dry_run)
        if target == "s3":
            return await self._publish_s3(job, approval, destination, dry_run)
        raise PublishError(f"Unknown publish target: '{target}'")

    async def _publish_local(
        self,
        job: EditJob,
        approval: ApprovalRecord,
        destination: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        dest_root = (
            Path(destination).expanduser().resolve()
            if destination
            else (self.settings.release_dir / job.job_id)
        )
        planned_files = [
            {"source": a.path, "dest": str(dest_root / Path(a.path).name), "kind": a.kind}
            for a in job.artifacts
        ]
        if dry_run:
            return {
                "target": "local_release",
                "dry_run": True,
                "release_dir": str(dest_root),
                "files": planned_files,
            }

        dest_root.mkdir(parents=True, exist_ok=True)
        copied: list[dict[str, str]] = []
        for artifact in job.artifacts:
            src = Path(artifact.path)
            dst = dest_root / src.name
            await asyncio.to_thread(shutil.copy2, src, dst)
            copied.append({"kind": artifact.kind, "path": str(dst), "sha256": artifact.sha256})

        cert_path = dest_root / "approval_certificate.json"
        cert = {
            "job_id": job.job_id,
            "title": job.title,
            "approval_id": approval.approval_id,
            "reviewer": approval.reviewer,
            "notes": approval.notes,
            "decided_at": approval.decided_at,
            "published_at": utc_now_iso(),
            "artifacts": copied,
        }
        cert_path.write_text(json.dumps(cert, indent=2), encoding="utf-8")

        return {
            "target": "local_release",
            "dry_run": False,
            "release_dir": str(dest_root),
            "approval_certificate": str(cert_path),
            "published_files": copied,
            "published_at": cert["published_at"],
        }

    async def _publish_webhook(
        self,
        job: EditJob,
        approval: ApprovalRecord,
        destination: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        url = destination or self.settings.webhook_url
        if not url:
            raise PublishError(
                "No webhook URL provided and VIDEO_MCP_WEBHOOK_URL is not configured."
            )
        payload = {
            "event": "video.job.published",
            "job_id": job.job_id,
            "title": job.title,
            "output_profile": job.output_profile.value,
            "approval": approval.model_dump(),
            "artifacts": [a.model_dump() for a in job.artifacts],
            "published_at": utc_now_iso(),
        }
        if dry_run:
            return {"target": "webhook", "dry_run": True, "url": url, "payload": payload}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                raise PublishError(f"Webhook returned HTTP {resp.status_code}: {resp.text[:300]}")
        return {
            "target": "webhook",
            "dry_run": False,
            "url": url,
            "status_code": resp.status_code,
            "published_at": payload["published_at"],
        }

    async def _publish_s3(
        self,
        job: EditJob,
        approval: ApprovalRecord,
        destination: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        if not destination or not destination.startswith("s3://"):
            raise PublishError("S3 publish requires destination like 's3://bucket/prefix'.")
        parsed = urlparse(destination)
        bucket = parsed.netloc
        prefix = parsed.path.strip("/")

        keys = [
            {
                "local": a.path,
                "s3_uri": f"s3://{bucket}/{prefix}/{job.job_id}/{Path(a.path).name}".replace(
                    "//", "/"
                ).replace("s3:/", "s3://"),
            }
            for a in job.artifacts
        ]
        if dry_run:
            return {"target": "s3", "dry_run": True, "uploads": keys}

        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:
            raise PublishError(
                "S3 publish requested but boto3 is not installed. "
                "Install with: pip install 'video-automation-mcp[s3]'"
            ) from exc

        def _upload_all() -> None:
            client = boto3.client("s3")
            for artifact in job.artifacts:
                key = f"{prefix}/{job.job_id}/{Path(artifact.path).name}".lstrip("/")
                client.upload_file(artifact.path, bucket, key)

        await asyncio.to_thread(_upload_all)
        return {
            "target": "s3",
            "dry_run": False,
            "approval_id": approval.approval_id,
            "uploads": keys,
            "published_at": utc_now_iso(),
        }

