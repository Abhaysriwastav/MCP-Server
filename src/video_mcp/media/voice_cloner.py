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


def _is_cuda_kernel_error(exc: BaseException) -> bool:
    """Return True when `exc` looks like a CUDA kernel/driver incompatibility error."""
    msg = str(exc).lower()
    return any(
        tok in msg
        for tok in (
            "no kernel image",
            "cuda error",
            "cublas",
            "cudnn",
            "acceleratorerror",
            "cuda driver",
        )
    )


def _torch_cuda_usable(torch_mod: Any) -> bool:
    """Verify CUDA works on this GPU architecture via a tiny tensor op."""
    try:
        if not torch_mod.cuda.is_available():
            return False
        if hasattr(torch_mod, "zeros"):
            probe = torch_mod.zeros(1, device="cuda")
            _ = (probe + 1).item()
        return True
    except Exception:
        return False


def _resolve_torch_device(device: str) -> str:
    """Resolve 'auto' to 'cuda:0' when CUDA is usable, else 'cpu'."""
    raw = device.strip()
    if raw.lower() == "auto":
        try:
            import torch  # type: ignore[import-not-found]

            return "cuda:0" if _torch_cuda_usable(torch) else "cpu"
        except Exception:
            return "cpu"
    return raw


class VoiceCloner:
    """Thread-safe, lazy-cached AI voice cloning engine."""

    def __init__(self, settings: Settings, runner: FFmpegRunner) -> None:
        self.settings = settings
        self.runner = runner
        self._lock = threading.RLock()
        self._tts: Any = None
        self._coqui_device: str = "cpu"
        self._omnivoice: Any = None
        self._omnivoice_device: str = "cpu"

    def _get_omnivoice(self, force_cpu: bool = False) -> Any:
        with self._lock:
            if self._omnivoice is not None and not force_cpu:
                return self._omnivoice
            try:
                import torch  # type: ignore[import-not-found]
                from omnivoice import OmniVoice  # type: ignore[import-not-found]
            except ImportError as exc:
                raise VoiceCloneError(
                    "omnivoice is not installed. Install with: "
                    "pip install omnivoice (or set VIDEO_MCP_VOICE_PROVIDER=coqui)."
                ) from exc

            device = "cpu" if force_cpu else _resolve_torch_device(self.settings.omnivoice_device)
            dtype = torch.float16 if device.startswith("cuda") else torch.float32
            try:
                self._omnivoice = OmniVoice.from_pretrained(
                    self.settings.omnivoice_model,
                    device_map=device,
                    dtype=dtype,
                    load_asr=True,
                )
            except Exception as exc:
                if device.startswith("cuda") and _is_cuda_kernel_error(exc):
                    device = "cpu"
                    self._omnivoice = OmniVoice.from_pretrained(
                        self.settings.omnivoice_model,
                        device_map="cpu",
                        dtype=torch.float32,
                        load_asr=True,
                    )
                else:
                    raise
            self._omnivoice_device = device
            return self._omnivoice

    def _get_coqui_tts(self, force_cpu: bool = False) -> Any:
        with self._lock:
            if self._tts is not None and not force_cpu:
                return self._tts
            try:
                from TTS.api import TTS  # type: ignore[import-not-found]
            except ImportError as exc:
                raise VoiceCloneError(
                    "coqui-tts is not installed. Install with: "
                    "pip install 'video-automation-mcp[voice]' "
                    "(or set VIDEO_MCP_VOICE_PROVIDER=elevenlabs)."
                ) from exc

            tts = TTS(self.settings.coqui_model)
            device = "cpu"
            if not force_cpu and _resolve_torch_device("auto").startswith("cuda") and hasattr(tts, "to"):
                try:
                    tts = tts.to("cuda")
                    device = "cuda"
                except Exception:
                    device = "cpu"
            self._coqui_device = device
            self._tts = tts
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
        if self.settings.voice_provider == "omnivoice":
            return await asyncio.to_thread(
                self._synthesize_omnivoice_sync,
                cleaned,
                output_path,
                reference_audio_path,
                language,
            )

        return await asyncio.to_thread(
            self._synthesize_coqui_sync,
            cleaned,
            output_path,
            reference_audio_path,
            language,
        )

    def _synthesize_omnivoice_sync(
        self,
        text: str,
        output_path: Path,
        reference_audio_path: Path | None,
        language: str,
    ) -> Path:
        import soundfile as sf  # type: ignore[import-not-found]

        model = self._get_omnivoice()
        kwargs: dict[str, Any] = {
            "text": text,
            "language": language,
        }
        if reference_audio_path is not None:
            kwargs["ref_audio"] = str(reference_audio_path)

        try:
            audios = model.generate(**kwargs)
        except Exception as exc:
            if self._omnivoice_device.startswith("cuda") and _is_cuda_kernel_error(exc):
                with self._lock:
                    self._omnivoice = None
                model = self._get_omnivoice(force_cpu=True)
                audios = model.generate(**kwargs)
            else:
                raise
        if not audios:
            raise VoiceCloneError("OmniVoice returned empty audio list.")
        sample_rate = int(getattr(model, "sampling_rate", 24000))
        sf.write(str(output_path), audios[0], sample_rate)

        if not output_path.is_file():
            raise VoiceCloneError(f"OmniVoice did not produce output file: {output_path}")
        return output_path

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
        try:
            tts.tts_to_file(**kwargs)
        except Exception as exc:
            if self._coqui_device.startswith("cuda") and _is_cuda_kernel_error(exc):
                with self._lock:
                    self._tts = None
                tts = self._get_coqui_tts(force_cpu=True)
                tts.tts_to_file(**kwargs)
            else:
                raise
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
