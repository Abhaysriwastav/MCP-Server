"""End-to-end tests for editing pipeline, dual-format output, approval gate, and publishing."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from video_mcp.config import Settings
from video_mcp.context import AppContext
from video_mcp.models import JobStatus
from video_mcp.publishing.publisher import PublishError
from video_mcp.tools import approval, editing, ingest, publishing

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg and ffprobe are required for end-to-end media tests")
class TestEndToEndPipeline(unittest.TestCase):
    def _create_synthetic_video(self, path: Path, duration_sec: float = 2.0) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration_sec}:size=640x360:rate=30",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration_sec}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ]
        subprocess.run(cmd, check=True)

    def test_full_editing_approval_and_dual_publish_workflow(self) -> None:
        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp).resolve()
                input_dir = tmp_path / "inputs"
                input_dir.mkdir()
                clip_path = input_dir / "sample.mp4"
                self._create_synthetic_video(clip_path, duration_sec=2.0)

                cfg = Settings(
                    workspace_dir=tmp_path / "ws",
                    db_path=tmp_path / "ws" / "video.db",
                    allowed_local_roots=[input_dir, tmp_path / "ws"],
                    release_dir=tmp_path / "ws" / "releases",
                )
                app = AppContext.create(cfg)
                try:
                    # 1. Ingest local source
                    ing = await ingest.ingest_source(app, str(clip_path))
                    self.assertEqual(ing["status"], "ingested")
                    source_id = ing["source"]["source_id"]

                    # 2. Create edit job with operations and output='both'
                    created = editing.create_edit_job(
                        app,
                        title="Demo Dual Export",
                        source_ids=[source_id],
                        operations=[
                            {"op": "trim", "start_sec": 0.0, "duration_sec": 1.5},
                            {"op": "audio_normalize", "target_i": -16.0},
                            {"op": "fade", "fade_in_sec": 0.2, "fade_out_sec": 0.2, "total_duration_sec": 1.5},
                        ],
                        output_profile="both",
                    )
                    job_id = created["job"]["job_id"]
                    self.assertEqual(created["job"]["status"], JobStatus.DRAFT.value)

                    # 3. Render job -> produces 16:9, 9:16, thumbnails, probe.json, manifest.json
                    rendered = await editing.render_edit_job(app, job_id)
                    job_data = rendered["job"]
                    self.assertEqual(job_data["status"], JobStatus.READY_FOR_REVIEW.value)
                    kinds = {a["kind"] for a in job_data["artifacts"]}
                    self.assertEqual(
                        kinds,
                        {"video_16x9", "video_9x16", "thumbnail", "probe", "manifest"},
                    )

                    # Verify cannot publish before approval
                    with self.assertRaises(PublishError):
                        await publishing.publish_job(app, job_id)

                    # 4. Request approval
                    req = approval.request_approval(app, job_id, notes="Ready for review")
                    approval_id = req["approval"]["approval_id"]
                    self.assertEqual(req["approval"]["decision"], "pending")

                    # 5. Approve job
                    appr = approval.approve_job(app, approval_id, reviewer="abhay", notes="LGTM")
                    self.assertEqual(appr["job_status"], JobStatus.APPROVED.value)

                    # 6. Dry-run publish then actual publish
                    dry = await publishing.publish_job(app, job_id, target="local_release", dry_run=True)
                    self.assertTrue(dry["publish"]["dry_run"])

                    pub = await publishing.publish_job(app, job_id, target="local_release", dry_run=False)
                    self.assertEqual(pub["job_status"], JobStatus.PUBLISHED.value)

                    release_dir = Path(pub["publish"]["release_dir"])
                    self.assertTrue((release_dir / "landscape_16x9.mp4").is_file())
                    self.assertTrue((release_dir / "vertical_9x16.mp4").is_file())
                    self.assertTrue((release_dir / "manifest.json").is_file())
                    self.assertTrue((release_dir / "probe.json").is_file())
                    self.assertTrue((release_dir / "approval_certificate.json").is_file())

                    cert = json.loads((release_dir / "approval_certificate.json").read_text())
                    self.assertEqual(cert["reviewer"], "abhay")
                    self.assertEqual(cert["approval_id"], approval_id)
                finally:
                    app.close()

        asyncio.run(_run())

    def test_tamper_detection_blocks_publish(self) -> None:
        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp).resolve()
                input_dir = tmp_path / "inputs"
                input_dir.mkdir()
                clip_path = input_dir / "sample.mp4"
                self._create_synthetic_video(clip_path, duration_sec=1.0)

                cfg = Settings(
                    workspace_dir=tmp_path / "ws",
                    db_path=tmp_path / "ws" / "video.db",
                    allowed_local_roots=[input_dir, tmp_path / "ws"],
                    release_dir=tmp_path / "ws" / "releases",
                )
                app = AppContext.create(cfg)
                try:
                    ing = await ingest.ingest_source(app, str(clip_path))
                    created = editing.create_edit_job(
                        app,
                        title="Tamper Check",
                        source_ids=[ing["source"]["source_id"]],
                        operations=[],
                        output_profile="landscape_16x9",
                    )
                    job_id = created["job"]["job_id"]
                    rendered = await editing.render_edit_job(app, job_id)
                    req = approval.request_approval(app, job_id)
                    approval.approve_job(app, req["approval"]["approval_id"], reviewer="qa")

                    # Tamper with manifest.json after approval
                    manifest_art = next(
                        a for a in rendered["job"]["artifacts"] if a["kind"] == "manifest"
                    )
                    Path(manifest_art["path"]).write_text('{"tampered": true}', encoding="utf-8")

                    with self.assertRaises(PublishError) as ctx:
                        await publishing.publish_job(app, job_id)
                    self.assertIn("Integrity mismatch", str(ctx.exception))
                finally:
                    app.close()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()

