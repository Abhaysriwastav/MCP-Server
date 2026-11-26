# Agensi.io Skill Listing Guide

Use this guide when submitting **Video Automation MCP** on [Agensi.io/sell](https://www.agensi.io/sell).

---

## Step 1 — Skill ZIP Upload

Upload: **`dist/video-automation-skill.zip`** (contains `SKILL.md` from `skill/SKILL.md`).

If you edit `skill/SKILL.md`, regenerate the ZIP with:

```bash
python3 -c "
import zipfile
from pathlib import Path
Path('dist').mkdir(exist_ok=True)
with zipfile.ZipFile('dist/video-automation-skill.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.write('skill/SKILL.md', arcname='SKILL.md')
"
```

---

## Step 2 — Skill Details

- **Skill Name** *(under 60 chars)*:
  `Video Automation MCP (Approval-Gated)`

- **Summary** *(one line, up to 300 chars)*:
  `Automate video editing from local, HTTP, or S3 sources with dual 16:9 + 9:16 exports, metadata manifests, and human-in-the-loop publishing approval.`

- **Full Description**:
  ```markdown
  Turn any AI agent into a safe, production-ready video editing pipeline.

  **What it solves:**
  - **Mixed-Source Ingest**: Pull clips from local folders (root-jailed), HTTPS URLs (SSRF-protected), or S3 buckets.
  - **Composable FFmpeg Editing**: Trim, concatenate, reframe, scale, normalize audio (EBU R128), add fades, adjust speed, burn subtitles, and apply text or watermark overlays.
  - **Dual-Format + Metadata Output**: Automatically exports both landscape (`16:9`, 1920×1080) and vertical (`9:16`, 1080×1920) MP4s alongside preview thumbnails, `probe.json`, and `manifest.json`.
  - **Human-in-the-Loop Approval Gate**: Snapshots SHA-256 checksums of every rendered file and blocks publishing until a human reviewer explicitly approves—preventing unreviewed or tampered exports.
  - **Live Web Dashboard**: Monitor active renders, preview videos in-browser, approve/reject, and configure settings at `http://127.0.0.1:8080`.
  ```

---

## Step 3 — See it in action (Demo)

- **The request (what the buyer types)**:
  ```text
  Trim /Movies/launch_4k.mp4 to the first 15 seconds, normalize audio to -14 LUFS, export both 16:9 and 9:16 formats, and stage it for my approval before publishing.
  ```

- **The result (what your agent delivers)**:
  ```markdown
  ## Summary
  Ingested `launch_4k.mp4` (`3840×2160`, 25 fps), applied trim + EBU R128 loudness normalization, and rendered both `16:9` and `9:16` outputs with preview thumbnails. Staged for human approval.

  | Artifact | Format / Resolution | Size |
  | :--- | :--- | :--- |
  | `landscape_16x9.mp4` | H.264 / AAC (`1920×1080`) | 5.4 MB |
  | `vertical_9x16.mp4` | H.264 / AAC (`1080×1920`) | 6.1 MB |
  | `video_16x9_thumb.jpg` | JPEG preview frame | 32 KB |
  | `video_9x16_thumb.jpg` | JPEG preview frame | 21 KB |
  | `manifest.json` & `probe.json` | Structured metadata | 5 KB |

  ```json
  {
    "job_id": "job_74adb0055856",
    "status": "pending_approval",
    "approval_id": "apr_9c12e4f8a102",
    "sha256_verified": true
  }
  ```

  **Next steps**
  - Review the `16:9` and `9:16` previews in the dashboard or file paths above.
  - Reply **"Approve"** (or reject with feedback) to unlock publishing to `local_release`, `webhook`, or `s3`.
  ```

---

## Step 4 & 5 — Compatibility & Pricing

- **Compatibility Note**:
  `Requires Python 3.11+ and FFmpeg/FFprobe. Works with Claude Code, Cursor, VS Code Copilot, Codex CLI, Gemini CLI, and Antigravity.`
- **Pricing**: Choose **Free** or **One-time** (e.g., `$9`–`$19`).

---

## Tags, Categories, Use Cases

- **Categories** *(pick up to 3)*: `Agents & Orchestration`, `APIs & Backend`, `DevOps & Cloud`
- **Tags**: `mcp`, `video-editing`, `ffmpeg`, `human-in-the-loop`, `automation`
- **Use cases**:
  - `Automated 16:9 + 9:16 social video rendering`
  - `Approval-gated video publishing`
  - `Batch FFmpeg post-production`

---

## Permissions & Documentation

- **Requires**: `Python 3.11+`, `FFmpeg & FFprobe`
- **Optional**: `AWS S3 / boto3 (for s3:// sources and S3 publishing)`
- **Tools Used**:
  - `Terminal / Shell`
  - `Read Files`
  - `Write Files`
  - `Network Access`
  - `Environment Variables`
- **File Scopes**: `workspace/**`, `src/video_mcp/**`
- **Documentation Link**: `https://github.com/Abhaysriwastav/MCP-Server`
