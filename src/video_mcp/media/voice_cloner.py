"""AI voice cloning & speech synthesis (local Coqui XTTS-v2 or optional ElevenLabs API)."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import httpx

from video_mcp.config import Settings
from video_mcp.media.ffmpeg_runner import FFmpegRunner


class VoiceCloneError(RuntimeError):
    """Raised when voice cloning fails or required TTS dependencies/credentials are missing."""


class VoiceCloner:
    """Thread-safe, lazy-cached AI voice cloning engine."""

    def __init__(self, settings: Settings, runner: FFmpegRunner) -> None:
        self.settings = settings
        self.runner = runner
        self._lock = threading.RLock()
        self._tts: Any = None

    def _get_coqui_tts(self) -> Any:
        with self._lock:
            if self._tts is not None:
                return self._tts
            try:
                from TTS.api import TTS  # type: ignore[import-not-found]
            except ImportError as exc:
                raise VoiceCloneError(
                    "coqui-tts is not installed. Install with: "
                    "pip install 'video-automation-mcp[voice]' "
                    "(or set VIDEO_MCP_VOICE_PROVIDER=elevenlabs)."
                ) from exc

            self._tts = TTS(self.settings.coqui_model)
            return self._tts

    async def extract_reference_sample(
        self, media_path: Path, output_wav: Path, max_sec: float = 12.0
    ) -> Path:
        """Extract a clean mono WAV voice sample from `media_path` for zero-shot cloning."""
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        await self.runner.run_ffmpeg(
            [
                "-i",
                str(media_path),
                "-t",
                f"{max_sec:.2f}",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "22050",
                str(output_wav),
            ]
        )
        return output_wav

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        reference_audio_path: Path | None = None,
        voice_id: str | None = None,
        language: str = "en",
    ) -> Path:
        """Synthesize `text` in the cloned AI voice and write to `output_path`."""
        cleaned = text.strip()
        if not cleaned:
            raise VoiceCloneError("Cannot synthesize empty script text.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.settings.voice_provider == "elevenlabs":
            return await self._synthesize_elevenlabs(
                text=cleaned,
                output_path=output_path,
                voice_id=voice_id or self.settings.elevenlabs_voice_id,
            )

        return await asyncio.to_thread(
            self._synthesize_coqui_sync,
            cleaned,
            output_path,
            reference_audio_path,
            language,
        )

    def _synthesize_coqui_sync(
        self,
        text: str,
        output_path: Path,
        reference_audio_path: Path | None,
        language: str,
    ) -> Path:
        tts = self._get_coqui_tts()
        kwargs: dict[str, Any] = {
            "text": text,
            "file_path": str(output_path),
            "language": language,
        }
        if reference_audio_path is not None:
            kwargs["speaker_wav"] = str(reference_audio_path)
        tts.tts_to_file(**kwargs)
        if not output_path.is_file():
            raise VoiceCloneError(f"Coqui TTS did not produce output file: {output_path}")
        return output_path

    async def _synthesize_elevenlabs(
        self,
        text: str,
        output_path: Path,
        voice_id: str | None,
    ) -> Path:
        api_key = self.settings.elevenlabs_api_key
        if not api_key:
            raise VoiceCloneError(
                "VIDEO_MCP_ELEVENLABS_API_KEY is required when voice_provider='elevenlabs'."
            )
        if not voice_id:
            raise VoiceCloneError(
                "voice_id (or VIDEO_MCP_ELEVENLABS_VOICE_ID) is required for ElevenLabs."
            )

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
        }
        mp3_tmp = output_path.with_suffix(".mp3")
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise VoiceCloneError(
                    f"ElevenLabs API error HTTP {resp.status_code}: {resp.text[:300]}"
                )
            mp3_tmp.write_bytes(resp.content)

        if output_path.suffix.lower() == ".wav":
            await self.runner.run_ffmpeg(
                ["-i", str(mp3_tmp), "-ac", "2", "-ar", "48000", str(output_path)]
            )
            mp3_tmp.unlink(missing_ok=True)
        else:
            mp3_tmp.replace(output_path)
        return output_path
