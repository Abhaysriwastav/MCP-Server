# Video Automation MCP Server

A production-ready Python [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for automated video editing, mixed-source ingestion, dual-format/structured output generation, and **human-in-the-loop approval** before publishing.

## Selections Implemented

| Dimension | Selection | Implementation |
| :--- | :--- | :--- |
| **Workflow** | `editing` | Composable FFmpeg pipeline (`trim`, `concat`, `crossfade_merge`, `scale`, `reframe`, `smart_crop`, `color_preset`, `remove_silences`, `audio_normalize`, `background_music` with auto-ducking, `fade`, `speed`, `text_overlay`, `watermark` with opacity, `burn_subtitles`, `auto_caption` with custom color/size/position/box BG, `voice_clone` with multi-language `target_language` dubbing, `generate_thumbnail`) |
| **Sources** | `mixed` | Local filesystem (root-jail traversal guard), HTTP/HTTPS downloads (SSRF protection & size/timeout limits), YouTube URLs (`youtube.com`, `youtu.be`, `shorts/` + top comments, likes & Most Replayed heatmap via `yt-dlp`, controlled by `VIDEO_MCP_YOUTUBE_MAX_COMMENTS`), and S3 (`s3://bucket/key` via optional `boto3`) |
| **Publishing** | `approval` | Strict SQLite-persisted state machine (`draft` → `rendering` [with `paused` / `cancelled` render control] → `ready_for_review` → `pending_approval` → `approved` / `rejected` → `published`) with SHA-256 artifact integrity verification |
| **Output** | `both` | Dual video renditions (`16:9` `1920x1080` + `9:16` `1080x1920`), structured metadata (`manifest.json`, `probe.json`, `captions.srt`, `transcript.json`, `social_kit.json` with chapters/titles/hashtags, `ai_voice_dub.wav`, preview thumbnails, `approval_certificate.json`), and one-click `.zip` bundle download |

## Project Architecture

```text
src/video_mcp/
├── config.py               # Environment-driven Settings (VIDEO_MCP_*)
├── context.py              # Shared AppContext dependency container
├── models.py               # Pydantic domain models, edit operations & state machine
├── server.py               # FastMCP server (tools, resources, prompts, lifespan)
├── media/
│   ├── face_tracker.py     # OpenCV speaker/face X-center estimator for smart 9:16 crops
│   ├── ffmpeg_runner.py    # Async ffmpeg/ffprobe subprocess runner, CUDA NVENC & progress streaming
│   ├── job_control.py      # Cooperative Pause / Resume / Cancel render controller
│   ├── pipeline.py         # Composable editing, color presets, BGM ducking, AI dubbing & dual export
│   ├── social_kit.py       # Auto-chapters, viral hook titles, hashtags & YouTube/Reels copy generator
│   ├── transcriber.py      # Lazy-cached faster-whisper transcription (auto CUDA/CPU) & SRT generator
│   ├── translator.py       # Async multi-language text & segment translation for AI dubbing
│   ├── viral_miner.py      # Multi-signal gaming viral clipper (comments, likes, heatmap, dialogue, scenes)
│   └── voice_cloner.py     # AI voice cloning (OmniVoice, Coqui XTTS-v2, or optional ElevenLabs)
├── sources/
│   └── resolver.py         # Mixed source resolver + YouTube engagement/comments/heatmap extractor
├── storage/
│   └── job_store.py        # Thread-safe SQLite store (sources, jobs, approvals, transcripts, activity)
├── publishing/
│   └── publisher.py        # Approval-gated publisher (local_release, webhook, s3)
├── dashboard/
│   ├── server.py           # Live HTTP + SSE dashboard, upload, YouTube ingest, viral clipper & ZIP bundle API
│   └── ui.py               # 6-tab 3D Studio UI (Overview, Ingest, Edit Studio, Viral Game Clipper, Jobs, Config)
└── tools/
    ├── ingest.py           # ingest_source, probe_media, list_sources, transcribe_source, find_dialogue_moments, analyze_viral_clips, extract_viral_clips
    ├── editing.py          # create_edit_job, update_edit_job, render_edit_job, pause/resume/cancel_render_job, get_job_status, list_jobs, generate_thumbnail
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
# pip install -e ".[captions]"  # Whisper transcription & auto_caption via faster-whisper
# pip install -e ".[vision]"    # Smart 9:16 face-tracking via opencv-python-headless
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

### Dashboard Features (6 Organized Tabs)
- **Overview**: 3D glassmorphic studio UI, animated AI waveform visualizer, 5-stage pipeline flow indicator, KPI cards, SVG status donut chart, 3D artifact chart, render health gauge, and live Hardware/GPU badge (`CUDA GPU` / `CPU · NVENC / libx264`).
- **Ingest**: Upload local videos, BGM audio tracks (`mp3`/`wav`/`m4a`), or watermark logos (`png`/`jpg`/`webp`), or paste `youtube.com` / `youtu.be` / `shorts` / HTTP / S3 URLs with Audio Normalize (`-14 LUFS`), Remove Silences, Smart Face-Track `9:16`, Hook Text Overlay, Color Look presets, Auto-Caption, and Multi-Language AI Voice Dubbing.
- **Edit Studio (Visual Edit Builder)**: Live video preview player with `9:16` vertical safe-zone guide, interactive trim (`Set Start/End = Current`, `Play Trim`), live hook & caption style preview (`color`, `size`, `position`, `box BG`), multi-clip montage with `xfade` crossfades, color presets (`Cinematic`, `Vivid`, `Warm`, `B&W`), corner watermark overlay with opacity, and BGM mixer with voice auto-ducking (`sidechaincompress`).
- **Viral Game Clipper**: Paste a YouTube URL or upload a gaming video (GTA VI, GTA V, trailers, highlights) directly in the tab to mine **YouTube comments, likes & Most Replayed heatmap**, **catchy spoken dialogue (Whisper)**, and **FFmpeg visual/audio action scenes** — with one-click **Analyze Viral Clips**, **Auto-Extract Top Clips**, **Clip & Render**, and **Send to Edit Studio**.
- **Jobs & Activity**: Status filter pills, real-time `0–100%` progress/ETA, **Pause / Resume / Cancel**, inline MP4 preview, **Social Kit** (auto-chapters, viral titles, hashtags, copyable YouTube descriptions), `.srt` and one-click `.zip` bundle downloads, and SHA-256 Approval & Publishing gate.
- **Configuration**: Live workspace, allowed local roots, timeout, and SSRF settings editor.

### Docker Compose (NVIDIA CUDA GPU + All Prerequisites Included)

Includes `ffmpeg`, `fontconfig` + `fonts-dejavu-core` (for `drawtext` / `subtitles`), `nodejs` (for `yt-dlp` YouTube extraction & comment mining), `curl`, `opencv-python-headless`, `yt-dlp`, `faster-whisper`, `omnivoice`, persistent `HF_HOME=/app/workspace/.cache/huggingface`, `VIDEO_MCP_YOUTUBE_MAX_COMMENTS=80`, and container `HEALTHCHECK`:

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

