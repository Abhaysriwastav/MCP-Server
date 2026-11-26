# Video Automation MCP Server

A production-ready Python [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for automated video editing, mixed-source ingestion, dual-format/structured output generation, and **human-in-the-loop approval** before publishing.

## Selections Implemented

| Dimension | Selection | Implementation |
| :--- | :--- | :--- |
| **Workflow** | `editing` | Composable FFmpeg pipeline (`trim`, `concat`, `crossfade_merge`, `scale`, `reframe`, `smart_crop`, `remove_silences`, `audio_normalize`, `background_music`, `fade`, `speed`, `color_preset`, `text_overlay`, `watermark`, `burn_subtitles`, `auto_caption`, `voice_clone`, `generate_thumbnail`) |
| **Sources** | `mixed` | Local filesystem (with root-jail traversal guard), HTTP/HTTPS downloads (with SSRF protection & size/timeout limits), YouTube URLs (`youtube.com`, `youtu.be`, `shorts/` via optional `yt-dlp`), S3 (`s3://bucket/key` via optional `boto3`), plus BGM audio & watermark images |
| **Publishing** | `approval` | Strict SQLite-persisted state machine (`draft` → `rendering` → `ready_for_review` → `pending_approval` → `approved` / `rejected` → `published`, plus `paused` / `cancelled`) with SHA-256 artifact integrity verification |
| **Output** | `both` | Dual video renditions (`16:9` `1920x1080` + `9:16` `1080x1920`) **and** structured metadata artifacts (`manifest.json`, `probe.json`, `social_kit.json`, `captions.srt`, `transcript.json`, `ai_voice_dub.wav`, preview thumbnails, `approval_certificate.json`, and one-click `.zip` bundles) |

## Project Architecture

```text
src/video_mcp/
├── config.py               # Environment-driven Settings (VIDEO_MCP_*)
├── context.py              # Shared AppContext dependency container
├── models.py               # Pydantic domain models, edit operations & state machine
├── server.py               # FastMCP server (tools, resources, prompts, lifespan)
├── media/
│   ├── face_tracker.py     # OpenCV speaker/face horizontal tracker for smart 9:16 crop
│   ├── ffmpeg_runner.py    # Async ffmpeg/ffprobe subprocess runner, CUDA NVENC & progress streaming
│   ├── job_control.py      # Cooperative pause / resume / cancel render handle registry
│   ├── pipeline.py         # Composable editing, silence removal, color presets, BGM ducking, AI dubbing, captions & dual export
│   ├── social_kit.py       # Auto-chapters, viral title hooks, hashtags & social copy generator
│   ├── transcriber.py      # Lazy-cached faster-whisper transcription (auto CUDA/CPU) & SRT generator
│   ├── translator.py       # Async transcript/script translation for multi-language AI dubbing
│   └── voice_cloner.py     # AI voice cloning (OmniVoice, Coqui XTTS-v2, or optional ElevenLabs)
├── sources/
│   └── resolver.py         # Mixed source resolver (local, HTTP/HTTPS, YouTube, S3)
├── storage/
│   └── job_store.py        # Thread-safe SQLite store (sources, jobs, approvals, transcripts, activity)
├── publishing/
│   └── publisher.py        # Approval-gated publisher (local_release, webhook, s3)
├── dashboard/
│   ├── server.py           # Live HTTP + SSE dashboard, upload, YouTube ingest, dialogue search, bundle ZIP & config API
│   └── ui.py               # 6-tab 3D studio dashboard, live video preview, edit builder, presets & approval UI
└── tools/
    ├── ingest.py           # ingest_source, probe_media, list_sources, delete_source, transcribe_source, find_dialogue_moments
    ├── editing.py          # create_edit_job, update_edit_job, render_edit_job, pause_job, resume_job, cancel_job, get_job_status, list_jobs, delete_job, generate_thumbnail
    ├── approval.py         # request_approval, approve_job, reject_job, get_approval_status, list_pending_approvals
    └── publishing.py       # publish_job, list_publish_targets
```

## Prerequisites

- Python 3.11+
- `ffmpeg` and `ffprobe` installed and available on `PATH` (for burned-in subtitles on macOS, use `brew install ffmpeg-full` or Docker)
- **No paid API keys required** — YouTube downloads (`yt-dlp`), Whisper transcription (`faster-whisper`), AI voice cloning (`OmniVoice` / `Coqui`), FFmpeg editing, and SQLite state all run 100% locally.
- **Auto CUDA Acceleration (Windows / Linux)** — With `VIDEO_MCP_WHISPER_DEVICE=auto`, `VIDEO_MCP_OMNIVOICE_DEVICE=auto`, and `VIDEO_MCP_FFMPEG_HWACCEL=auto`, NVIDIA CUDA (`float16` + `h264_nvenc`) is used automatically when available and falls back to CPU on macOS/CPU-only hosts.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Optional feature extras:
# pip install -e ".[youtube]"   # YouTube URL ingestion via yt-dlp
# pip install -e ".[captions]"  # Whisper transcription & auto_caption via faster-whisper + Pillow
# pip install -e ".[vision]"    # Smart 9:16 face-tracking crop via opencv-python-headless
# pip install -e ".[voice]"     # Local AI voice cloning via OmniVoice / Coqui XTTS-v2
# pip install -e ".[s3]"        # S3 ingest & publishing via boto3
# pip install -e ".[full]"      # All optional integrations
# Or install everything from requirements.txt:
# pip install -r requirements.txt
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
- **6 Organized Studio Tabs with Live Badges**: Dedicated tabs for **Overview**, **Ingest**, **Edit Studio**, **Dialogue Clipper**, **Jobs & Activity** (showing active render badge), and **Configuration**.
- **3D Glassmorphic Studio UI & Live Graphics**: Animated 3D perspective grid, floating studio cube, live AI audio waveform visualizer, 5-stage pipeline flow indicator, SVG status donut chart, 3D artifact bar chart, render health radial gauge, and a live Hardware/GPU badge (`CUDA GPU` / `CPU · NVENC / libx264`).
- **Device Upload, YouTube / URL Ingest & Media Library**: Upload videos, audio BGM tracks, or logo images, or paste `youtube.com` / `youtu.be` / `shorts` / HTTP / S3 links with quick `-14 LUFS` normalize, silence removal, smart `9:16` face-track, hook overlay, color look, and AI voice/dubbing options, plus a **Media Library** table with quick **Edit** & **Delete** actions.
- **Interactive Edit Studio & One-Click Presets**: Live video preview with a `9:16` safe-zone frame guide, live hook/caption style previews, playback speed sync, `Set Start` / `Set End` buttons, one-click presets (`Shorts Viral`, `Podcast Cleanup`, `Cinematic Reel`, `AI Hindi Dub`), multi-clip crossfade montage, BGM auto-ducking, watermark overlays, and multi-language AI dubbing.
- **Clip Viral Dialogue**: Search spoken dialogue by keyword/phrase (or auto-rank top moments) and one-click **Clip & Render** into synced `16:9` + `9:16` outputs.
- **Job Control, Social Kit, ZIP Bundles & Approval Gate**: Live `0–100%` progress & dynamic ETA, **Pause / Resume / Cancel / Delete** controls, auto-generated **Social Kit** (YouTube chapters, viral hook titles, hashtags & copyable descriptions), one-click **Download Bundle (`.ZIP`)**, and **Approve / Reject / Publish**.

### Docker Compose (CPU / macOS & NVIDIA CUDA GPU)

Both Dockerfiles include `ffmpeg`, `ca-certificates`, `libglib2.0-0`, all `requirements.txt` packages (`opencv-python-headless`, `faster-whisper`, `yt-dlp`, `omnivoice`, `coqui-tts`), a `/health` check, and a persistent `hf_cache` volume for HuggingFace model weights.

```bash
# Universal CPU / macOS build:
docker compose up --build -d

# NVIDIA CUDA GPU build:
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d

# Dashboard: http://localhost:8080 | Health: http://localhost:8080/health | MCP HTTP: http://localhost:8000/mcp
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

