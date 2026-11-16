"""Unit tests for mixed-source security, SSRF guards, and SQLite JobStore."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from video_mcp.config import Settings
from video_mcp.context import AppContext
from video_mcp.sources.resolver import SourceResolutionError, _validate_public_url


class TestSourcesAndStore(unittest.TestCase):
    def test_ssrf_blocks_loopback_and_private_ips(self) -> None:
        with self.assertRaises(SourceResolutionError):
            _validate_public_url("http://127.0.0.1/video.mp4", allow_private=False)
        with self.assertRaises(SourceResolutionError):
            _validate_public_url("http://169.254.169.254/latest/meta-data", allow_private=False)
        with self.assertRaises(SourceResolutionError):
            _validate_public_url("ftp://example.com/video.mp4", allow_private=False)

    def test_local_path_traversal_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            allowed_dir = tmp_path / "allowed"
            allowed_dir.mkdir()
            outside_file = tmp_path / "secret.mp4"
            outside_file.write_bytes(b"not-allowed")

            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "test.db",
                allowed_local_roots=[allowed_dir],
                release_dir=tmp_path / "ws" / "releases",
            )
            app = AppContext.create(cfg)
            try:
                with self.assertRaises(SourceResolutionError):
                    asyncio.run(app.resolver.resolve(str(outside_file), probe_media=False))
            finally:
                app.close()

    def test_s3_without_boto3_gives_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            cfg = Settings(
                workspace_dir=tmp_path / "ws",
                db_path=tmp_path / "ws" / "test.db",
                allowed_local_roots=[tmp_path],
                release_dir=tmp_path / "ws" / "releases",
            )
            app = AppContext.create(cfg)
            try:
                with self.assertRaises(SourceResolutionError) as ctx:
                    asyncio.run(app.resolver.resolve("s3://my-bucket/clip.mp4", probe_media=False))
                self.assertIn("boto3", str(ctx.exception))
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()

