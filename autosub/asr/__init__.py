import importlib.util
from ..models import Lang
from .base import ASR

def available(lang: Lang) -> tuple[bool, str]:
    mod = "funasr" if lang == "zh" else "faster_whisper"
    ok = importlib.util.find_spec(mod) is not None
    return ok, "" if ok else f"Chưa cài {mod}: make setup-full"

def get_asr(lang: Lang, model: str = "", diarize: bool = False) -> ASR:
    ok, why = available(lang)
    if not ok:
        raise RuntimeError(why)
    if lang == "zh":
        from .funasr_zh import FunASRZH
        return FunASRZH(model, diarize=diarize)
    from .whisper_en import WhisperEN
    return WhisperEN(model)

__all__ = ["ASR", "available", "get_asr"]
