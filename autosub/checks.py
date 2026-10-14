import importlib.util
import shutil
from pathlib import Path
from . import config

def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None

def engines() -> dict:
    """Which engines can run on this machine, with a hint when they cannot."""
    full = "Chạy: make setup-full"
    return {
        "separate": {"ok": _has("demucs"), "hint": "" if _has("demucs") else full},
        "asr": {"zh": {"ok": _has("funasr"), "hint": "" if _has("funasr") else full},
                "en": {"ok": _has("faster_whisper"), "hint": "" if _has("faster_whisper") else full}},
        "llm": {"gemini": {"ok": bool(config.GCP_PROJECT), "hint": "" if config.GCP_PROJECT else "Đặt GOOGLE_CLOUD_PROJECT trong .env"},
                "openai": {"ok": bool(config.OPENAI_API_KEY), "hint": "" if config.OPENAI_API_KEY else "Đặt OPENAI_API_KEY trong .env"}},
        "tts": {"edge": {"ok": _has("edge_tts"), "hint": "" if _has("edge_tts") else "Chạy: make setup"},
                "vieneu": {"ok": _has("vieneu"), "hint": "" if _has("vieneu") else full}},
    }

def run_checks() -> list[dict]:
    out = []
    def add(name, ok, hint): out.append({"name": name, "ok": bool(ok), "hint": "" if ok else hint})
    try:
        from .storage import get_store
        get_store().ping()
        storage_ok, storage_hint = True, ""
    except Exception as e:  # noqa: BLE001
        storage_ok, storage_hint = False, f"Không kết nối được MinIO ({e}). Kiểm tra service minio trong docker compose"
    add("MinIO", storage_ok, storage_hint)
    add("ffmpeg", shutil.which("ffmpeg") and shutil.which("ffprobe"), "Cài ffmpeg (có ffprobe)")
    from .fonts import FONTS
    missing = [f.file for f in FONTS if not (config.FONTS_DIR / f.file).exists()]
    add("font phụ đề", not missing, f"Thiếu trong fonts/: {', '.join(missing)}")
    add("demucs", _has("demucs"), "Chạy: make setup-full")
    add("funasr (tiếng Trung)", _has("funasr"), "Chạy: make setup-full")
    add("faster-whisper (tiếng Anh)", _has("faster_whisper"), "Chạy: make setup-full")
    add("vieneu", _has("vieneu"), "Chạy: make setup-full")
    add("GOOGLE_CLOUD_PROJECT", config.GCP_PROJECT, "Đặt GOOGLE_CLOUD_PROJECT trong .env")
    if config.ADC_PATH:
        add("ADC_HOST_PATH", Path(config.ADC_PATH).is_file(), f"Không thấy file ADC: {config.ADC_PATH}")
    add("OPENAI_API_KEY", config.OPENAI_API_KEY, "Đặt OPENAI_API_KEY trong .env (chỉ cần khi dùng OpenAI)")
    return out

def test_llm(provider: str, model: str = "") -> dict:
    """One tiny real call to verify credentials."""
    from .llm import get_llm
    try:
        r = get_llm(provider, model).generate_json(
            'Trả về JSON {"ok": true}.', {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            temperature=0)
        return {"ok": bool(r.get("ok")), "error": None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
