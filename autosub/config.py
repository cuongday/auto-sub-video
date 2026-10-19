import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# .env at repo root; real environment variables take precedence
load_dotenv(ROOT / ".env", override=False)

# ADC_HOST_PATH points at the gcloud ADC json; google-auth reads GOOGLE_APPLICATION_CREDENTIALS
ADC_PATH = os.environ.get("ADC_HOST_PATH")
if ADC_PATH and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ADC_PATH
_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if _creds and (not Path(_creds).is_file() or Path(_creds).stat().st_size == 0):
    # compose mounts an empty placeholder when no ADC file is configured (OpenAI-only setups)
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS")
    ADC_PATH = None

# All job data lives in MinIO; WORK_DIR is only a local scratch cache that processing tools read/write.
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "autosub")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "0") == "1"
WORK_DIR = Path(os.environ.get("AUTOSUB_WORK_DIR", "/work")).resolve()
# host folder mounted read-only (HOST_ROOT in compose); videos are picked inside it from the web UI
HOST_ROOT = Path(os.environ.get("AUTOSUB_HOST_ROOT", "/host"))
WORK_MAX_BYTES = int(float(os.environ.get("AUTOSUB_WORK_MAX_GB", "20")) * (1 << 30))
FONTS_DIR = ROOT / "fonts"
FRONTEND_DIST = ROOT / "frontend" / "dist"
PORT = int(os.environ.get("AUTOSUB_PORT", "8020"))
APP_PASSWORD = os.environ.get("AUTOSUB_PASSWORD", "")   # empty: no login (default, app bound to 127.0.0.1)

GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
GCP_LOCATION = os.environ.get("GOOGLE_LOCATION") or os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
GEMINI_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

def _with_default(models: list[tuple[str, str]], default: str) -> list[tuple[str, str]]:
    return models if any(m == default for m, _ in models) else [(default, default)] + models

# Suggestions only: the UI lets the user type any model id.
GEMINI_MODELS = _with_default([
    ("gemini-2.5-flash", "Gemini 2.5 Flash — cân bằng"),
    ("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite — nhanh, rẻ"),
    ("gemini-2.5-pro", "Gemini 2.5 Pro — dịch kỹ hơn"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash — mới nhất"),
], GEMINI_MODEL)
OPENAI_MODELS = _with_default([
    ("gpt-4.1-mini", "GPT-4.1 mini — rẻ, nhanh"),
    ("gpt-4.1", "GPT-4.1"),
    ("gpt-4o-mini", "GPT-4o mini"),
    ("gpt-4o", "GPT-4o"),
], OPENAI_MODEL)

_WHISPER_MODELS = [("large-v3-turbo", "Whisper large-v3-turbo — chính xác"),
                   ("medium", "Whisper medium"), ("small", "Whisper small — nhanh")]
ASR_MODELS = {
    "zh": [("paraformer-zh", "Paraformer (FunASR) — tiếng Trung")],
    "en": _WHISPER_MODELS,
    "ko": _WHISPER_MODELS,
}

EDGE_VOICES = [("vi-VN-HoaiMyNeural", "Hoài My (nữ)"), ("vi-VN-NamMinhNeural", "Nam Minh (nam)")]
VIENEU_MODE = os.environ.get("VIENEU_MODE", "v3turbo")
# where VieNeu runs: "cpu" (ONNX Runtime, every machine), "cuda" (PyTorch on an NVIDIA GPU, needs the GPU
# image), "auto" (GPU when one is usable, else CPU). The web UI can override it (app setting vieneu_device).
VIENEU_DEVICE = os.environ.get("VIENEU_DEVICE", "auto").strip().lower()
VIENEU_GPU_WORKERS = int(os.environ.get("AUTOSUB_VIENEU_GPU_WORKERS", "2"))   # parallel lines on one GPU
VOICE_WORKERS = int(os.environ.get("AUTOSUB_VOICE_WORKERS", "4"))
EDGE_WORKERS = 3          # more parallel requests make edge-tts drop answers
DOUYIN_WORKERS = int(os.environ.get("AUTOSUB_DOUYIN_WORKERS", "4"))   # parallel CDN downloads

FFMPEG_PRESET = os.environ.get("AUTOSUB_FFMPEG_PRESET", "veryfast")
FFMPEG_CRF = int(os.environ.get("AUTOSUB_FFMPEG_CRF", "20"))
