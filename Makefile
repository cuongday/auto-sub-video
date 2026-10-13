.PHONY: setup setup-full dev build run test test-slow
PORT ?= 8020
TORCH_INDEX = https://download.pytorch.org/whl/cpu
setup:
	python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
	cd frontend && npm install
setup-full: setup
	.venv/bin/pip install torch torchaudio --index-url $(TORCH_INDEX)
	.venv/bin/pip install -e '.[full,dev]'
dev:
	.venv/bin/uvicorn autosub.api:app --host 127.0.0.1 --port $(PORT) --reload & UV=$$!; trap 'kill $$UV' EXIT INT TERM; cd frontend && npm run dev
build:
	cd frontend && npm run build
run: build
	.venv/bin/uvicorn autosub.api:app --host 127.0.0.1 --port $(PORT)
test:
	.venv/bin/pytest -q
test-slow:
	.venv/bin/pytest -q -m slow
