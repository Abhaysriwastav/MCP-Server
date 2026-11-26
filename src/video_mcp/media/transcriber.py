"""Async-safe Whisper transcription and readable SRT subtitle generation."""

from __future__ import annotations

import asyncio
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


class Transcriber:
    """Thread-safe, lazy-cached faster-whisper transcriber."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._model: Any = None

    def _get_model(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel  # type: ignore[import-not-found]
            except ImportError as exc:
                raise TranscriberError(
                    "faster-whisper is not installed. "
                    "Install with: pip install 'video-automation-mcp[captions]'"
                ) from exc

            self._model = WhisperModel(
                self.settings.whisper_model,
                device=self.settings.whisper_device,
                compute_type=self.settings.whisper_compute_type,
            )
            return self._model

    def _transcribe_sync(
        self, media_path: Path, word_timestamps: bool = True
    ) -> list[TranscriptSegment]:
        if not media_path.is_file():
            raise TranscriberError(f"Media file not found for transcription: {media_path}")
        model = self._get_model()
        raw_segments, _info = model.transcribe(
            str(media_path),
            word_timestamps=word_timestamps,
            vad_filter=True,
        )
        results: list[TranscriptSegment] = []
        for seg in raw_segments:
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
