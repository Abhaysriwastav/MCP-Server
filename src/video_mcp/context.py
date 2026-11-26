"""Shared application context holding settings, store, resolver, pipeline, and publisher."""

from __future__ import annotations

from dataclasses import dataclass

from video_mcp.config import Settings
from video_mcp.media.ffmpeg_runner import FFmpegRunner
from video_mcp.media.pipeline import VideoPipeline
from video_mcp.media.transcriber import Transcriber
from video_mcp.media.voice_cloner import VoiceCloner
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
    transcriber: Transcriber
    voice_cloner: VoiceCloner
    pipeline: VideoPipeline
    publisher: PublishingService

    @classmethod
    def create(cls, settings: Settings | None = None) -> AppContext:
        cfg = settings or Settings.from_env()
        cfg.ensure_directories()
        store = JobStore(cfg.db_path)
        store.recover_stale_rendering_jobs()
        runner = FFmpegRunner(
            ffmpeg_bin=cfg.ffmpeg_bin,
            ffprobe_bin=cfg.ffprobe_bin,
            timeout_sec=cfg.ffmpeg_timeout_sec,
            hwaccel=cfg.ffmpeg_hwaccel,
        )
        resolver = SourceResolver(cfg, runner)
        transcriber = Transcriber(cfg)
        voice_cloner = VoiceCloner(cfg, runner)
        pipeline = VideoPipeline(
            runner,
            cfg.workspace_dir,
            transcriber=transcriber,
            voice_cloner=voice_cloner,
            default_max_words_per_line=cfg.subtitle_max_words_per_line,
        )
        publisher = PublishingService(cfg)
        return cls(
            settings=cfg,
            store=store,
            runner=runner,
            resolver=resolver,
            transcriber=transcriber,
            voice_cloner=voice_cloner,
            pipeline=pipeline,
            publisher=publisher,
        )

    def close(self) -> None:
        self.store.close()

