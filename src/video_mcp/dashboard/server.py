"""HTTP + SSE dashboard server for live monitoring, approvals, and configuration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import re
import threading
import time
import uuid
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from video_mcp.context import AppContext
from video_mcp.dashboard.ui import DASHBOARD_HTML
from video_mcp.models import JobStatus, SourceAsset, SourceKind
from video_mcp.tools import approval, editing, ingest, publishing


def _config_file_path(app: AppContext) -> Path:
    return app.settings.workspace_dir / "dashboard_config.json"


def _serialize_config(app: AppContext) -> dict[str, Any]:
    s = app.settings
    return {
        "config_file": str(_config_file_path(app)),
        "workspace_dir": str(s.workspace_dir),
        "db_path": str(s.db_path),
        "allowed_local_roots": [str(p) for p in s.allowed_local_roots],
        "release_dir": str(s.release_dir),
        "webhook_url": s.webhook_url,
        "ffmpeg_timeout_sec": s.ffmpeg_timeout_sec,
        "max_download_mb": s.max_download_mb,
        "download_timeout_sec": s.download_timeout_sec,
        "allow_private_urls": s.allow_private_urls,
    }


def _apply_config_update(app: AppContext, payload: dict[str, Any]) -> dict[str, Any]:
    s = app.settings
    if "allowed_local_roots" in payload and isinstance(payload["allowed_local_roots"], list):
        s.allowed_local_roots = [
            Path(str(p)).expanduser().resolve() for p in payload["allowed_local_roots"] if str(p).strip()
        ]
    if "release_dir" in payload and payload["release_dir"]:
        s.release_dir = Path(str(payload["release_dir"])).expanduser().resolve()
        s.release_dir.mkdir(parents=True, exist_ok=True)
    if "webhook_url" in payload:
        s.webhook_url = str(payload["webhook_url"]).strip() or None if payload["webhook_url"] else None
    if "ffmpeg_timeout_sec" in payload:
        s.ffmpeg_timeout_sec = max(10, int(payload["ffmpeg_timeout_sec"]))
        app.runner.timeout_sec = s.ffmpeg_timeout_sec
    if "max_download_mb" in payload:
        s.max_download_mb = max(1, int(payload["max_download_mb"]))
    if "download_timeout_sec" in payload:
        s.download_timeout_sec = max(5, int(payload["download_timeout_sec"]))
    if "allow_private_urls" in payload:
        s.allow_private_urls = bool(payload["allow_private_urls"])

    cfg_path = _config_file_path(app)
    serialized = _serialize_config(app)
    cfg_path.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
    app.store.log_activity(
        category="config",
        message="Updated server configuration via dashboard",
        details={"config_file": str(cfg_path)},
    )
    return serialized


def create_dashboard_server(
    app: AppContext,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> ThreadingHTTPServer:
    """Create a ThreadingHTTPServer bound to the given AppContext."""

    class DashboardHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return  # Keep stdout clean when running alongside MCP stdio

        def _send_json(self, status: int, data: dict[str, Any]) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw) if raw.strip() else {}

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/":
                body = DASHBOARD_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if path == "/api/overview":
                jobs = app.store.list_jobs(limit=50)
                sources = app.store.list_sources(limit=50)
                events = app.store.list_activity(limit=80)
                counts = {status.value: 0 for status in JobStatus}
                for j in jobs:
                    counts[j.status.value] = counts.get(j.status.value, 0) + 1
                counts["total_jobs"] = len(jobs)
                counts["total_sources"] = len(sources)
                from video_mcp.media.transcriber import _resolve_whisper_device

                w_dev, _ = _resolve_whisper_device(
                    app.settings.whisper_device, app.settings.whisper_compute_type
                )
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "summary": counts,
                        "jobs": [j.model_dump() for j in jobs],
                        "sources": [s.model_dump() for s in sources],
                        "activity": events,
                        "system": {
                            "compute": "CUDA GPU" if w_dev == "cuda" else "CPU",
                            "nvenc": app.runner.has_nvenc(),
                            "voice_provider": app.settings.voice_provider,
                            "whisper_model": app.settings.whisper_model,
                        },
                    },
                )
                return

            if path.startswith("/api/jobs/") and path.endswith("/bundle.zip"):
                job_id = path.removeprefix("/api/jobs/").removesuffix("/bundle.zip").strip("/")
                job = app.store.get_job(job_id)
                if job is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Job not found: {job_id}"})
                    return
                if not job.artifacts:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Job has no artifacts yet."})
                    return
                buf_path = app.settings.workspace_dir / "renders" / f"{job_id}_bundle.zip"
                buf_path.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(buf_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for art in job.artifacts:
                        p = Path(art.path)
                        if p.is_file():
                            zf.write(p, arcname=p.name)
                    cert = app.settings.release_dir / job_id / "approval_certificate.json"
                    if cert.is_file():
                        zf.write(cert, arcname="approval_certificate.json")
                data = buf_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{job_id}_bundle.zip"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if path.startswith("/api/jobs/"):
                job_id = path.removeprefix("/api/jobs/").strip("/")
                job = app.store.get_job(job_id)
                if job is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Job not found: {job_id}"})
                    return
                appr = app.store.get_approval(job.approval_id) if job.approval_id else None
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "job": job.model_dump(),
                        "approval": appr.model_dump() if appr else None,
                    },
                )
                return

            if path == "/api/config":
                self._send_json(HTTPStatus.OK, _serialize_config(app))
                return

            if path == "/api/files":
                qs = parse_qs(parsed.query)
                raw_path = qs.get("path", [""])[0]
                target = Path(raw_path).expanduser().resolve() if raw_path else None
                allowed_bases = [
                    app.settings.workspace_dir.resolve(),
                    app.settings.release_dir.resolve(),
                ]
                if target is None or not any(
                    target == base or base in target.parents for base in allowed_bases
                ):
                    self._send_json(HTTPStatus.FORBIDDEN, {"error": "File path not allowed"})
                    return
                if not target.is_file():
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "File not found"})
                    return
                mime, _ = mimetypes.guess_type(str(target))
                file_size = target.stat().st_size
                range_header = self.headers.get("Range")
                start = 0
                end = file_size - 1
                status = HTTPStatus.OK

                if range_header and range_header.startswith("bytes="):
                    spec = range_header.removeprefix("bytes=").split(",")[0].strip()
                    parts = spec.split("-", 1)
                    if parts[0]:
                        start = int(parts[0])
                    if len(parts) > 1 and parts[1]:
                        end = min(int(parts[1]), file_size - 1)
                    if start > end or start >= file_size:
                        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                        self.send_header("Content-Range", f"bytes */{file_size}")
                        self.end_headers()
                        return
                    status = HTTPStatus.PARTIAL_CONTENT

                chunk_len = (end - start) + 1
                self.send_response(status)
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(chunk_len))
                if status == HTTPStatus.PARTIAL_CONTENT:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.end_headers()

                try:
                    with target.open("rb") as handle:
                        handle.seek(start)
                        remaining = chunk_len
                        while remaining > 0:
                            buf = handle.read(min(remaining, 1024 * 256))
                            if not buf:
                                break
                            self.wfile.write(buf)
                            remaining -= len(buf)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                return

            if path == "/api/events":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                last_seen = 0
                recent = app.store.list_activity(limit=1)
                if recent:
                    last_seen = int(recent[0]["event_id"])  # type: ignore[arg-type]
                try:
                    while True:
                        new_events = app.store.list_activity(limit=20, since_id=last_seen)
                        if new_events:
                            last_seen = int(new_events[-1]["event_id"])  # type: ignore[arg-type]
                            payload = json.dumps({"events": new_events})
                            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        else:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                        time.sleep(0.8)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/upload":
                try:
                    raw_name = unquote(self.headers.get("X-Filename", "upload.mp4"))
                    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(raw_name).name) or "upload.mp4"
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0:
                        raise ValueError("Empty upload body.")
                    max_bytes = app.settings.max_download_mb * 1024 * 1024
                    if length > max_bytes:
                        raise ValueError(
                            f"File exceeds max_download_mb ({app.settings.max_download_mb} MiB)"
                        )

                    sources_dir = app.settings.workspace_dir / "sources"
                    sources_dir.mkdir(parents=True, exist_ok=True)
                    dest = sources_dir / f"upload_{uuid.uuid4().hex[:10]}_{safe_name}"

                    remaining = length
                    hasher = hashlib.sha256()
                    with dest.open("wb") as handle:
                        while remaining > 0:
                            chunk = self.rfile.read(min(remaining, 1024 * 256))
                            if not chunk:
                                break
                            hasher.update(chunk)
                            handle.write(chunk)
                            remaining -= len(chunk)

                    digest = hasher.hexdigest()
                    existing = app.store.get_source_by_sha256(digest)
                    if existing is not None:
                        dest.unlink(missing_ok=True)
                        self._send_json(
                            HTTPStatus.OK,
                            {"status": "deduplicated", "source": existing.model_dump()},
                        )
                        return

                    probe_data = asyncio.run(app.runner.probe(dest))
                    asset = SourceAsset(
                        source_id=f"src_{uuid.uuid4().hex[:12]}",
                        uri=str(dest),
                        kind=SourceKind.LOCAL,
                        local_path=str(dest),
                        sha256=digest,
                        size_bytes=dest.stat().st_size,
                        filename=safe_name,
                        probe=probe_data,
                    )
                    saved = app.store.save_source(asset)
                    app.store.log_activity(
                        category="ingest",
                        message=f"Uploaded device video '{saved.filename}'",
                        details={
                            "source_id": saved.source_id,
                            "size_bytes": saved.size_bytes,
                        },
                    )
                    self._send_json(
                        HTTPStatus.OK,
                        {"status": "uploaded", "source": saved.model_dump()},
                    )
                except Exception as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            if path == "/api/ingest":
                try:
                    payload = self._read_json()
                    uri = str(payload.get("uri") or "").strip()
                    if not uri:
                        raise ValueError("uri is required.")
                    res = asyncio.run(ingest.ingest_source(app, uri=uri, probe_media=True))
                    self._send_json(HTTPStatus.OK, res)
                except Exception as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            if path.startswith("/api/sources/"):
                parts = [p for p in path.removeprefix("/api/sources/").split("/") if p]
                if len(parts) == 2 and parts[1] == "find_dialogue":
                    source_id = parts[0]
                    try:
                        payload = self._read_json()
                        res = asyncio.run(
                            ingest.find_dialogue_moments(
                                app,
                                source_id=source_id,
                                query=payload.get("query"),
                                padding_sec=float(payload.get("padding_sec", 2.0)),
                                limit=int(payload.get("limit", 10)),
                            )
                        )
                        self._send_json(HTTPStatus.OK, res)
                    except Exception as exc:
                        self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Invalid source action path"})
                return

            if path == "/api/jobs":
                try:
                    payload = self._read_json()
                    created = editing.create_edit_job(
                        app,
                        title=str(payload.get("title") or "Uploaded Video Job"),
                        source_ids=list(payload.get("source_ids") or []),
                        operations=list(payload.get("operations") or []),
                        output_profile=str(payload.get("output_profile") or "both"),
                    )
                    job_id = created["job"]["job_id"]
                    if payload.get("auto_render", True):
                        threading.Thread(
                            target=lambda: asyncio.run(editing.render_edit_job(app, job_id)),
                            daemon=True,
                        ).start()
                    self._send_json(HTTPStatus.OK, created)
                except Exception as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            if path == "/api/config":
                try:
                    payload = self._read_json()
                    updated = _apply_config_update(app, payload)
                    self._send_json(HTTPStatus.OK, updated)
                except Exception as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            if path.startswith("/api/jobs/") and path.endswith("/bundle.zip"):
                job_id = path.removeprefix("/api/jobs/").removesuffix("/bundle.zip").strip("/")
                job = app.store.get_job(job_id)
                if job is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Job not found: {job_id}"})
                    return
                if not job.artifacts:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Job has no artifacts yet."})
                    return
                buf_path = app.settings.workspace_dir / "renders" / f"{job_id}_bundle.zip"
                buf_path.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(buf_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for art in job.artifacts:
                        p = Path(art.path)
                        if p.is_file():
                            zf.write(p, arcname=p.name)
                    cert = app.settings.release_dir / job_id / "approval_certificate.json"
                    if cert.is_file():
                        zf.write(cert, arcname="approval_certificate.json")
                data = buf_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{job_id}_bundle.zip"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if path.startswith("/api/jobs/"):
                parts = [p for p in path.removeprefix("/api/jobs/").split("/") if p]
                if len(parts) != 2:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "Invalid job action path"})
                    return
                job_id, action = parts
                try:
                    payload = self._read_json()
                    if action == "request_approval":
                        res = approval.request_approval(app, job_id, notes=payload.get("notes"))
                    elif action == "approve":
                        job = app.store.get_job(job_id)
                        if job is None or not job.approval_id:
                            raise ValueError("Job has no pending approval_id.")
                        res = approval.approve_job(
                            app,
                            approval_id=job.approval_id,
                            reviewer=str(payload.get("reviewer") or "dashboard-reviewer"),
                            notes=payload.get("notes"),
                        )
                    elif action == "reject":
                        job = app.store.get_job(job_id)
                        if job is None or not job.approval_id:
                            raise ValueError("Job has no pending approval_id.")
                        res = approval.reject_job(
                            app,
                            approval_id=job.approval_id,
                            reviewer=str(payload.get("reviewer") or "dashboard-reviewer"),
                            reason=str(payload.get("reason") or "Rejected via dashboard"),
                        )
                    elif action == "pause":
                        res = editing.pause_job(app, job_id)
                    elif action == "resume":
                        res = editing.resume_job(app, job_id)
                    elif action == "cancel":
                        res = editing.cancel_job(app, job_id)
                    elif action == "retry":
                        res = editing.update_edit_job(app, job_id)
                        threading.Thread(
                            target=lambda: asyncio.run(editing.render_edit_job(app, job_id)),
                            daemon=True,
                        ).start()
                    elif action == "auto_caption":
                        job = app.store.get_job(job_id)
                        if job is None:
                            raise ValueError(f"Job not found: {job_id}")
                        ops = list(job.operations)
                        if not any(op.get("op") == "auto_caption" for op in ops):
                            ops.append({"op": "auto_caption"})
                        res = editing.update_edit_job(app, job_id, operations=ops)
                        threading.Thread(
                            target=lambda: asyncio.run(editing.render_edit_job(app, job_id)),
                            daemon=True,
                        ).start()
                    elif action == "voice_clone":
                        job = app.store.get_job(job_id)
                        if job is None:
                            raise ValueError(f"Job not found: {job_id}")
                        ops = list(job.operations)
                        if not any(op.get("op") == "voice_clone" for op in ops):
                            ops.append(
                                {
                                    "op": "voice_clone",
                                    "script_text": payload.get("script_text") or None,
                                    "reference_audio_source_id": payload.get("reference_audio_source_id") or None,
                                    "voice_id": payload.get("voice_id") or None,
                                    "keep_background_audio": bool(payload.get("keep_background_audio", False)),
                                }
                            )
                        res = editing.update_edit_job(app, job_id, operations=ops)
                        threading.Thread(
                            target=lambda: asyncio.run(editing.render_edit_job(app, job_id)),
                            daemon=True,
                        ).start()
                    elif action in {"publish", "publish_dry"}:
                        res = asyncio.run(
                            publishing.publish_job(
                                app,
                                job_id=job_id,
                                target=str(payload.get("target") or "local_release"),
                                destination=payload.get("destination"),
                                dry_run=(action == "publish_dry"),
                            )
                        )
                    else:
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown action: {action}"})
                        return
                    self._send_json(HTTPStatus.OK, res)
                except Exception as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    return ThreadingHTTPServer((host, port), DashboardHandler)


def main() -> None:
    """CLI entrypoint for `video-automation-dashboard`."""
    host = os.getenv("VIDEO_MCP_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("VIDEO_MCP_DASHBOARD_PORT", "8080"))
    app = AppContext.create()
    server = create_dashboard_server(app, host=host, port=port)
    print(f"Video Automation Dashboard running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()
