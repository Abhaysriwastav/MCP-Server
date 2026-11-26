"""Mixed-source resolver supporting local paths, HTTP(S) downloads, and S3 URIs."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from video_mcp.config import Settings
from video_mcp.media.ffmpeg_runner import FFmpegRunner, sha256_file
from video_mcp.models import SourceAsset, SourceKind


class SourceResolutionError(RuntimeError):
    """Raised when a local, HTTP(S), or cloud source cannot be resolved safely."""


_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def is_youtube_url(url: str) -> bool:
    """Return True if `url` is an http(s) YouTube watch, share, or shorts URL."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return host in _YOUTUBE_HOSTS or host.endswith(".youtube.com")


def _is_forbidden_ip(ip_str: str) -> bool:
    addr = ipaddress.ip_address(ip_str)
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _validate_public_url(url: str, allow_private: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SourceResolutionError(f"Unsupported URL scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise SourceResolutionError("URL must include a hostname.")
    if allow_private:
        return

    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SourceResolutionError(f"DNS resolution failed for {parsed.hostname}: {exc}") from exc

    for info in infos:
        ip_str = info[4][0]
        if _is_forbidden_ip(ip_str):
            raise SourceResolutionError(
                f"Blocked private/loopback destination {ip_str} for {parsed.hostname}"
            )


class SourceResolver:
    """Resolves mixed media sources (local, HTTP/HTTPS, S3) into the workspace."""

    def __init__(self, settings: Settings, runner: FFmpegRunner) -> None:
        self.settings = settings
        self.runner = runner

    async def resolve(self, uri: str, probe_media: bool = True) -> SourceAsset:
        """Resolve a local path, http(s):// URL, YouTube URL, or s3:// URI into a SourceAsset."""
        parsed = urlparse(uri)
        if parsed.scheme in {"http", "https"}:
            if is_youtube_url(uri):
                return await self._resolve_youtube(uri, probe_media=probe_media)
            return await self._resolve_http(uri, probe_media=probe_media)
        if parsed.scheme == "s3":
            return await self._resolve_s3(uri, probe_media=probe_media)
        if parsed.scheme in {"", "file"}:
            local_str = parsed.path if parsed.scheme == "file" else uri
            return await self._resolve_local(local_str, probe_media=probe_media)
        raise SourceResolutionError(f"Unsupported source URI scheme: {parsed.scheme}")

    async def _resolve_local(self, raw_path: str, probe_media: bool) -> SourceAsset:
        candidate = Path(raw_path).expanduser().resolve()
        if not self._is_within_allowed_roots(candidate):
            allowed = ", ".join(str(r) for r in self.settings.allowed_local_roots)
            raise SourceResolutionError(
                f"Local path '{candidate}' is outside allowed roots: [{allowed}]"
            )
        if not candidate.is_file():
            raise SourceResolutionError(f"Local file not found: {candidate}")

        digest = sha256_file(candidate)
        probe_data = await self.runner.probe(candidate) if probe_media else {}
        return SourceAsset(
            source_id=f"src_{uuid.uuid4().hex[:12]}",
            uri=str(candidate),
            kind=SourceKind.LOCAL,
            local_path=str(candidate),
            sha256=digest,
            size_bytes=candidate.stat().st_size,
            filename=candidate.name,
            probe=probe_data,
        )

    async def _resolve_http(self, url: str, probe_media: bool) -> SourceAsset:
        _validate_public_url(url, allow_private=self.settings.allow_private_urls)

        parsed = urlparse(url)
        ext = Path(parsed.path).suffix or ".mp4"
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        dest = self.settings.workspace_dir / "sources" / f"http_{url_hash}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)

        max_bytes = self.settings.effective_max_download_bytes
        timeout = httpx.Timeout(self.settings.download_timeout_sec)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise SourceResolutionError(
                        f"HTTP {response.status_code} downloading {url}"
                    )
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    raise SourceResolutionError(
                        f"Remote file exceeds max_download_mb ({self.settings.max_download_mb} MiB)"
                    )

                total = 0
                hasher = hashlib.sha256()
                with dest.open("wb") as handle:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                        total += len(chunk)
                        if total > max_bytes:
                            dest.unlink(missing_ok=True)
                            raise SourceResolutionError(
                                f"Download exceeded max_download_mb ({self.settings.max_download_mb} MiB)"
                            )
                        hasher.update(chunk)
                        handle.write(chunk)

        probe_data = await self.runner.probe(dest) if probe_media else {}
        return SourceAsset(
            source_id=f"src_{uuid.uuid4().hex[:12]}",
            uri=url,
            kind=SourceKind.HTTP,
            local_path=str(dest),
            sha256=hasher.hexdigest(),
            size_bytes=total,
            filename=Path(parsed.path).name or dest.name,
            probe=probe_data,
        )

    async def _resolve_s3(self, uri: str, probe_media: bool) -> SourceAsset:
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SourceResolutionError(
                "S3 source requested but boto3 is not installed. "
                "Install with: pip install 'video-automation-mcp[s3]'"
            ) from exc

        parsed = urlparse(uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise SourceResolutionError(f"Invalid S3 URI: {uri}")

        filename = Path(key).name or "source.mp4"
        key_hash = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:16]
        dest = self.settings.workspace_dir / "sources" / f"s3_{key_hash}_{filename}"
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _download() -> None:
            client = boto3.client("s3")
            client.download_file(bucket, key, str(dest))

        await asyncio.to_thread(_download)
        digest = sha256_file(dest)
        probe_data = await self.runner.probe(dest) if probe_media else {}
        return SourceAsset(
            source_id=f"src_{uuid.uuid4().hex[:12]}",
            uri=uri,
            kind=SourceKind.S3,
            local_path=str(dest),
            sha256=digest,
            size_bytes=dest.stat().st_size,
            filename=filename,
            probe=probe_data,
        )

    async def _resolve_youtube(self, url: str, probe_media: bool) -> SourceAsset:
        _validate_public_url(url, allow_private=self.settings.allow_private_urls)
        try:
            import yt_dlp  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SourceResolutionError(
                "YouTube source requested but yt-dlp is not installed. "
                "Install with: pip install 'video-automation-mcp[youtube]'"
            ) from exc

        sources_dir = (self.settings.workspace_dir / "sources").resolve()
        sources_dir.mkdir(parents=True, exist_ok=True)
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        out_template = str(sources_dir / f"yt_{url_hash}.%(ext)s")
        max_bytes = self.settings.effective_max_download_bytes
        max_dur = self.settings.youtube_max_duration_sec

        ydl_opts_info: dict[str, object] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "extract_flat": False,
        }

        def _extract_info() -> dict[str, object]:
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info = ydl.extract_info(url, download=False)
                if not isinstance(info, dict):
                    raise SourceResolutionError(f"Unable to extract YouTube metadata for: {url}")
                return info

        info = await asyncio.to_thread(_extract_info)
        duration = info.get("duration")
        if isinstance(duration, (int, float)) and duration > max_dur:
            raise SourceResolutionError(
                f"YouTube video duration ({duration}s) exceeds youtube_max_duration_sec ({max_dur}s)"
            )

        est_bytes = info.get("filesize") or info.get("filesize_approx")
        if isinstance(est_bytes, (int, float)) and est_bytes > max_bytes:
            raise SourceResolutionError(
                f"YouTube video size ({int(est_bytes)} bytes) exceeds max download limit ({max_bytes} bytes)"
            )

        ydl_opts_dl: dict[str, object] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "outtmpl": out_template,
            "max_filesize": max_bytes,
        }

        def _download() -> Path:
            with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl:
                dl_info = ydl.extract_info(url, download=True)
                if isinstance(dl_info, dict):
                    prepared = ydl.prepare_filename(dl_info)
                    mp4_candidate = Path(prepared).with_suffix(".mp4")
                    if mp4_candidate.is_file():
                        return mp4_candidate.resolve()
                    prep_path = Path(prepared)
                    if prep_path.is_file():
                        return prep_path.resolve()
            fallback = sources_dir / f"yt_{url_hash}.mp4"
            if fallback.is_file():
                return fallback.resolve()
            raise SourceResolutionError(f"yt-dlp completed but output file was not found for: {url}")

        dest = await asyncio.to_thread(_download)
        if sources_dir not in dest.parents:
            raise SourceResolutionError(f"Downloaded YouTube path escaped workspace: {dest}")

        size_bytes = dest.stat().st_size
        if size_bytes > max_bytes:
            dest.unlink(missing_ok=True)
            raise SourceResolutionError(
                f"Downloaded YouTube file ({size_bytes} bytes) exceeds max download limit ({max_bytes} bytes)"
            )

        digest = sha256_file(dest)
        probe_data = await self.runner.probe(dest) if probe_media else {}
        title = str(info.get("title") or dest.stem)
        probe_data["youtube"] = {
            "title": title,
            "duration_sec": duration,
            "uploader": info.get("uploader"),
            "webpage_url": info.get("webpage_url") or url,
        }

        return SourceAsset(
            source_id=f"src_{uuid.uuid4().hex[:12]}",
            uri=url,
            kind=SourceKind.YOUTUBE,
            local_path=str(dest),
            sha256=digest,
            size_bytes=size_bytes,
            filename=dest.name,
            probe=probe_data,
        )

    def _is_within_allowed_roots(self, path: Path) -> bool:
        for root in self.settings.allowed_local_roots:
            resolved_root = root.expanduser().resolve()
            if path == resolved_root or resolved_root in path.parents:
                return True
        return False

