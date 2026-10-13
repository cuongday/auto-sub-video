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
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/data/home \
    HF_HOME=/data/models/huggingface \
    MODELSCOPE_CACHE=/data/models/modelscope \
    TORCH_HOME=/data/models/torch \
    AUTOSUB_WORK_DIR=/work \
    AUTOSUB_PORT=8020

# ffmpeg (Debian build has libass: `ass`/`subtitles` filters), sox/libsndfile for audio libs
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libsndfile1 ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY autosub/ autosub/
# torch CPU wheels first so demucs/funasr don't pull the CUDA build
RUN pip install -e . \
    && if [ "$FULL" = "1" ]; then \
         pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
         && pip install -e '.[full]'; \
       fi
COPY fonts/ fonts/
COPY --from=web /web/dist frontend/dist

# /data/models: model downloads (volume); /work: scratch copies of job files (job data lives in MinIO)
RUN mkdir -p /data/models /data/home /work && chmod -R 777 /data /work
EXPOSE 8020
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"AUTOSUB_PORT\"]}/api/options', timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "mkdir -p $HOME && exec uvicorn autosub.api:app --host 0.0.0.0 --port $AUTOSUB_PORT"]
