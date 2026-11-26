"""Tests for face tracking, silence removal, multi-language dubbing, edit builder, and ZIP bundle."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import AsyncMock, patch

from video_mcp.config import Settings
from video_mcp.context import AppContext
from video_mcp.dashboard.server import create_dashboard_server
from video_mcp.dashboard.ui import DASHBOARD_HTML
from video_mcp.media.face_tracker import estimate_face_center_x_sync
from video_mcp.media.pipeline import _reframe_filter, _subtitle_force_style
from video_mcp.media.social_kit import generate_social_kit
from video_mcp.media.translator import translate_segments
from video_mcp.models import EditJob, JobStatus, SourceAsset, SourceKind, TranscriptSegment
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

    def test_social_kit_generates_chapters_titles_and_hashtags(self) -> None:
        segs = [
            TranscriptSegment(start=0.0, end=5.0, text="Welcome to the studio workflow"),
            TranscriptSegment(start=32.0, end=38.0, text="Smart face tracking keeps subjects centered"),
        ]
        kit = generate_social_kit(segs, "AI Video Studio")
        self.assertEqual(len(kit["chapters"]), 2)
        self.assertEqual(kit["chapters"][0]["time"], "00:00")
        self.assertEqual(kit["chapters"][1]["time"], "00:32")
        self.assertEqual(len(kit["viral_titles"]), 3)
        self.assertIn("#shorts", kit["hashtags"])
        self.assertIn("Chapters:", kit["youtube_description"])

    def test_subtitle_force_style_supports_color_position_and_bg(self) -> None:
        style = _subtitle_force_style(
            font_size=26, font_color="yellow", highlight_bg=False, position="top"
        )
        self.assertIn("FontSize=26", style)
        self.assertIn("PrimaryColour=&H0000FFFF", style)
        self.assertIn("Alignment=8", style)
        self.assertIn("BorderStyle=1", style)

    def test_dashboard_contains_all_new_studio_controls(self) -> None:
        for token in (
            "builder-916-guide",
            "builder-caption-preview",
            "builder-bgm-source",
            "builder-wm-source",
            "builder-color",
            "builder-montage-list",
            "upload-color",
        ):
            self.assertIn(token, DASHBOARD_HTML)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe required")
    def test_color_preset_bgm_and_crossfade_end_to_end(self) -> None:
        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                clip1 = tmp_path / "clip1.mp4"
                clip2 = tmp_path / "clip2.mp4"
                bgm = tmp_path / "bgm.wav"
                for clip, freq in ((clip1, 440), (clip2, 554)):
                    subprocess.run(
                        [
                            "ffmpeg", "-y",
                            "-f", "lavfi", "-i", "testsrc=duration=1.5:size=320x240:rate=24",
                            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=1.5",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            str(clip),
                        ],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-f", "lavfi", "-i", "sine=frequency=220:duration=2.0",
                        str(bgm),
                    ],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                cfg = Settings(
                    workspace_dir=tmp_path / "ws",
                    db_path=tmp_path / "ws" / "video.db",
                    release_dir=tmp_path / "rel",
                    allowed_local_roots=[tmp_path],
                )
                app = AppContext.create(cfg)
                try:
                    s1 = (await ingest.ingest_source(app, str(clip1)))["source"]["source_id"]
                    s2 = (await ingest.ingest_source(app, str(clip2)))["source"]["source_id"]
                    s_bgm = (await ingest.ingest_source(app, str(bgm)))["source"]["source_id"]

                    created = editing.create_edit_job(
                        app,
                        title="Montage + Color + BGM",
                        source_ids=[s1, s2],
                        operations=[
                            {"op": "crossfade_merge", "transition_sec": 0.4},
                            {"op": "color_preset", "preset": "cinematic"},
                            {"op": "background_music", "audio_source_id": s_bgm, "music_volume": 0.2, "ducking": True},
                        ],
                        output_profile="landscape_16x9",
                    )
                    rendered = await editing.render_edit_job(app, created["job"]["job_id"])
                    kinds = {a["kind"] for a in rendered["job"]["artifacts"]}
                    self.assertIn("video_16x9", kinds)
                    self.assertIn("social_kit", kinds)
                finally:
                    app.close()

        asyncio.run(_run())

    def test_dashboard_contains_presets_library_badges_and_delete(self) -> None:
        for token in (
            "sources-tbody",
            "applyStudioPreset",
            "jobs-tab-badge",
            "ingest-tab-badge",
            "deleteJob",
        ):
            self.assertIn(token, DASHBOARD_HTML)

    def test_delete_source_workspace_guard_and_delete_job_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            ws = tmp_path / "ws"
            cfg = Settings(
                workspace_dir=ws,
                db_path=ws / "video.db",
                release_dir=ws / "releases",
                allowed_local_roots=[tmp_path],
            )
            app = AppContext.create(cfg)
            try:
                # 1. Workspace-managed source file SHOULD be removed
                ws_file = ws / "sources" / "clip.mp4"
                ws_file.parent.mkdir(parents=True, exist_ok=True)
                ws_file.write_bytes(b"wsdata")
                s_ws = SourceAsset(
                    source_id="src_ws",
                    uri=str(ws_file),
                    kind=SourceKind.LOCAL,
                    local_path=str(ws_file),
                    sha256="a" * 64,
                    size_bytes=6,
                    filename="clip.mp4",
                    probe={},
                )
                app.store.save_source(s_ws)
                res_ws = ingest.delete_source(app, "src_ws", delete_file=True)
                self.assertTrue(res_ws["deleted"])
                self.assertTrue(res_ws["file_removed"])
                self.assertFalse(ws_file.exists())
                self.assertIsNone(app.store.get_source("src_ws"))

                # 2. External file outside workspace SHOULD NOT be removed from disk
                ext_file = tmp_path / "external.mp4"
                ext_file.write_bytes(b"extdata")
                s_ext = SourceAsset(
                    source_id="src_ext",
                    uri=str(ext_file),
                    kind=SourceKind.LOCAL,
                    local_path=str(ext_file),
                    sha256="b" * 64,
                    size_bytes=7,
                    filename="external.mp4",
                    probe={},
                )
                app.store.save_source(s_ext)
                res_ext = ingest.delete_source(app, "src_ext", delete_file=True)
                self.assertTrue(res_ext["deleted"])
                self.assertFalse(res_ext["file_removed"])
                self.assertTrue(ext_file.exists())
                self.assertIsNone(app.store.get_source("src_ext"))

                # 3. Active RENDERING job cannot be deleted; COMPLETED/FAILED job cleans up renders dir
                job_rendering = EditJob(
                    job_id="job_busy",
                    title="Busy",
                    source_ids=["src_ext"],
                    status=JobStatus.RENDERING,
                )
                app.store.save_job(job_rendering)
                with self.assertRaises(ValueError):
                    editing.delete_job(app, "job_busy")

                job_done = EditJob(
                    job_id="job_done",
                    title="Done",
                    source_ids=["src_ext"],
                    status=JobStatus.READY_FOR_REVIEW,
                )
                app.store.save_job(job_done)
                render_dir = ws / "renders" / "job_done"
                render_dir.mkdir(parents=True, exist_ok=True)
                (render_dir / "out.mp4").write_bytes(b"mp4")
                res_del = editing.delete_job(app, "job_done", delete_files=True)
                self.assertTrue(res_del["deleted"])
                self.assertFalse(render_dir.exists())
                self.assertIsNone(app.store.get_job("job_done"))
            finally:
                app.close()

    def test_health_endpoint_returns_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            ws = tmp_path / "ws"
            cfg = Settings(
                workspace_dir=ws,
                db_path=ws / "video.db",
                release_dir=ws / "releases",
                allowed_local_roots=[tmp_path],
            )
            app = AppContext.create(cfg)
            srv = create_dashboard_server(app, host="127.0.0.1", port=0)
            thread = threading.Thread(target=srv.serve_forever, daemon=True)
            thread.start()
            try:
                port = srv.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as resp:
                    self.assertEqual(resp.status, 200)
                    payload = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(payload, {"status": "ok"})
            finally:
                srv.shutdown()
                srv.server_close()
                app.close()


if __name__ == "__main__":
    unittest.main()
