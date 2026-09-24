# ArthaNeeti API: FastAPI + LangGraph agents + the three MCP servers they spawn.
# Build from the repository root:  docker build -f docker/backend.Dockerfile .

FROM python:3.11-slim AS build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install -r requirements.txt


FROM python:3.11-slim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    LLM_RATE_LIMITER_DB=/app/var/llm_rate_limiter.db

RUN useradd --create-home --uid 10001 arthaneeti
WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY agents ./agents
COPY app ./app
COPY mcp_servers ./mcp_servers
COPY shared ./shared
COPY assets/fonts ./assets/fonts
COPY assets/brand/mark.png assets/brand/wordmark.png ./assets/brand/

# Uploaded annual reports and the rate-limiter ledger are written at runtime.
RUN mkdir -p data/uploads var && chown -R arthaneeti:arthaneeti data var
USER arthaneeti

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/', timeout=4)"

# --proxy-headers: behind Render's router or the nginx container, the client
# address comes from X-Forwarded-For, which the per-IP throttle depends on.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
