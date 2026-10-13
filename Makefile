.PHONY: setup setup-full up down logs build test test-slow test-minio
# The app runs only through docker compose (it needs the MinIO service).
up:
	docker compose up -d --build
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
