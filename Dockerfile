FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/venv/bin:$PATH" \
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
    VIDEO_MCP_FFMPEG_HWACCEL=auto \
    VIDEO_MCP_YOUTUBE_MAX_COMMENTS=80 \
    HF_HOME=/app/workspace/.cache/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-venv \
        python3.11-dev \
        python3-pip \
        ffmpeg \
        git \
        ca-certificates \
        libglib2.0-0 \
        curl \
        fontconfig \
        fonts-dejavu-core \
        nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && python3.11 -m venv /opt/venv

WORKDIR /app

RUN python --version \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "torch==2.8.0+cu128" "torchaudio==2.8.0+cu128" --index-url https://download.pytorch.org/whl/cu128

COPY requirements.txt ./

RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cu128 -r requirements.txt

RUN python -c "import torch; flags = (torch._C._cuda_getArchFlags() or '').split(); print('PyTorch:', torch.__version__, 'CUDA:', torch.version.cuda, 'Archs:', flags); assert torch.version.cuda and torch.version.cuda.startswith('12.8'), f'Expected CUDA 12.8, got {torch.version.cuda}'; assert any('120' in a for a in flags), f'Missing sm_120/compute_120 in {flags}'"

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --no-deps . \
    && mkdir -p /app/workspace /app/workspace/.cache/huggingface

EXPOSE 8080 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD curl -sf http://127.0.0.1:8080/api/overview > /dev/null || exit 1

CMD ["video-automation-dashboard"]