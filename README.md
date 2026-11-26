# Video Automation MCP Server

A production-ready Python [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for automated video editing, mixed-source ingestion, dual-format/structured output generation, and **human-in-the-loop approval** before publishing.

## Selections Implemented

| Dimension | Selection | Implementation |
| :--- | :--- | :--- |
| **Workflow** | `editing` | Composable FFmpeg pipeline (`trim`, `concat`, `scale`, `reframe`, `audio_normalize`, `fade`, `speed`, `text_overlay`, `watermark`, `burn_subtitles`, `auto_caption`, `generate_thumbnail`) |
| **Sources** | `mixed` | Local filesystem (with root-jail traversal guard), HTTP/HTTPS downloads (with SSRF protection & size/timeout limits), YouTube URLs (`youtube.com`, `youtu.be`, `shorts/` via optional `yt-dlp`), and S3 (`s3://bucket/key` via optional `boto3`) |
| **Publishing** | `approval` | Strict SQLite-persisted state machine (`draft` → `rendering` → `ready_for_review` → `pending_approval` → `approved` / `rejected` → `published`) with SHA-256 artifact integrity verification |
| **Output** | `both` | Dual video renditions (`16:9` `1920x1080` + `9:16` `1080x1920`) **and** structured metadata artifacts (`manifest.json`, `probe.json`, `captions.srt`, `transcript.json`, preview thumbnails, `approval_certificate.json`) |

## Project Architecture

```text
src/video_mcp/
├── config.py               # Environment-driven Settings (VIDEO_MCP_*)
├── context.py              # Shared AppContext dependency container
├── models.py               # Pydantic domain models, edit operations & state machine
├── server.py               # FastMCP server (tools, resources, prompts, lifespan)
├── media/
│   ├── ffmpeg_runner.py    # Async ffmpeg/ffprobe subprocess runner + SHA-256 helpers
│   ├── pipeline.py         # Composable editing, synced auto-captioning & dual-rendition export
│   └── transcriber.py      # Lazy-cached faster-whisper transcription & SRT cue generator
├── sources/
│   └── resolver.py         # Mixed source resolver (local, HTTP/HTTPS, YouTube, S3)
├── storage/
│   └── job_store.py        # Thread-safe SQLite store (sources, jobs, approvals, transcripts, activity)
├── publishing/
│   └── publisher.py        # Approval-gated publisher (local_release, webhook, s3)
├── dashboard/
│   ├── server.py           # Live HTTP + SSE dashboard, upload, YouTube ingest, dialogue search & config API
│   └── ui.py               # Single-page monitoring, viral dialogue clipper, preview & approval UI
└── tools/
    ├── ingest.py           # ingest_source, probe_media, list_sources, transcribe_source, find_dialogue_moments
    ├── editing.py          # create_edit_job, update_edit_job, render_edit_job, get_job_status, list_jobs, generate_thumbnail
    ├── approval.py         # request_approval, approve_job, reject_job, get_approval_status, list_pending_approvals
    └── publishing.py       # publish_job, list_publish_targets
```

## Prerequisites

- Python 3.11+
- `ffmpeg` and `ffprobe` installed and available on `PATH` (for burned-in subtitles on macOS, use `brew install ffmpeg-full` or Docker)
- **No paid API keys required** — YouTube downloads (`yt-dlp`), Whisper transcription (`faster-whisper`), FFmpeg editing, and SQLite state all run 100% locally.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Optional feature extras:
# pip install -e ".[youtube]"   # YouTube URL ingestion via yt-dlp
# pip install -e ".[captions]"  # Whisper transcription & auto_caption via faster-whisper
# pip install -e ".[s3]"        # S3 ingest & publishing via boto3
# pip install -e ".[full]"      # All optional integrations
```

Copy `.env.example` to `.env` (or export `VIDEO_MCP_*` environment variables) as needed.

## Running the Server & Live Dashboard

```bash
# Default stdio MCP server (for MCP clients)
video-automation-mcp

# Or Streamable HTTP MCP server
VIDEO_MCP_TRANSPORT=streamable-http VIDEO_MCP_PORT=8000 video-automation-mcp

# Live Web Dashboard (upload videos, ingest YouTube URLs, clip viral dialogue, monitor renders, approve & publish)
video-automation-dashboard
# Open http://127.0.0.1:8080 (or set VIDEO_MCP_DASHBOARD_PORT=8081)
```

### Dashboard Features
- **Device Upload & YouTube / URL Ingest**: Upload local videos or paste `youtube.com` / `youtu.be` / `shorts` / HTTP / S3 links directly in the UI with optional **Auto-caption (Whisper)**.
- **Clip Viral Dialogue**: Search spoken dialogue by keyword/phrase (or auto-rank top moments) and one-click **Clip & Render** into synced `16:9` + `9:16` outputs.
- **Job Inspector & Approval Gate**: Stream rendered MP4s inline, add auto-captions to existing jobs, and **Approve / Reject / Publish**.

### Docker Compose

```bash
docker compose up --build -d
# Dashboard: http://localhost:8080 | MCP HTTP: http://localhost:8000/mcp
```

### Example MCP Client Configuration

```json
{
  "mcpServers": {
    "video-automation": {
      "command": "/path/to/.venv/bin/video-automation-mcp",
      "env": {
        "VIDEO_MCP_WORKSPACE_DIR": "/path/to/workspace",
        "VIDEO_MCP_ALLOWED_LOCAL_ROOTS": "/path/to/media,/path/to/workspace"
      }
    }
  }
}
```

## Running Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

