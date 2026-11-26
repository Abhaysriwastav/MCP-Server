FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    VIDEO_MCP_WORKSPACE_DIR=/app/workspace \
    VIDEO_MCP_DB_PATH=/app/workspace/video_mcp.db \
    VIDEO_MCP_RELEASE_DIR=/app/workspace/releases \
    VIDEO_MCP_ALLOWED_LOCAL_ROOTS=/app/workspace \
    VIDEO_MCP_DASHBOARD_HOST=0.0.0.0 \
    VIDEO_MCP_DASHBOARD_PORT=8080 \
    VIDEO_MCP_HOST=0.0.0.0 \
    VIDEO_MCP_PORT=8000 \
    VIDEO_MCP_WHISPER_DEVICE=auto \
    VIDEO_MCP_WHISPER_COMPUTE_TYPE=auto \
    VIDEO_MCP_OMNIVOICE_DEVICE=auto \
    VIDEO_MCP_FFMPEG_HWACCEL=auto

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml requirements.txt README.md ./
COPY src ./src

RUN pip3 install --no-cache-dir --upgrade pip \
    && pip3 install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cu124 \
    && pip3 install --no-cache-dir -r requirements.txt \
    && pip3 install --no-cache-dir --no-deps . \
    && mkdir -p /app/workspace

EXPOSE 8080 8000

CMD ["video-automation-dashboard"]
