"""Shared application context holding settings, store, resolver, pipeline, and publisher."""

from __future__ import annotations

from dataclasses import dataclass

from video_mcp.config import Settings
from video_mcp.media.ffmpeg_runner import FFmpegRunner
from video_mcp.media.pipeline import VideoPipeline
from video_mcp.publishing.publisher import PublishingService
from video_mcp.sources.resolver import SourceResolver
from video_mcp.storage.job_store import JobStore


@dataclass
class AppContext:
    """Dependency container shared across MCP tools and resources."""

    settings: Settings
    store: JobStore
    runner: FFmpegRunner
    resolver: SourceResolver
    pipeline: VideoPipeline
    publisher: PublishingService

    @classmethod
    def create(cls, settings: Settings | None = None) -> AppContext:
        cfg = settings or Settings.from_env()
        cfg.ensure_directories()
        store = JobStore(cfg.db_path)
        runner = FFmpegRunner(
            ffmpeg_bin=cfg.ffmpeg_bin,
            ffprobe_bin=cfg.ffprobe_bin,
            timeout_sec=cfg.ffmpeg_timeout_sec,
        )
        resolver = SourceResolver(cfg, runner)
        pipeline = VideoPipeline(runner, cfg.workspace_dir)
        publisher = PublishingService(cfg)
        return cls(
            settings=cfg,
            store=store,
            runner=runner,
            resolver=resolver,
            pipeline=pipeline,
            publisher=publisher,
        )

    def close(self) -> None:
        self.store.close()

