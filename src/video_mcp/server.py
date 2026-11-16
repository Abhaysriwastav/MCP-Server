"""FastMCP server entrypoint for Video Automation MCP."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from video_mcp.config import Settings
from video_mcp.context import AppContext
from video_mcp.tools import approval, editing, ingest, publishing


def build_server(settings: Settings | None = None) -> FastMCP:
    """Create and configure the FastMCP server instance."""
    cfg = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[AppContext]:
        app = AppContext.create(cfg)
        try:
            yield app
        finally:
            app.close()

    mcp = FastMCP(
        name="video-automation-mcp",
        instructions=(
            "Video editing automation server with mixed-source ingest (local/HTTP/S3), "
            "dual-format (16:9 + 9:16) & structured metadata output, and mandatory "
            "human-in-the-loop approval before publishing."
        ),
        lifespan=lifespan,
        host=cfg.host,
        port=cfg.port,
    )

    def _app(ctx: Context) -> AppContext:
        return ctx.request_context.lifespan_context

    # ------------------------------------------------------------------
    # Mixed-Source Ingest & Inspection Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def ingest_source(
        ctx: Context,
        uri: str,
        probe_media: bool = True,
    ) -> dict[str, Any]:
        """Resolve a local path, http(s):// URL, or s3:// URI into the workspace."""
        return await ingest.ingest_source(_app(ctx), uri=uri, probe_media=probe_media)

    @mcp.tool()
    async def probe_media(ctx: Context, source_id_or_path: str) -> dict[str, Any]:
        """Inspect video/audio streams, duration, and resolution using ffprobe."""
        return await ingest.probe_media(_app(ctx), source_id_or_path=source_id_or_path)

    @mcp.tool()
    def list_sources(ctx: Context, limit: int = 50) -> dict[str, Any]:
        """List recently ingested media sources."""
        return ingest.list_sources(_app(ctx), limit=limit)

    # ------------------------------------------------------------------
    # Video Editing & Dual-Output Rendering Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def create_edit_job(
        ctx: Context,
        title: str,
        source_ids: list[str],
        operations: list[dict[str, Any]] | None = None,
        output_profile: str = "both",
    ) -> dict[str, Any]:
        """Create a DRAFT video editing job.

        output_profile: 'landscape_16x9', 'vertical_9x16', or 'both' (default).
        operations: list of dicts with 'op' in {trim, scale, reframe, audio_normalize,
                    fade, speed, text_overlay, watermark, burn_subtitles}.
        """
        return editing.create_edit_job(
            _app(ctx),
            title=title,
            source_ids=source_ids,
            operations=operations,
            output_profile=output_profile,
        )

    @mcp.tool()
    async def render_edit_job(ctx: Context, job_id: str) -> dict[str, Any]:
        """Render the edit job into video renditions, thumbnails, probe.json, and manifest.json."""
        return await editing.render_edit_job(_app(ctx), job_id=job_id)

    @mcp.tool()
    def get_job_status(ctx: Context, job_id: str) -> dict[str, Any]:
        """Get current status, rendered artifacts, and approval linkage for a job."""
        return editing.get_job_status(_app(ctx), job_id=job_id)

    @mcp.tool()
    def list_jobs(
        ctx: Context,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List edit jobs, optionally filtered by status."""
        return editing.list_jobs(_app(ctx), status=status, limit=limit)

    @mcp.tool()
    async def generate_thumbnail(
        ctx: Context,
        source_id: str,
        timestamp_sec: float = 0.5,
    ) -> dict[str, Any]:
        """Extract a preview JPEG frame from a registered source."""
        return await editing.generate_thumbnail(
            _app(ctx), source_id=source_id, timestamp_sec=timestamp_sec
        )

    # ------------------------------------------------------------------
    # Human-in-the-Loop Approval Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def request_approval(
        ctx: Context,
        job_id: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Submit a rendered job for human approval, snapshotting artifact checksums."""
        return approval.request_approval(_app(ctx), job_id=job_id, notes=notes)

    @mcp.tool()
    def approve_job(
        ctx: Context,
        approval_id: str,
        reviewer: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Approve a pending job so it can be published."""
        return approval.approve_job(
            _app(ctx), approval_id=approval_id, reviewer=reviewer, notes=notes
        )

    @mcp.tool()
    def reject_job(
        ctx: Context,
        approval_id: str,
        reviewer: str,
        reason: str,
    ) -> dict[str, Any]:
        """Reject a pending job with reviewer feedback."""
        return approval.reject_job(
            _app(ctx), approval_id=approval_id, reviewer=reviewer, reason=reason
        )

    @mcp.tool()
    def get_approval_status(ctx: Context, approval_id: str) -> dict[str, Any]:
        """Fetch an approval record by ID."""
        return approval.get_approval_status(_app(ctx), approval_id=approval_id)

    @mcp.tool()
    def list_pending_approvals(ctx: Context, limit: int = 50) -> dict[str, Any]:
        """List all approval requests currently awaiting human review."""
        return approval.list_pending_approvals(_app(ctx), limit=limit)

    # ------------------------------------------------------------------
    # Approval-Gated Publishing Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def publish_job(
        ctx: Context,
        job_id: str,
        target: str = "local_release",
        destination: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Publish an APPROVED job to local_release, webhook, or s3."""
        return await publishing.publish_job(
            _app(ctx),
            job_id=job_id,
            target=target,
            destination=destination,
            dry_run=dry_run,
        )

    @mcp.tool()
    def list_publish_targets(ctx: Context) -> dict[str, Any]:
        """List available publishing targets and configuration status."""
        return publishing.list_publish_targets(_app(ctx))

    # ------------------------------------------------------------------
    # MCP Resources & Prompts
    # ------------------------------------------------------------------

    @mcp.resource("video://jobs/{job_id}")
    def job_resource(ctx: Context, job_id: str) -> str:
        """Read-only JSON resource for an edit job and its artifacts."""
        return json.dumps(editing.get_job_status(_app(ctx), job_id=job_id), indent=2)

    @mcp.resource("video://approvals/pending")
    def pending_approvals_resource(ctx: Context) -> str:
        """Read-only JSON resource listing all pending approval requests."""
        return json.dumps(approval.list_pending_approvals(_app(ctx)), indent=2)

    @mcp.prompt()
    def review_and_approve_video(job_id: str) -> str:
        """Prompt template guiding a human-in-the-loop review before publishing."""
        return (
            f"Inspect video job '{job_id}' using get_job_status. Verify that both "
            "16:9 and 9:16 renditions (plus thumbnails and manifest.json) are present "
            "and meet quality requirements. Summarize the probe metadata and preview "
            "paths for the human reviewer, then call request_approval and wait for "
            "explicit human confirmation before calling approve_job and publish_job."
        )

    return mcp


def main() -> None:
    """CLI entrypoint for `video-automation-mcp`."""
    settings = Settings.from_env()
    server = build_server(settings)
    server.run(transport=settings.transport)


if __name__ == "__main__":
    main()

