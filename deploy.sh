#!/bin/sh
# Deploy a code change without rebuilding the Docker image.
# The app container runs the code in this folder (docker-compose.dev.yml, enabled by COMPOSE_FILE in .env):
#   - Python (autosub/) reloads by itself on save;
#   - the web UI is served from frontend/dist, so it only needs `npm run build`.
# Rebuild the image (./deploy.sh --image) only after changing dependencies (pyproject.toml/uv.lock,
# frontend/package.json) or the Dockerfile.
set -e
cd "$(dirname "$0")"
if [ "$1" = "--image" ]; then
  (cd frontend && npm ci && npm run build)
  docker compose up -d --build
else
  (cd frontend && npm run build)
  docker compose up -d                  # no-op when nothing changed in the compose config
  docker compose restart auto-sub       # picks up a new frontend/dist and any Python change at once
fi
printf 'Waiting for the app'
for _ in $(seq 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' auto-sub 2>/dev/null)" = healthy ] && { echo ' ready'; exit 0; }
  printf .; sleep 3
done
echo ' not healthy, see: docker compose logs auto-sub' >&2; exit 1
