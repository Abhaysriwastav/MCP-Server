"""Unit and integration tests for YouTube ingestion, transcription, SRT chunking, and caption sync."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from video_mcp.config import Settings
from video_mcp.context import AppContext
from video_mcp.media.pipeline import _escape_filter_path, _subtitle_force_style
from video_mcp.media.transcriber import Transcriber, format_srt_timestamp, generate_srt
from video_mcp.models import (
    EditJob,
    JobStatus,
    SourceKind,
    TranscriptSegment,
    TranscriptWord,
)
from video_mcp.sources.resolver import SourceResolutionError, is_youtube_url
from video_mcp.tools import approval, editing, ingest

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class TestYouTubeAndTranscription(unittest.TestCase):
    def test_youtube_url_detection(self) -> None:
        self.assertTrue(is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertTrue(is_youtube_url("https://youtu.be/dQw4w9WgXcQ"))
        self.assertTrue(is_youtube_url("https://youtube.com/shorts/abc123"))
        self.assertTrue(is_youtube_url("https://m.youtube.com/watch?v=abc123"))
        self.assertFalse(is_youtube_url("https://example.com/video.mp4"))
        self.assertFalse(is_youtube_url("ftp://youtube.com/watch?v=abc"))

    def test_youtube_max_duration_and_download_mocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "test.db",
                allowed_local_roots=[tmp_path],
                release_dir=tmp_path / "ws" / "releases",
                allow_private_urls=True,
                youtube_max_duration_sec=60,
                max_download_bytes=1024 * 1024,
            )
            app = AppContext.create(cfg)
            try:
                class FakeYDLTooLong:
                    def __init__(self, opts: dict[str, object]) -> None:
                        self.opts = opts

                    def __enter__(self) -> FakeYDLTooLong:
                        return self

                    def __exit__(self, *args: object) -> None:
                        return None

                    def extract_info(self, url: str, download: bool = False) -> dict[str, object]:
                        return {"title": "Too Long", "duration": 120}

                fake_mod = types.ModuleType("yt_dlp")
                fake_mod.YoutubeDL = FakeYDLTooLong  # type: ignore[attr-defined]
                with patch.dict(sys.modules, {"yt_dlp": fake_mod}):
                    with self.assertRaises(SourceResolutionError) as ctx:
                        asyncio.run(
                            app.resolver.resolve("https://youtu.be/dQw4w9WgXcQ", probe_media=False)
                        )
                    self.assertIn("youtube_max_duration_sec", str(ctx.exception))

                # Now test valid duration + download into workspace/sources/
                class FakeYDLValid:
                    def __init__(self, opts: dict[str, object]) -> None:
                        self.opts = opts

                    def __enter__(self) -> FakeYDLValid:
                        return self

                    def __exit__(self, *args: object) -> None:
                        return None

                    def prepare_filename(self, info: dict[str, object]) -> str:
                        tmpl = str(self.opts["outtmpl"])
                        return tmpl.replace("%(ext)s", "mp4")

                    def extract_info(self, url: str, download: bool = False) -> dict[str, object]:
                        info = {
                            "title": "Sample Short",
                            "duration": 15,
                            "filesize_approx": 5000,
                            "uploader": "TestChannel",
                            "webpage_url": url,
                        }
                        if download:
                            out_file = Path(self.prepare_filename(info))
                            out_file.parent.mkdir(parents=True, exist_ok=True)
                            out_file.write_bytes(b"fake-mp4-bytes")
                        return info

                fake_mod.YoutubeDL = FakeYDLValid  # type: ignore[attr-defined]
                with patch.dict(sys.modules, {"yt_dlp": fake_mod}):
                    asset = asyncio.run(
                        app.resolver.resolve("https://youtube.com/shorts/xyz789", probe_media=False)
                    )
                self.assertEqual(asset.kind, SourceKind.YOUTUBE)
                self.assertTrue(Path(asset.local_path).is_file())
                self.assertIn(str((tmp_path / "ws" / "sources").resolve()), asset.local_path)
                self.assertEqual(asset.probe["youtube"]["title"], "Sample Short")
            finally:
                app.close()

    def test_srt_generation_and_cue_chunking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            srt_path = Path(tmp) / "captions.srt"
            words = [
                TranscriptWord(word="Hello", start=0.0, end=0.3),
                TranscriptWord(word="world", start=0.3, end=0.6),
                TranscriptWord(word="this", start=0.6, end=0.9),
                TranscriptWord(word="is", start=0.9, end=1.1),
                TranscriptWord(word="a", start=1.1, end=1.2),
                TranscriptWord(word="very", start=1.2, end=1.5),
                TranscriptWord(word="clean", start=1.5, end=1.8),
                TranscriptWord(word="caption", start=1.8, end=2.2),
            ]
            seg = TranscriptSegment(
                start=0.0,
                end=2.2,
                text="Hello world this is a very clean caption",
                words=words,
            )
            generate_srt([seg], srt_path, max_words_per_cue=4, max_chars_per_cue=38)
            content = srt_path.read_text(encoding="utf-8")
            self.assertIn("00:00:00,000 --> 00:00:01,100\nHello world this is", content)
            self.assertIn("00:00:01,100 --> 00:00:02,200\na very clean caption", content)
            self.assertEqual(format_srt_timestamp(3661.25), "01:01:01,250")

    def test_transcriber_caches_whisper_model_and_sqlite_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            media_file = tmp_path / "clip.mp4"
            media_file.write_bytes(b"dummy")

            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "test.db",
                allowed_local_roots=[tmp_path],
                release_dir=tmp_path / "ws" / "releases",
            )
            app = AppContext.create(cfg)
            init_calls = 0

            class FakeWord:
                def __init__(self, word: str, start: float, end: float) -> None:
                    self.word = word
                    self.start = start
                    self.end = end
                    self.probability = 0.99

            class FakeSeg:
                def __init__(self, start: float, end: float, text: str, words: list[FakeWord]) -> None:
                    self.start = start
                    self.end = end
                    self.text = text
                    self.words = words

            class FakeWhisperModel:
                def __init__(self, model_size: str, device: str, compute_type: str) -> None:
                    nonlocal init_calls
                    init_calls += 1

                def transcribe(self, path: str, word_timestamps: bool = True, vad_filter: bool = True):
                    segs = [
                        FakeSeg(0.5, 2.0, "First sentence", [FakeWord("First", 0.5, 1.0), FakeWord("sentence", 1.1, 2.0)]),
                        FakeSeg(5.0, 7.5, "Second sentence", [FakeWord("Second", 5.0, 6.0), FakeWord("sentence", 6.1, 7.5)]),
                    ]
                    return iter(segs), None

            fake_fw = types.ModuleType("faster_whisper")
            fake_fw.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]

            try:
                with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
                    ing = asyncio.run(ingest.ingest_source(app, str(media_file), probe_media=False))
                    sid = ing["source"]["source_id"]

                    res1 = asyncio.run(ingest.transcribe_source(app, sid))
                    self.assertFalse(res1["cached"])
                    self.assertEqual(res1["segment_count"], 2)
                    self.assertEqual(init_calls, 1)

                    # Second call hits SQLite cache & respects start_sec/end_sec filter
                    res2 = asyncio.run(ingest.transcribe_source(app, sid, start_sec=4.0, end_sec=8.0))
                    self.assertTrue(res2["cached"])
                    self.assertEqual(res2["segment_count"], 1)
                    self.assertIn("[5.00s -> 7.50s] Second sentence", res2["transcript_lines"])
                    self.assertEqual(init_calls, 1)
            finally:
                app.close()

    def test_subtitle_path_escaping_and_style(self) -> None:
        escaped = _escape_filter_path(Path(r"C:\Users\o'neil\subs[1]:test.srt"))
        self.assertNotIn("\\'", escaped.replace("\\'", ""))
        self.assertIn("\\:", escaped)
        self.assertIn("\\[1\\]", escaped)
        style = _subtitle_force_style(font_size=22, margin_v=60)
        self.assertIn("FontSize=22", style)
        self.assertIn("MarginV=60", style)
        self.assertIn("Alignment=2", style)

    def test_stale_rendering_recovery_and_update_resets_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "test.db",
                allowed_local_roots=[tmp_path],
                release_dir=tmp_path / "ws" / "releases",
            )
            app1 = AppContext.create(cfg)
            stale_job = EditJob(
                job_id="job_stale_1",
                title="Crashed Render",
                source_ids=["src_1"],
                status=JobStatus.RENDERING,
            )
            app1.store.save_job(stale_job)
            app1.close()

            # Startup should recover stale rendering job as failed
            app2 = AppContext.create(cfg)
            try:
                recovered = app2.store.get_job("job_stale_1")
                assert recovered is not None
                self.assertEqual(recovered.status, JobStatus.FAILED)
                self.assertIn("restart", (recovered.error or "").lower())

                # Updating a job resets approved/rejected back to draft and clears approval_id
                recovered.status = JobStatus.APPROVED
                recovered.approval_id = "apr_old"
                app2.store.save_job(recovered)

                updated = editing.update_edit_job(app2, "job_stale_1", title="Edited Again")
                self.assertEqual(updated["job"]["status"], JobStatus.DRAFT.value)
                self.assertIsNone(updated["job"]["approval_id"])
            finally:
                app2.close()

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg and ffprobe required for caption sync test")
    def test_auto_caption_runs_after_trim_before_dual_renditions(self) -> None:
        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp).resolve()
                input_dir = tmp_path / "inputs"
                input_dir.mkdir()
                clip_path = input_dir / "sample.mp4"
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "testsrc=duration=2.5:size=640x360:rate=30",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2.5",
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
                        title="Trim + AutoCaption",
                        source_ids=[sid],
                        operations=[
                            {"op": "trim", "start_sec": 1.0, "duration_sec": 1.2},
                            {"op": "auto_caption", "max_words_per_cue": 3},
                        ],
                        output_profile="both",
                    )
                    job_id = created["job"]["job_id"]

                    mock_segments = [
                        TranscriptSegment(
                            start=0.0,
                            end=1.1,
                            text="Synced after trim",
                            words=[
                                TranscriptWord(word="Synced", start=0.0, end=0.35),
                                TranscriptWord(word="after", start=0.35, end=0.7),
                                TranscriptWord(word="trim", start=0.7, end=1.1),
                            ],
                        )
                    ]
                    with patch.object(
                        app.transcriber,
                        "transcribe_media",
                        new=AsyncMock(return_value=mock_segments),
                    ) as mock_transcribe:
                        rendered = await editing.render_edit_job(app, job_id)
                        # Verify transcription ran on pre_caption.mp4 (the trimmed clip), not raw sample.mp4
                        called_path = mock_transcribe.call_args.args[0]
                        self.assertEqual(called_path.name, "pre_caption.mp4")

                    kinds = {a["kind"] for a in rendered["job"]["artifacts"]}
                    self.assertTrue(
                        {"video_16x9", "video_9x16", "subtitles_srt", "transcript", "manifest", "probe"}.issubset(kinds)
                    )

                    # Approval snapshots all artifacts including subtitles_srt and transcript
                    req = approval.request_approval(app, job_id)
                    self.assertEqual(
                        len(req["approval"]["artifact_checksums"]),
                        len(rendered["job"]["artifacts"]),
                    )
                finally:
                    app.close()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
