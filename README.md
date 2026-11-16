# Video Automation MCP Server

A production-ready Python [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for automated video editing, mixed-source ingestion, dual-format/structured output generation, and **human-in-the-loop approval** before publishing.

## Selections Implemented

| Dimension | Selection | Implementation |
| :--- | :--- | :--- |
| **Workflow** | `editing` | Composable FFmpeg pipeline (`trim`, `concat`, `scale`, `reframe`, `audio_normalize`, `fade`, `speed`, `text_overlay`, `watermark`, `burn_subtitles`, `generate_thumbnail`) |
| **Sources** | `mixed` | Local filesystem (with root-jail traversal guard), HTTP/HTTPS downloads (with SSRF protection & size/timeout limits), and S3 (`s3://bucket/key` via optional `boto3`) |
| **Publishing** | `approval` | Strict SQLite-persisted state machine (`draft` → `rendering` → `ready_for_review` → `pending_approval` → `approved` / `rejected` → `published`) with SHA-256 artifact integrity verification |
| **Output** | `both` | Dual video renditions (`16:9` `1920x1080` + `9:16` `1080x1920`) **and** structured metadata artifacts (`manifest.json`, `probe.json`, preview thumbnails, `approval_certificate.json`) |

## Project Architecture

```text
src/video_mcp/
├── config.py               # Environment-driven Settings (VIDEO_MCP_*)
├── context.py              # Shared AppContext dependency container
├── models.py               # Pydantic domain models, edit operations & state machine
├── server.py               # FastMCP server (tools, resources, prompts, lifespan)
├── media/
│   ├── ffmpeg_runner.py    # Async ffmpeg/ffprobe subprocess runner + SHA-256 helpers
│   └── pipeline.py         # Composable editing & dual-rendition export pipeline
├── sources/
│   └── resolver.py         # Mixed source resolver (local, HTTP/HTTPS, S3)
├── storage/
│   └── job_store.py        # Thread-safe SQLite store (sources, jobs, approvals)
├── publishing/
│   └── publisher.py        # Approval-gated publisher (local_release, webhook, s3)
└── tools/
    ├── ingest.py           # ingest_source, probe_media, list_sources
    ├── editing.py          # create_edit_job, render_edit_job, get_job_status, list_jobs, generate_thumbnail
    ├── approval.py         # request_approval, approve_job, reject_job, get_approval_status, list_pending_approvals
    └── publishing.py       # publish_job, list_publish_targets
```

## Prerequisites

- Python 3.11+
- `ffmpeg` and `ffprobe` installed and available on `PATH`

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# Optional S3 support:
# pip install -e ".[s3]"
```

Copy `.env.example` to `.env` (or export `VIDEO_MCP_*` environment variables) as needed.

## Running the Server

```bash
# Default stdio transport (for MCP clients)
video-automation-mcp

# Or Streamable HTTP transport
VIDEO_MCP_TRANSPORT=streamable-http VIDEO_MCP_PORT=8000 video-automation-mcp
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

