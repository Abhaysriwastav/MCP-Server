"""Configuration settings for the Video Automation MCP server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


def _env_paths(name: str, default: list[Path]) -> list[Path]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [Path(p.strip()).expanduser().resolve() for p in raw.split(",") if p.strip()]


class Settings(BaseModel):
    """Runtime configuration loaded from environment variables (VIDEO_MCP_*)."""

    workspace_dir: Path = Field(default=Path("./workspace"))
    db_path: Path = Field(default=Path("./workspace/video_mcp.db"))
    allowed_local_roots: list[Path] = Field(default_factory=lambda: [Path(".").resolve()])

    ffmpeg_bin: str = Field(default="ffmpeg")
    ffprobe_bin: str = Field(default="ffprobe")
    ffmpeg_timeout_sec: int = Field(default=600, ge=10)

    max_download_mb: int = Field(default=1024, ge=1)
    max_download_bytes: int | None = Field(default=None, ge=1)
    download_timeout_sec: int = Field(default=120, ge=5)
    allow_private_urls: bool = Field(default=False)

    # YouTube & Whisper transcription / captioning
    whisper_model: str = Field(default="base")
    whisper_device: str = Field(default="cpu")
    whisper_compute_type: str = Field(default="int8")
    youtube_max_duration_sec: int = Field(default=7200, ge=1)
    subtitle_max_words_per_line: int = Field(default=6, ge=1, le=20)

    # AI Voice Cloning
    voice_provider: Literal["coqui", "elevenlabs"] = Field(default="coqui")
    coqui_model: str = Field(default="tts_models/multilingual/multi-dataset/xtts_v2")
    elevenlabs_api_key: str | None = Field(default=None)
    elevenlabs_voice_id: str | None = Field(default=None)

    release_dir: Path = Field(default=Path("./workspace/releases"))
    webhook_url: str | None = Field(default=None)

    transport: Literal["stdio", "streamable-http"] = Field(default="stdio")
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings from `VIDEO_MCP_*` environment variables."""
        workspace = Path(os.getenv("VIDEO_MCP_WORKSPACE_DIR", "./workspace")).expanduser().resolve()
        db_default = workspace / "video_mcp.db"
        release_default = workspace / "releases"
        transport_raw = os.getenv("VIDEO_MCP_TRANSPORT", "stdio").strip().lower()
        transport: Literal["stdio", "streamable-http"] = (
            "streamable-http" if transport_raw == "streamable-http" else "stdio"
        )
        return cls(
            workspace_dir=workspace,
            db_path=Path(os.getenv("VIDEO_MCP_DB_PATH", str(db_default))).expanduser().resolve(),
            allowed_local_roots=_env_paths(
                "VIDEO_MCP_ALLOWED_LOCAL_ROOTS",
                [Path(".").resolve(), workspace],
            ),
            ffmpeg_bin=os.getenv("VIDEO_MCP_FFMPEG_BIN", "ffmpeg"),
            ffprobe_bin=os.getenv("VIDEO_MCP_FFPROBE_BIN", "ffprobe"),
            ffmpeg_timeout_sec=_env_int("VIDEO_MCP_FFMPEG_TIMEOUT_SEC", 600),
            max_download_mb=_env_int("VIDEO_MCP_MAX_DOWNLOAD_MB", 1024),
            max_download_bytes=(
                int(os.environ["VIDEO_MCP_MAX_DOWNLOAD_BYTES"])
                if os.getenv("VIDEO_MCP_MAX_DOWNLOAD_BYTES")
                else None
            ),
            download_timeout_sec=_env_int("VIDEO_MCP_DOWNLOAD_TIMEOUT_SEC", 120),
            allow_private_urls=_env_bool("VIDEO_MCP_ALLOW_PRIVATE_URLS", False),
            whisper_model=os.getenv("VIDEO_MCP_WHISPER_MODEL", "base"),
            whisper_device=os.getenv("VIDEO_MCP_WHISPER_DEVICE", "cpu"),
            whisper_compute_type=os.getenv("VIDEO_MCP_WHISPER_COMPUTE_TYPE", "int8"),
            youtube_max_duration_sec=_env_int("VIDEO_MCP_YOUTUBE_MAX_DURATION_SEC", 7200),
            subtitle_max_words_per_line=_env_int("VIDEO_MCP_SUBTITLE_MAX_WORDS_PER_LINE", 6),
            voice_provider=(
                "elevenlabs"
                if os.getenv("VIDEO_MCP_VOICE_PROVIDER", "coqui").strip().lower() == "elevenlabs"
                else "coqui"
            ),
            coqui_model=os.getenv(
                "VIDEO_MCP_COQUI_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2"
            ),
            elevenlabs_api_key=os.getenv("VIDEO_MCP_ELEVENLABS_API_KEY") or None,
            elevenlabs_voice_id=os.getenv("VIDEO_MCP_ELEVENLABS_VOICE_ID") or None,
            release_dir=Path(
                os.getenv("VIDEO_MCP_RELEASE_DIR", str(release_default))
            ).expanduser().resolve(),
            webhook_url=os.getenv("VIDEO_MCP_WEBHOOK_URL") or None,
            transport=transport,
            host=os.getenv("VIDEO_MCP_HOST", "127.0.0.1"),
            port=_env_int("VIDEO_MCP_PORT", 8000),
        )

    @property
    def effective_max_download_bytes(self) -> int:
        if self.max_download_bytes is not None:
            return self.max_download_bytes
        return self.max_download_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        """Create required workspace subdirectories if they do not exist."""
        for directory in (
            self.workspace_dir,
            self.workspace_dir / "sources",
            self.workspace_dir / "renders",
            self.workspace_dir / "thumbnails",
            self.release_dir,
            self.db_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)

