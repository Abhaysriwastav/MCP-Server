---
name: Video Automation MCP (Approval-Gated)
description: End-to-end video editing automation with mixed sources (local, HTTP/HTTPS, S3), dual-format 16:9 + 9:16 & JSON metadata export, and mandatory human-in-the-loop approval before publishing.
---

# Video Automation MCP Skill

Use this skill whenever the user wants to ingest, edit, reframe, normalize, thumbnail, review, approve, or publish videos using the **Video Automation MCP Server** (`video-automation-mcp`).

## Prerequisites & Setup

1. Ensure **Python 3.11+** and **FFmpeg / FFprobe** are installed on the machine.
2. Install the MCP server package:
   ```bash
   pip install git+https://github.com/Abhaysriwastav/MCP-Server.git
   ```
   *(Or clone `https://github.com/Abhaysriwastav/MCP-Server` and run `pip install -e .`.)*
3. Register `video-automation-mcp` in the agent's MCP configuration (`stdio` transport):
   ```json
   {
     "mcpServers": {
       "video-automation": {
         "command": "video-automation-mcp",
         "env": {
           "VIDEO_MCP_WORKSPACE_DIR": "./workspace",
           "VIDEO_MCP_ALLOWED_LOCAL_ROOTS": "."
         }
       }
     }
   }
   ```
4. Optional: launch the live monitoring & approval web dashboard on `http://127.0.0.1:8080`:
   ```bash
   video-automation-dashboard
   ```

---

## Core Workflow (Always Follow This Order)

### 1. Ingest Mixed Sources (`ingest_source` / `probe_media`)
Resolve local paths, `http(s)://` URLs, YouTube URLs (`youtube.com`, `youtu.be`, `shorts/`), or `s3://bucket/key` URIs into the workspace:
- `ingest_source(uri="...")` → returns `source_id` (`src_...`) and `ffprobe` stream metadata.
- `probe_media(source_id_or_path="...")` → inspect codec, resolution, fps, duration, and audio presence.
- `delete_source(source_id="src_...", delete_file=true)` → remove a source record and its workspace-cached file.

### 2. Create & Render an Edit Job (`create_edit_job` → `render_edit_job`)
Build a `DRAFT` job with composable FFmpeg operations and `output_profile`:
- `output_profile`: `"both"` (default — exports **16:9** `1920x1080` + **9:16** `1080x1920` + thumbnails + `probe.json` + `social_kit.json` + `manifest.json`), `"landscape_16x9"`, or `"vertical_9x16"`.
- Supported `operations`:
  - `{"op": "trim", "start_sec": 1.0, "duration_sec": 15.0}`
  - `{"op": "crossfade_merge", "transition_sec": 0.5}` (when multiple `source_ids` are provided)
  - `{"op": "reframe", "aspect_ratio": "9:16", "mode": "crop"}` (`crop` or `pad`)
  - `{"op": "smart_crop", "enabled": true}` (OpenCV face-tracking horizontal focus for `9:16`)
  - `{"op": "remove_silences", "noise_db": -32.0, "min_silence_sec": 0.6}`
  - `{"op": "scale", "width": 1920, "height": 1080}`
  - `{"op": "color_preset", "preset": "cinematic"}` (`original`, `cinematic`, `vivid`, `warm`, `bw`)
  - `{"op": "audio_normalize", "target_i": -14.0}`
  - `{"op": "background_music", "audio_source_id": "src_bgm", "music_volume": 0.22, "ducking": true}`
  - `{"op": "fade", "fade_in_sec": 0.5, "fade_out_sec": 0.5, "total_duration_sec": 15.0}`
  - `{"op": "speed", "factor": 1.25}`
  - `{"op": "text_overlay", "text": "New Release", "position": "bottom"}`
  - `{"op": "watermark", "image_source_id": "src_logo", "position": "bottom-right", "opacity": 0.85}`
  - `{"op": "burn_subtitles", "subtitle_path": "./captions.srt"}`
  - `{"op": "auto_caption", "font_size": 20, "font_color": "white", "position": "bottom", "highlight_bg": true}`
  - `{"op": "voice_clone", "target_language": "es"}` (AI dubbing/translation with OmniVoice/Coqui)
- Call `render_edit_job(job_id="job_...")` to execute the pipeline and move the job to `ready_for_review`.
- Lifecycle controls: pause, resume, or cancel active renders from the dashboard (`POST /api/jobs/{job_id}/pause|resume|cancel`) or Python `tools.editing` (`pause_job`, `resume_job`, `cancel_job`), and remove completed/failed jobs with `delete_job(job_id="job_...", delete_files=true)`.

### 3. Human-in-the-Loop Approval Gate (`request_approval` → `approve_job` / `reject_job`)
**CRITICAL RULE:** Never call `approve_job` or `publish_job` without explicit human confirmation.
1. Call `request_approval(job_id="job_...", notes="Ready for review")` — snapshots SHA-256 checksums of all rendered files and returns `approval_id` (`apr_...`).
2. Present the `16:9` / `9:16` output paths, thumbnails, and `probe.json` summary to the user.
3. Wait for the user's explicit decision:
   - If approved → call `approve_job(approval_id="apr_...", reviewer="<name>", notes="...")`.
   - If rejected → call `reject_job(approval_id="apr_...", reviewer="<name>", reason="...")`, then adjust operations and re-render.

### 4. Publish (`publish_job`)
Publishing is strictly blocked unless the job is `approved` and all artifact SHA-256 checksums match the approved snapshot:
1. Preview first with `publish_job(job_id="job_...", target="local_release", dry_run=true)`.
2. Execute with `publish_job(job_id="job_...", target="local_release", dry_run=false)` (or `"webhook"` / `"s3"`).
3. Local releases include both video formats, thumbnails, `probe.json`, `manifest.json`, and `approval_certificate.json`.
