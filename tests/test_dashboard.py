"""Tests for the live monitoring & configuration dashboard."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from video_mcp.config import Settings
from video_mcp.context import AppContext
from video_mcp.dashboard.server import _apply_config_update, _serialize_config
from video_mcp.dashboard.ui import DASHBOARD_HTML
from video_mcp.models import EditJob, JobStatus
from video_mcp.tools import editing


class TestDashboard(unittest.TestCase):
    def test_dashboard_html_contains_live_and_config_sections(self) -> None:
        self.assertIn("Video Automation MCP", DASHBOARD_HTML)
        self.assertIn("/api/overview", DASHBOARD_HTML)
        self.assertIn("/api/events", DASHBOARD_HTML)
        self.assertIn("/api/config", DASHBOARD_HTML)

    def test_activity_log_and_config_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "video.db",
                allowed_local_roots=[tmp_path],
                release_dir=tmp_path / "ws" / "releases",
            )
            app = AppContext.create(cfg)
            try:
                ev1 = app.store.log_activity("ingest", "Ingested clip.mp4", job_id="job_123")
                self.assertEqual(ev1["category"], "ingest")
                events = app.store.list_activity(limit=10)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["message"], "Ingested clip.mp4")

                initial = _serialize_config(app)
                self.assertEqual(initial["ffmpeg_timeout_sec"], 600)

                updated = _apply_config_update(
                    app,
                    {
                        "ffmpeg_timeout_sec": 900,
                        "allow_private_urls": True,
                        "webhook_url": "https://example.com/hook",
                    },
                )
                self.assertEqual(updated["ffmpeg_timeout_sec"], 900)
                self.assertTrue(updated["allow_private_urls"])
                self.assertEqual(updated["webhook_url"], "https://example.com/hook")
                self.assertTrue(Path(updated["config_file"]).is_file())

                saved_json = json.loads(Path(updated["config_file"]).read_text(encoding="utf-8"))
                self.assertEqual(saved_json["ffmpeg_timeout_sec"], 900)

                # Config update also emits an activity event
                events_after = app.store.list_activity(limit=10)
                self.assertEqual(events_after[0]["category"], "config")
            finally:
                app.close()

    def test_pause_resume_and_cancel_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "video.db",
                allowed_local_roots=[tmp_path],
                release_dir=tmp_path / "ws" / "releases",
            )
            app = AppContext.create(cfg)
            try:
                job = EditJob(
                    job_id="job_ctrl_1",
                    title="Control Test",
                    source_ids=["src_1"],
                    status=JobStatus.RENDERING,
                )
                app.store.save_job(job)
                handle = app.controller.create_handle("job_ctrl_1")

                paused = editing.pause_job(app, "job_ctrl_1")
                self.assertEqual(paused["job"]["status"], JobStatus.PAUSED.value)

                resumed = editing.resume_job(app, "job_ctrl_1")
                self.assertEqual(resumed["job"]["status"], JobStatus.RENDERING.value)

                cancelled = editing.cancel_job(app, "job_ctrl_1")
                self.assertEqual(cancelled["job"]["status"], JobStatus.CANCELLED.value)
                self.assertTrue(handle.is_cancelled())
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
