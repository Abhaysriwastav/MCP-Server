"""Tests for face tracking, silence removal, multi-language dubbing, edit builder, and ZIP bundle."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from video_mcp.config import Settings
from video_mcp.context import AppContext
from video_mcp.dashboard.ui import DASHBOARD_HTML
from video_mcp.media.face_tracker import estimate_face_center_x_sync
from video_mcp.media.pipeline import _reframe_filter
from video_mcp.media.translator import translate_segments
from video_mcp.models import TranscriptSegment
from video_mcp.tools import editing, ingest

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class TestStudioFeatures(unittest.TestCase):
    def test_reframe_filter_uses_focus_x(self) -> None:
        flt = _reframe_filter(1080, 1920, mode="crop", focus_x=0.25)
        self.assertIn("iw*0.2500-540.0", flt)

    def test_face_tracker_returns_center_fallback_on_missing_file(self) -> None:
        self.assertEqual(estimate_face_center_x_sync(Path("/nonexistent/video.mp4")), 0.5)

    def test_translate_segments_preserves_timestamps(self) -> None:
        segs = [TranscriptSegment(start=1.0, end=3.0, text="Hello world")]
        with patch(
            "video_mcp.media.translator.translate_text",
            new=AsyncMock(return_value="Hola mundo"),
        ):
            out = asyncio.run(translate_segments(segs, target_language="es", source_language="en"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].text, "Hola mundo")
        self.assertEqual(out[0].start, 1.0)
        self.assertEqual(out[0].end, 3.0)

    def test_dashboard_contains_edit_builder_and_bundle_download(self) -> None:
        self.assertIn("Visual Edit Builder", DASHBOARD_HTML)
        self.assertIn("submitCustomEdit()", DASHBOARD_HTML)
        self.assertIn("bundle.zip", DASHBOARD_HTML)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg and ffprobe required for silence removal test")
    def test_remove_silences_and_smart_crop_end_to_end(self) -> None:
        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp).resolve()
                input_dir = tmp_path / "inputs"
                input_dir.mkdir()
                clip_path = input_dir / "with_silence.mp4"
                # 0.8s tone -> 1.0s silence -> 0.8s tone = 2.6s total
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "testsrc=duration=2.6:size=640x360:rate=30",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.8",
                        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100:d=1.0",
                        "-f", "lavfi", "-i", "sine=frequency=523:duration=0.8",
                        "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[aout]",
                        "-map", "0:v", "-map", "[aout]",
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
                        title="No Silence + Smart Crop",
                        source_ids=[sid],
                        operations=[
                            {"op": "remove_silences", "noise_db": -35.0, "min_silence_sec": 0.5},
                            {"op": "smart_crop", "enabled": True},
                        ],
                        output_profile="vertical_9x16",
                    )
                    rendered = await editing.render_edit_job(app, created["job"]["job_id"])
                    v_art = next(
                        a for a in rendered["job"]["artifacts"] if a["kind"] == "video_9x16"
                    )
                    out_dur = float(v_art["metadata"]["probe"]["duration_sec"])
                    # Original was 2.6s with 1.0s silence; trimmed output should be noticeably shorter
                    self.assertLess(out_dur, 2.2)
                finally:
                    app.close()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
