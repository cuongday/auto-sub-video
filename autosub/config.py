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

PROJECTS_DIR = Path(os.environ.get("AUTOSUB_PROJECTS_DIR", ROOT / "projects")).resolve()
CACHE_DIR = ROOT / ".cache"
FONTS_DIR = ROOT / "fonts"
FRONTEND_DIST = ROOT / "frontend" / "dist"
PORT = int(os.environ.get("AUTOSUB_PORT", "8020"))

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

ASR_MODELS = {
    "zh": [("paraformer-zh", "Paraformer (FunASR) — tiếng Trung")],
    "en": [("large-v3-turbo", "Whisper large-v3-turbo — chính xác"),
           ("medium", "Whisper medium"), ("small", "Whisper small — nhanh")],
}

EDGE_VOICES = [("vi-VN-HoaiMyNeural", "Hoài My (nữ)"), ("vi-VN-NamMinhNeural", "Nam Minh (nam)")]
VIENEU_MODE = os.environ.get("VIENEU_MODE", "v3turbo")
VOICE_WORKERS = int(os.environ.get("AUTOSUB_VOICE_WORKERS", "4"))
EDGE_WORKERS = 3          # more parallel requests make edge-tts drop answers

FFMPEG_PRESET = os.environ.get("AUTOSUB_FFMPEG_PRESET", "veryfast")
FFMPEG_CRF = int(os.environ.get("AUTOSUB_FFMPEG_CRF", "20"))
