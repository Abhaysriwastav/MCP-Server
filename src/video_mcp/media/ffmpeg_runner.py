"""Async FFmpeg and FFprobe subprocess runner with timeouts and structured errors."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any


class FFmpegError(RuntimeError):
    """Raised when an ffmpeg or ffprobe invocation fails or times out."""

    def __init__(self, message: str, returncode: int | None = None, stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


def sha256_file(path: Path) -> str:
    """Compute hex SHA-256 digest of a file in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class FFmpegRunner:
    """Thin async wrapper around `ffmpeg` and `ffprobe` binaries."""

    def __init__(
        self,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
        timeout_sec: int = 600,
    ) -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.timeout_sec = timeout_sec

    def ensure_binaries(self) -> None:
        """Verify that both ffmpeg and ffprobe are executable on PATH or absolute path."""
        for label, binary in (("ffmpeg", self.ffmpeg_bin), ("ffprobe", self.ffprobe_bin)):
            if shutil.which(binary) is None and not Path(binary).is_file():
                raise FFmpegError(f"{label} binary not found: {binary}")

    def has_filter(self, filter_name: str) -> bool:
        """Return True if the configured ffmpeg binary includes `filter_name`."""
        try:
            proc = subprocess.run(
                [self.ffmpeg_bin, "-hide_banner", "-filters"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return any(
                f" {filter_name} " in line for line in proc.stdout.splitlines()
            )
        except Exception:
            return False

    async def probe(self, media_path: Path) -> dict[str, Any]:
        """Run ffprobe on a media file and return normalized stream/format metadata."""
        self.ensure_binaries()
        if not media_path.is_file():
            raise FFmpegError(f"Media file does not exist: {media_path}")

        args = [
            self.ffprobe_bin,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(media_path),
        ]
        stdout, stderr, rc = await self._exec(args, timeout=min(self.timeout_sec, 60))
        if rc != 0:
            raise FFmpegError(f"ffprobe failed for {media_path.name}", rc, stderr)

        raw = json.loads(stdout.decode("utf-8"))
        streams = raw.get("streams", [])
        fmt = raw.get("format", {})
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        return {
            "filename": media_path.name,
            "format_name": fmt.get("format_name"),
            "duration_sec": float(fmt["duration"]) if fmt.get("duration") else None,
            "size_bytes": int(fmt["size"]) if fmt.get("size") else media_path.stat().st_size,
            "bit_rate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
            "has_video": video_stream is not None,
            "has_audio": audio_stream is not None,
            "video": (
                {
                    "codec": video_stream.get("codec_name"),
                    "width": video_stream.get("width"),
                    "height": video_stream.get("height"),
                    "r_frame_rate": video_stream.get("r_frame_rate"),
                    "pix_fmt": video_stream.get("pix_fmt"),
                }
                if video_stream
                else None
            ),
            "audio": (
                {
                    "codec": audio_stream.get("codec_name"),
                    "sample_rate": audio_stream.get("sample_rate"),
                    "channels": audio_stream.get("channels"),
                }
                if audio_stream
                else None
            ),
        }

    async def run_ffmpeg(
        self,
        args: list[str],
        timeout: int | None = None,
        progress_cb: Callable[[float], None] | None = None,
        duration_sec: float | None = None,
    ) -> None:
        """Execute an ffmpeg command, optionally streaming 0..1 progress via `-progress pipe:1`."""
        self.ensure_binaries()
        effective_timeout = timeout or self.timeout_sec
        if progress_cb is not None and duration_sec and duration_sec > 0:
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostats",
                "-progress",
                "pipe:1",
                *args,
            ]
            stderr, rc = await self._exec_with_progress(
                cmd, timeout=effective_timeout, duration_sec=duration_sec, progress_cb=progress_cb
            )
        else:
            cmd = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", *args]
            _, stderr, rc = await self._exec(cmd, timeout=effective_timeout)
        if rc != 0:
            raise FFmpegError(f"ffmpeg failed (exit {rc}): {stderr}", rc, stderr)

    async def _exec_with_progress(
        self,
        cmd: list[str],
        timeout: int,
        duration_sec: float,
        progress_cb: Callable[[float], None],
    ) -> tuple[str, int]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        total_us = max(1.0, duration_sec * 1_000_000.0)

        async def _read_progress() -> None:
            assert proc.stdout is not None
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if line.startswith("out_time_us="):
                    raw = line.split("=", 1)[1].strip()
                    if raw.isdigit():
                        progress_cb(min(1.0, max(0.0, int(raw) / total_us)))
                elif line == "progress=end":
                    progress_cb(1.0)

        try:
            _, stderr_bytes = await asyncio.wait_for(
                asyncio.gather(_read_progress(), proc.stderr.read() if proc.stderr else asyncio.sleep(0)),
                timeout=timeout,
            )
            rc = await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise FFmpegError(f"Command timed out after {timeout}s: {cmd[0]}") from exc
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        return stderr[-2000:], rc or 0

    async def _exec(self, cmd: list[str], timeout: int) -> tuple[bytes, str, int]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise FFmpegError(f"Command timed out after {timeout}s: {cmd[0]}") from exc
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        return stdout, stderr[-2000:], proc.returncode or 0

