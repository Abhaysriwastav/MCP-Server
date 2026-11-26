"""Tests for viral gaming clip extraction (comments, likes, heatmap, catchy dialogue, FFmpeg scenes)."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from video_mcp.config import Settings
from video_mcp.context import AppContext
from video_mcp.dashboard.ui import DASHBOARD_HTML
from video_mcp.media.viral_miner import (
    fuse_viral_moments,
    mine_catchy_dialogue,
    mine_comment_moments,
    mine_heatmap_peaks,
    parse_comment_timestamps,
)
from video_mcp.models import TranscriptSegment
from video_mcp.tools import ingest

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class TestViralMiner(unittest.TestCase):
    def test_parse_comment_timestamps_handles_mmss_hhmmss_and_ranges(self) -> None:
        self.assertEqual(
            parse_comment_timestamps("0:42 that entrance was insane"),
            [(42.0, None)],
        )
        self.assertEqual(
            parse_comment_timestamps("Best sequence is 1:14-1:32 and 1:02:05!"),
            [(74.0, 92.0), (3725.0, None)],
        )
        # Timestamps past max_duration should be ignored
        self.assertEqual(
            parse_comment_timestamps("Check 9:59!", max_duration=120.0),
            [],
        )

    def test_comment_timestamp_clustering_ranks_high_like_moments_first(self) -> None:
        comments = [
            {"text": "0:15 nice car", "likes": 5},
            {"text": "1:14 gives me goosebumps every single time!", "likes": 25_000},
            {"text": "1:16 best scene in the GTA VI trailer hands down", "likes": 12_400},
        ]
        moments = mine_comment_moments(
            comments=comments,
            segments=[],
            duration_sec=120.0,
        )
        self.assertGreaterEqual(len(moments), 2)
        top = moments[0]
        self.assertGreater(top["comment_likes"], 30_000)
        self.assertLessEqual(top["start_sec"], 74.0)
        self.assertGreaterEqual(top["end_sec"], 76.0)

    def test_comment_quote_matching_pins_dialogue_without_timestamp(self) -> None:
        segments = [
            {"start": 2.0, "end": 5.0, "text": "Lucia, do you know why you're here?"},
            {"start": 5.5, "end": 8.0, "text": "Bad luck, I guess."},
            {"start": 18.0, "end": 22.0, "text": "The only way we're gonna get through this is by sticking together."},
        ]
        comments = [
            {"text": '"Bad luck, I guess" is already the most iconic gaming line!', "likes": 40_000},
        ]
        moments = mine_comment_moments(
            comments=comments,
            segments=segments,
            duration_sec=60.0,
        )
        self.assertEqual(len(moments), 1)
        self.assertIn("Bad luck", moments[0]["dialogue_text"])
        self.assertEqual(moments[0]["comment_likes"], 40_000)
        self.assertLessEqual(moments[0]["start_sec"], 5.5)

    def test_heatmap_and_catchy_dialogue_fusion_boosts_multi_signal_moment(self) -> None:
        segments = [
            {"start": 10.0, "end": 14.0, "text": "Trust? Trust."},
            {"start": 40.0, "end": 44.0, "text": "We have a heist to pull off in Vice City!"},
        ]
        comments = [
            {"text": "0:40 that heist dialogue gave me chills!", "likes": 18_000},
        ]
        heatmap = [
            {"start_time": 10.0, "end_time": 15.0, "value": 0.4},
            {"start_time": 38.0, "end_time": 44.0, "value": 0.96},
            {"start_time": 50.0, "end_time": 55.0, "value": 0.3},
        ]
        cm = mine_comment_moments(comments, segments, duration_sec=90.0)
        hm = mine_heatmap_peaks(heatmap, duration_sec=90.0)
        dm = mine_catchy_dialogue(segments, query="heist", duration_sec=90.0)

        fused = fuse_viral_moments(
            comment_moments=cm,
            heatmap_peaks=hm,
            dialogue_moments=dm,
            scene_moments=[],
            segments=segments,
            youtube_meta={"view_count": 1_000_000, "like_count": 85_000, "comments": comments},
            title="GTA_Trailer.mp4",
            duration_sec=90.0,
        )
        self.assertGreaterEqual(fused["moment_count"], 1)
        best = fused["moments"][0]
        self.assertEqual(best["category"], "multi_signal")
        self.assertIn("Comment Timestamp", best["signals"])
        self.assertIn("Most Replayed", best["signals"])
        self.assertIn("Catchy Dialogue", best["signals"])
        self.assertEqual(fused["video_engagement"]["engagement_grade"], "S")

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe required")
    def test_detect_viral_scenes_and_extract_viral_clips_end_to_end(self) -> None:
        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                clip_path = tmp_path / "gta_action.mp4"
                # 10s synthetic video with sharp scene cuts + loud audio spike around 4s-7s
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=24:d=3.0",
                        "-f", "lavfi", "-i", "testsrc=s=320x240:r=24:d=3.5",
                        "-f", "lavfi", "-i", "color=c=red:s=320x240:r=24:d=3.5",
                        "-f", "lavfi", "-i", "sine=frequency=220:duration=3.0,volume=0.08",
                        "-f", "lavfi", "-i", "sine=frequency=880:duration=3.5,volume=0.9",
                        "-f", "lavfi", "-i", "sine=frequency=220:duration=3.5,volume=0.08",
                        "-filter_complex",
                        "[0:v][1:v][2:v]concat=n=3:v=1:a=0[vout];[3:a][4:a][5:a]concat=n=3:v=0:a=1[aout]",
                        "-map", "[vout]", "-map", "[aout]",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(clip_path),
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
                    src = (await ingest.ingest_source(app, str(clip_path)))["source"]
                    sid = src["source_id"]

                    fake_segments = [
                        TranscriptSegment(start=3.2, end=6.2, text="No way! Watch that heist explosion in Vice City!")
                    ]
                    with patch.object(
                        app.transcriber, "transcribe_media", new=AsyncMock(return_value=fake_segments)
                    ):
                        analysis = await ingest.analyze_viral_clips(
                            app, source_id=sid, min_clip_sec=4.0, max_clip_sec=8.0
                        )
                        self.assertGreaterEqual(analysis["moment_count"], 1)

                        extracted = await ingest.extract_viral_clips(
                            app,
                            source_id=sid,
                            top_n=1,
                            output_profile="vertical_9x16",
                            min_clip_sec=4.0,
                            max_clip_sec=8.0,
                            auto_caption=False,
                            smart_crop=False,
                            add_hook_overlay=False,
                            auto_render=True,
                        )
                        self.assertEqual(extracted["extracted_count"], 1)
                        kinds = {a["kind"] for a in extracted["jobs"][0]["artifacts"]}
                        self.assertIn("video_9x16", kinds)
                finally:
                    app.close()

        asyncio.run(_run())

    def test_dashboard_contains_viral_game_clipper_controls(self) -> None:
        for token in (
            "analyzeViralClips",
            "autoExtractViralClips",
            "viral-engagement-bar",
            "viral-analyze-btn",
            "viral-extract-btn",
            "viral-url",
            "viral-file",
            "viralIngestUrlAndAnalyze",
            "viralUploadAndAnalyze",
            "Send to Edit Studio",
        ):
            self.assertIn(token, DASHBOARD_HTML)

    @unittest.skipUnless(shutil.which("node") is not None, "node required")
    def test_dashboard_inline_js_is_valid(self) -> None:
        match = re.search(r"<script>(.*)</script>", DASHBOARD_HTML, re.S)
        self.assertIsNotNone(match)
        assert match is not None
        with tempfile.TemporaryDirectory() as tmp:
            js_path = Path(tmp) / "dashboard.js"
            js_path.write_text(match.group(1), encoding="utf-8")
            proc = subprocess.run(
                ["node", "--check", str(js_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)


if __name__ == "__main__":
    unittest.main()
