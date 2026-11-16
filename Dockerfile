FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIDEO_MCP_WORKSPACE_DIR=/app/workspace \
    VIDEO_MCP_DB_PATH=/app/workspace/video_mcp.db \
    VIDEO_MCP_RELEASE_DIR=/app/workspace/releases \
    VIDEO_MCP_ALLOWED_LOCAL_ROOTS=/app/workspace \
    VIDEO_MCP_DASHBOARD_HOST=0.0.0.0 \
    VIDEO_MCP_DASHBOARD_PORT=8080 \
    VIDEO_MCP_HOST=0.0.0.0 \
    VIDEO_MCP_PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && mkdir -p /app/workspace

EXPOSE 8080 8000

CMD ["video-automation-dashboard"]
