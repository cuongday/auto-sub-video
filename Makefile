.PHONY: setup setup-full up up-gpu dev dev-web down logs build test test-slow test-minio
# The app runs only through docker compose (it needs the MinIO service).
up:
	docker compose up -d --build
# NVIDIA GPU for VieNeu (see docker-compose.gpu.yml)
up-gpu:
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
# dev: use the code in this folder (no rebuild per change). Back to the baked image: make up
dev: build
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
# rebuild frontend/dist on every save (refresh the page to see it); or `cd frontend && npm run dev` on :5175
dev-web:
	cd frontend && npm run build -- --watch
down:
	docker compose down
logs:
	docker compose logs -f auto-sub
build:
	cd frontend && npm run build
# local env for development and tests only
# needs uv: https://docs.astral.sh/uv/getting-started/installation/
setup:
	uv sync
	cd frontend && npm install
setup-full:
	uv sync --extra full
test:
	uv run pytest -q
test-slow:
	uv run pytest -q -m slow
test-minio:
	uv run pytest -q -m minio
