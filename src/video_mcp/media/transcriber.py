"""Async-safe Whisper transcription and readable SRT subtitle generation."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from video_mcp.config import Settings
from video_mcp.models import TranscriptSegment, TranscriptWord


class TranscriberError(RuntimeError):
    """Raised when transcription fails or faster-whisper is unavailable."""


def format_srt_timestamp(seconds: float) -> str:
    """Format non-negative seconds as `HH:MM:SS,mmm`."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _fallback_words_for_segment(seg: TranscriptSegment) -> list[TranscriptWord]:
    tokens = seg.text.strip().split()
    if not tokens:
        return []
    duration = max(0.1, seg.end - seg.start)
    step = duration / len(tokens)
    return [
        TranscriptWord(
            word=tok,
            start=seg.start + i * step,
            end=seg.start + (i + 1) * step,
        )
        for i, tok in enumerate(tokens)
    ]


def generate_srt(
    segments: list[TranscriptSegment],
    output_srt_path: Path,
    max_words_per_cue: int = 6,
    max_chars_per_cue: int = 38,
) -> Path:
    """Group word-level timestamps into short, readable SRT cues and write UTF-8 `.srt`."""
    cues: list[tuple[float, float, str]] = []

    for seg in segments:
        words = seg.words if seg.words else _fallback_words_for_segment(seg)
        if not words:
            continue

        buf: list[TranscriptWord] = []
        buf_len = 0

        for w in words:
            token = w.word.strip()
            if not token:
                continue
            projected_len = buf_len + (1 if buf else 0) + len(token)
            if buf and (len(buf) >= max_words_per_cue or projected_len > max_chars_per_cue):
                cues.append((buf[0].start, max(buf[-1].end, buf[0].start + 0.1), " ".join(x.word.strip() for x in buf)))
                buf = []
                buf_len = 0

            buf.append(w)
            buf_len += (1 if len(buf) > 1 else 0) + len(token)

        if buf:
            cues.append((buf[0].start, max(buf[-1].end, buf[0].start + 0.1), " ".join(x.word.strip() for x in buf)))

    lines: list[str] = []
    for idx, (start, end, text) in enumerate(cues, start=1):
        lines.append(f"{idx}")
        lines.append(f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")

    output_srt_path.parent.mkdir(parents=True, exist_ok=True)
    output_srt_path.write_text("\n".join(lines), encoding="utf-8")
    return output_srt_path


def _resolve_whisper_device(device: str, compute_type: str) -> tuple[str, str]:
    """Resolve 'auto' to CUDA + float16 when available, else CPU + int8."""
    resolved_dev = device.strip().lower()
    if resolved_dev == "auto":
        cuda_ok = False
        try:
            import ctranslate2  # type: ignore[import-not-found]

            cuda_ok = ctranslate2.get_cuda_device_count() > 0
        except Exception:
            try:
                import torch  # type: ignore[import-not-found]

                cuda_ok = bool(torch.cuda.is_available())
            except Exception:
                cuda_ok = False
        resolved_dev = "cuda" if cuda_ok else "cpu"

    resolved_compute = compute_type.strip().lower()
    if resolved_compute == "auto":
        resolved_compute = "float16" if resolved_dev == "cuda" else "int8"
    return resolved_dev, resolved_compute


def _is_cuda_error(exc: BaseException) -> bool:
    """Return True when `exc` indicates a CUDA/cuBLAS/cuDNN runtime or kernel failure."""
    msg = str(exc).lower()
    return any(tok in msg for tok in ("no kernel image", "cuda", "cublas", "cudnn", "ctranslate2"))


class Transcriber:
    """Thread-safe, lazy-cached faster-whisper transcriber."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._model: Any = None
        self._active_device: str = "cpu"

    def _get_model(self, force_cpu: bool = False) -> Any:
        with self._lock:
            if self._model is not None and not force_cpu:
                return self._model
            try:
                from faster_whisper import WhisperModel  # type: ignore[import-not-found]
            except ImportError as exc:
                raise TranscriberError(
                    "faster-whisper is not installed. "
                    "Install with: pip install 'video-automation-mcp[captions]'"
                ) from exc

            if force_cpu:
                device, compute_type = "cpu", "int8"
            else:
                device, compute_type = _resolve_whisper_device(
                    self.settings.whisper_device,
                    self.settings.whisper_compute_type,
                )
            try:
                self._model = WhisperModel(
                    self.settings.whisper_model,
                    device=device,
                    compute_type=compute_type,
                )
            except Exception as exc:
                if device == "cuda" and _is_cuda_error(exc):
                    device = "cpu"
                    self._model = WhisperModel(
                        self.settings.whisper_model,
                        device="cpu",
                        compute_type="int8",
                    )
                else:
                    raise
            self._active_device = device
            return self._model

    def _decode_audio_input(self, media_path: Path) -> Any:
        """Decode audio to 16kHz mono float32 via ffmpeg to avoid PyAV metadata_errors issues."""
        ffmpeg_bin = self.settings.ffmpeg_bin
        if shutil.which(ffmpeg_bin) is None and not Path(ffmpeg_bin).is_file():
            return str(media_path)
        try:
            import numpy as np  # type: ignore[import-not-found]
        except ImportError:
            return str(media_path)

        proc = subprocess.run(
            [
                ffmpeg_bin,
                "-nostdin",
                "-threads",
                "0",
                "-i",
                str(media_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "f32le",
                "-",
            ],
            capture_output=True,
            timeout=min(self.settings.ffmpeg_timeout_sec, 300),
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            return str(media_path)
        return np.frombuffer(proc.stdout, dtype=np.float32).copy()

    def _transcribe_sync(
        self, media_path: Path, word_timestamps: bool = True
    ) -> list[TranscriptSegment]:
        if not media_path.is_file():
            raise TranscriberError(f"Media file not found for transcription: {media_path}")
        model = self._get_model()
        audio_input = self._decode_audio_input(media_path)

        def _run_with_model(active_model: Any) -> list[Any]:
            raw_segments, _info = active_model.transcribe(
                audio_input,
                word_timestamps=word_timestamps,
                vad_filter=True,
            )
            segs = list(raw_segments)
            if not segs:
                # Retry without VAD in case quiet speech or game audio was filtered out
                raw_segments, _info = active_model.transcribe(
                    audio_input,
                    word_timestamps=word_timestamps,
                    vad_filter=False,
                )
                segs = list(raw_segments)
            return segs

        try:
            segments_list = _run_with_model(model)
        except Exception as exc:
            if self._active_device == "cuda" and _is_cuda_error(exc):
                with self._lock:
                    self._model = None
                model = self._get_model(force_cpu=True)
                segments_list = _run_with_model(model)
            else:
                raise
        results: list[TranscriptSegment] = []
        for seg in segments_list:
            words: list[TranscriptWord] = []
            for w in getattr(seg, "words", None) or []:
                words.append(
                    TranscriptWord(
                        word=str(w.word),
                        start=float(w.start),
                        end=float(w.end),
                        probability=float(w.probability) if getattr(w, "probability", None) is not None else None,
                    )
                )
            results.append(
                TranscriptSegment(
                    start=float(seg.start),
                    end=float(seg.end),
                    text=str(seg.text).strip(),
                    words=words,
                )
            )
        return results

    async def transcribe_media(
        self, media_path: Path, word_timestamps: bool = True
    ) -> list[TranscriptSegment]:
        """Transcribe media asynchronously without blocking the event loop."""
        return await asyncio.to_thread(self._transcribe_sync, media_path, word_timestamps)


_DEFAULT_TRANSCRIBER_LOCK = threading.RLock()
_DEFAULT_TRANSCRIBERS: dict[tuple[str, str, str], Transcriber] = {}


async def transcribe_media(
    media_path: Path,
    word_timestamps: bool = True,
    settings: Settings | None = None,
) -> list[TranscriptSegment]:
    """Module-level helper that caches a Transcriber per Whisper model configuration."""
    cfg = settings or Settings.from_env()
    key = (cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute_type)
    with _DEFAULT_TRANSCRIBER_LOCK:
        transcriber = _DEFAULT_TRANSCRIBERS.get(key)
        if transcriber is None:
            transcriber = Transcriber(cfg)
            _DEFAULT_TRANSCRIBERS[key] = transcriber
    return await transcriber.transcribe_media(media_path, word_timestamps=word_timestamps)
