"""Unit and integration tests for AI voice cloning and audio replacement."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

from video_mcp.config import Settings
from video_mcp.context import AppContext
from video_mcp.media.voice_cloner import VoiceCloneError
from video_mcp.models import TranscriptSegment, TranscriptWord
from video_mcp.tools import approval, editing, ingest

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _write_sine_wav(path: Path, duration_sec: float = 1.2, sample_rate: int = 22050) -> None:
    import math
    import struct

    num_frames = int(duration_sec * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(num_frames):
            val = int(12000 * math.sin(2 * math.pi * 523.25 * (i / sample_rate)))
            frames.extend(struct.pack("<h", val))
        wf.writeframes(bytes(frames))


class TestVoiceCloning(unittest.TestCase):
    def test_coqui_missing_gives_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "test.db",
                allowed_local_roots=[tmp_path],
                release_dir=tmp_path / "ws" / "releases",
                voice_provider="coqui",
            )
            app = AppContext.create(cfg)
            try:
                with patch.dict(sys.modules, {"TTS": None, "TTS.api": None}):
                    with self.assertRaises(VoiceCloneError) as ctx:
                        asyncio.run(
                            app.voice_cloner.synthesize("Hello world", tmp_path / "out.wav")
                        )
                    self.assertIn("coqui-tts", str(ctx.exception))
            finally:
                app.close()

    def test_elevenlabs_requires_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "test.db",
                allowed_local_roots=[tmp_path],
                release_dir=tmp_path / "ws" / "releases",
                voice_provider="elevenlabs",
                elevenlabs_api_key=None,
            )
            app = AppContext.create(cfg)
            try:
                with self.assertRaises(VoiceCloneError) as ctx:
                    asyncio.run(
                        app.voice_cloner.synthesize(
                            "Hello", tmp_path / "out.wav", voice_id="voice_123"
                        )
                    )
                self.assertIn("VIDEO_MCP_ELEVENLABS_API_KEY", str(ctx.exception))
            finally:
                app.close()

    def test_coqui_model_cached_and_receives_speaker_wav(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            ref_wav = tmp_path / "ref.wav"
            _write_sine_wav(ref_wav, duration_sec=0.5)

            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "test.db",
                allowed_local_roots=[tmp_path],
                release_dir=tmp_path / "ws" / "releases",
                voice_provider="coqui",
            )
            app = AppContext.create(cfg)
            init_count = 0
            calls: list[dict[str, object]] = []

            class FakeTTS:
                def __init__(self, model_name: str) -> None:
                    nonlocal init_count
                    init_count += 1

                def tts_to_file(self, **kwargs: object) -> None:
                    calls.append(kwargs)
                    _write_sine_wav(Path(str(kwargs["file_path"])), duration_sec=0.5)

            fake_tts_pkg = types.ModuleType("TTS")
            fake_tts_api = types.ModuleType("TTS.api")
            fake_tts_api.TTS = FakeTTS  # type: ignore[attr-defined]
            fake_tts_pkg.api = fake_tts_api  # type: ignore[attr-defined]

            try:
                with patch.dict(sys.modules, {"TTS": fake_tts_pkg, "TTS.api": fake_tts_api}):
                    asyncio.run(
                        app.voice_cloner.synthesize(
                            "First line",
                            tmp_path / "out1.wav",
                            reference_audio_path=ref_wav,
                        )
                    )
                    asyncio.run(
                        app.voice_cloner.synthesize(
                            "Second line",
                            tmp_path / "out2.wav",
                            reference_audio_path=ref_wav,
                        )
                    )
                self.assertEqual(init_count, 1)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0]["speaker_wav"], str(ref_wav))
            finally:
                app.close()

    def test_omnivoice_model_cached_and_generates_wav(self) -> None:
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            ref_wav = tmp_path / "ref.wav"
            _write_sine_wav(ref_wav, duration_sec=0.5)

            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "test.db",
                allowed_local_roots=[tmp_path],
                release_dir=tmp_path / "ws" / "releases",
                voice_provider="omnivoice",
            )
            app = AppContext.create(cfg)
            load_count = 0
            gen_calls: list[dict[str, object]] = []

            class FakeOmniVoice:
                sampling_rate = 24000

                @classmethod
                def from_pretrained(cls, model_id: str, **kwargs: object) -> FakeOmniVoice:
                    nonlocal load_count
                    load_count += 1
                    return cls()

                def generate(self, **kwargs: object) -> list[np.ndarray]:
                    gen_calls.append(kwargs)
                    return [np.zeros(2400, dtype=np.float32)]

            fake_ov = types.ModuleType("omnivoice")
            fake_ov.OmniVoice = FakeOmniVoice  # type: ignore[attr-defined]
            try:
                with patch.dict(sys.modules, {"omnivoice": fake_ov}):
                    out = asyncio.run(
                        app.voice_cloner.synthesize(
                            "OmniVoice test",
                            tmp_path / "omni.wav",
                            reference_audio_path=ref_wav,
                            language="en",
                        )
                    )
                self.assertTrue(out.is_file())
                self.assertEqual(load_count, 1)
                self.assertEqual(gen_calls[0]["ref_audio"], str(ref_wav))
            finally:
                app.close()

    def test_cuda_auto_detection_for_whisper_torch_and_nvenc(self) -> None:
        from video_mcp.media.ffmpeg_runner import FFmpegRunner
        from video_mcp.media.transcriber import _resolve_whisper_device
        from video_mcp.media.voice_cloner import _resolve_torch_device

        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = types.SimpleNamespace(is_available=lambda: True)  # type: ignore[attr-defined]
        fake_ct2 = types.ModuleType("ctranslate2")
        fake_ct2.get_cuda_device_count = lambda: 1  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"torch": fake_torch, "ctranslate2": fake_ct2}):
            self.assertEqual(_resolve_whisper_device("auto", "auto"), ("cuda", "float16"))
            self.assertEqual(_resolve_torch_device("auto"), "cuda:0")

        fake_torch_cpu = types.ModuleType("torch")
        fake_torch_cpu.cuda = types.SimpleNamespace(is_available=lambda: False)  # type: ignore[attr-defined]
        fake_ct2_cpu = types.ModuleType("ctranslate2")
        fake_ct2_cpu.get_cuda_device_count = lambda: 0  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"torch": fake_torch_cpu, "ctranslate2": fake_ct2_cpu}):
            self.assertEqual(_resolve_whisper_device("auto", "auto"), ("cpu", "int8"))
            self.assertEqual(_resolve_torch_device("auto"), "cpu")
            runner = FFmpegRunner(hwaccel="auto")
            self.assertEqual(runner.video_encoder_args(), ["-c:v", "libx264", "-preset", "medium", "-crf", "18"])

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg and ffprobe required for end-to-end voice dub test")
    def test_trim_voice_clone_and_auto_caption_pipeline(self) -> None:
        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp).resolve()
                input_dir = tmp_path / "inputs"
                input_dir.mkdir()
                clip_path = input_dir / "sample.mp4"
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "testsrc=duration=2.0:size=640x360:rate=30",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2.0",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(clip_path),
                    ],
                    check=True,
                )

                cfg = Settings(
                    workspace_dir=tmp_path / "ws",
                    db_path=tmp_path / "ws" / "video.db",
                    allowed_local_roots=[input_dir, tmp_path / "ws"],
                    release_dir=tmp_path / "ws" / "releases",
                )
                app = AppContext.create(cfg)
                try:
                    ing = await ingest.ingest_source(app, str(clip_path))
                    sid = ing["source"]["source_id"]

                    created = editing.create_edit_job(
                        app,
                        title="AI Voice + Captions",
                        source_ids=[sid],
                        operations=[
                            {"op": "trim", "start_sec": 0.5, "duration_sec": 1.2},
                            {"op": "voice_clone", "keep_background_audio": True},
                            {"op": "auto_caption", "max_words_per_cue": 4},
                        ],
                        output_profile="both",
                    )
                    job_id = created["job"]["job_id"]

                    mock_segments = [
                        TranscriptSegment(
                            start=0.0,
                            end=1.1,
                            text="Cloned AI voice test",
                            words=[
                                TranscriptWord(word="Cloned", start=0.0, end=0.25),
                                TranscriptWord(word="AI", start=0.25, end=0.5),
                                TranscriptWord(word="voice", start=0.5, end=0.8),
                                TranscriptWord(word="test", start=0.8, end=1.1),
                            ],
                        )
                    ]

                    async def _fake_synthesize(
                        text: str,
                        output_path: Path,
                        reference_audio_path: Path | None = None,
                        voice_id: str | None = None,
                        language: str = "en",
                    ) -> Path:
                        _write_sine_wav(output_path, duration_sec=1.2)
                        return output_path

                    with (
                        patch.object(
                            app.transcriber,
                            "transcribe_media",
                            new=AsyncMock(return_value=mock_segments),
                        ) as mock_tr,
                        patch.object(
                            app.voice_cloner,
                            "synthesize",
                            side_effect=_fake_synthesize,
                        ) as mock_syn,
                    ):
                        rendered = await editing.render_edit_job(app, job_id)
                        # Whisper should only run once for both voice_clone + auto_caption
                        self.assertEqual(mock_tr.await_count, 1)
                        self.assertEqual(mock_syn.call_count, 1)

                    kinds = {a["kind"] for a in rendered["job"]["artifacts"]}
                    self.assertTrue(
                        {
                            "video_16x9",
                            "video_9x16",
                            "voice_dub",
                            "subtitles_srt",
                            "transcript",
                            "manifest",
                            "probe",
                        }.issubset(kinds)
                    )

                    req = approval.request_approval(app, job_id)
                    self.assertIn(
                        next(a["artifact_id"] for a in rendered["job"]["artifacts"] if a["kind"] == "voice_dub"),
                        req["approval"]["artifact_checksums"],
                    )
                finally:
                    app.close()

        asyncio.run(_run())

    def test_torch_device_falls_back_to_cpu_on_no_kernel_image(self) -> None:
        from video_mcp.media.voice_cloner import _resolve_torch_device

        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = types.SimpleNamespace(is_available=lambda: True)  # type: ignore[attr-defined]

        def _failing_zeros(*args: object, **kwargs: object) -> object:
            raise RuntimeError("CUDA error: no kernel image is available for execution on the device")

        fake_torch.zeros = _failing_zeros  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"torch": fake_torch}):
            self.assertEqual(_resolve_torch_device("auto"), "cpu")

    def test_omnivoice_retries_on_cpu_when_cuda_kernel_fails(self) -> None:
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            ref_wav = tmp_path / "ref.wav"
            _write_sine_wav(ref_wav, duration_sec=0.5)

            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "test.db",
                allowed_local_roots=[tmp_path],
                release_dir=tmp_path / "ws" / "releases",
                voice_provider="omnivoice",
                omnivoice_device="cuda:0",
            )
            app = AppContext.create(cfg)
            loaded_devices: list[object] = []

            class FakeOmniVoice:
                sampling_rate = 24000

                def __init__(self, device: object) -> None:
                    self.device = device

                @classmethod
                def from_pretrained(cls, model_id: str, **kwargs: object) -> FakeOmniVoice:
                    loaded_devices.append(kwargs.get("device_map"))
                    return cls(kwargs.get("device_map"))

                def generate(self, **kwargs: object) -> list[np.ndarray]:
                    if str(self.device).startswith("cuda"):
                        raise RuntimeError(
                            "CUDA error: no kernel image is available for execution on the device"
                        )
                    return [np.zeros(2400, dtype=np.float32)]

            fake_ov = types.ModuleType("omnivoice")
            fake_ov.OmniVoice = FakeOmniVoice  # type: ignore[attr-defined]
            try:
                with patch.dict(sys.modules, {"omnivoice": fake_ov}):
                    out = asyncio.run(
                        app.voice_cloner.synthesize(
                            "Fallback test",
                            tmp_path / "fallback.wav",
                            reference_audio_path=ref_wav,
                            language="en",
                        )
                    )
                self.assertTrue(out.is_file())
                self.assertEqual(loaded_devices, ["cuda:0", "cpu"])
            finally:
                app.close()

    def test_transcriber_falls_back_to_cpu_on_cuda_kernel_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            media = tmp_path / "clip.wav"
            _write_sine_wav(media, duration_sec=0.5)

            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "test.db",
                allowed_local_roots=[tmp_path],
                whisper_device="cuda",
                whisper_compute_type="float16",
            )
            app = AppContext.create(cfg)
            init_calls: list[tuple[object, object]] = []

            class FakeSegment:
                start = 0.0
                end = 0.5
                text = "CPU fallback transcript"
                words = []

            class FakeWhisperModel:
                def __init__(self, model_name: str, device: object = "cpu", compute_type: object = "int8") -> None:
                    self.device = device
                    init_calls.append((device, compute_type))

                def transcribe(self, *args: object, **kwargs: object) -> tuple[list[FakeSegment], object]:
                    if self.device == "cuda":
                        raise RuntimeError(
                            "CUDA error: no kernel image is available for execution on the device"
                        )
                    return [FakeSegment()], None

            fake_fw = types.ModuleType("faster_whisper")
            fake_fw.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
            try:
                with (
                    patch.dict(sys.modules, {"faster_whisper": fake_fw}),
                    patch.object(app.transcriber, "_decode_audio_input", return_value=str(media)),
                ):
                    segs = asyncio.run(app.transcriber.transcribe_media(media))
                self.assertEqual(len(segs), 1)
                self.assertEqual(segs[0].text, "CPU fallback transcript")
                self.assertEqual(init_calls, [("cuda", "float16"), ("cpu", "int8")])
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
