from .base import TTSEngine, TTSError, cached_synthesize

def get_tts(name: str) -> TTSEngine:
    if name == "edge":
        from .edge import EdgeTTS
        return EdgeTTS()
    if name == "vieneu":
        from .vieneu_tts import VieneuTTS
        return VieneuTTS()
    raise TTSError(f"Không hỗ trợ TTS {name!r}")

__all__ = ["TTSEngine", "TTSError", "cached_synthesize", "get_tts"]
