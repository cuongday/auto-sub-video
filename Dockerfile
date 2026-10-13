# syntax=docker/dockerfile:1.7

# ---------- frontend build ----------
FROM node:20-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- runtime ----------
FROM python:3.11-slim-bookworm
ARG FULL=1
ENV PYTHONUNBUFFERED=1 \
    HOME=/data/home \
    HF_HOME=/data/models/huggingface \
    MODELSCOPE_CACHE=/data/models/modelscope \
    TORCH_HOME=/data/models/torch \
    AUTOSUB_WORK_DIR=/work \
    AUTOSUB_PORT=8020 \
    UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/root/.cache/uv \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# ffmpeg (Debian build has libass: `ass`/`subtitles` filters), sox/libsndfile for audio libs
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libsndfile1 ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
WORKDIR /app

# dependencies first (cached layer): only re-run when pyproject.toml / uv.lock change.
# Versions come from uv.lock; torch/torchaudio resolve to the CPU wheels (see [tool.uv.sources]).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project $( [ "$FULL" = "1" ] && echo "--extra full" )

COPY README.md ./
COPY autosub/ autosub/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev $( [ "$FULL" = "1" ] && echo "--extra full" )

COPY fonts/ fonts/
COPY --from=web /web/dist frontend/dist

# /data/models: model downloads (volume); /work: scratch copies of job files (job data lives in MinIO).
# Only these dirs are made writable for the non-root runtime user (no recursive chmod over the venv).
RUN mkdir -p /data/models /data/home /work && chmod 777 /data /data/models /data/home /work
EXPOSE 8020
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"AUTOSUB_PORT\"]}/api/options', timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "mkdir -p $HOME && exec uvicorn autosub.api:app --host 0.0.0.0 --port $AUTOSUB_PORT"]
