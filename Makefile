.PHONY: setup up down logs build test test-slow test-minio
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
setup:
	python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
	cd frontend && npm install
test:
	.venv/bin/pytest -q
test-slow:
	.venv/bin/pytest -q -m slow
test-minio:
	.venv/bin/pytest -q -m minio
