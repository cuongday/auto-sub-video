import os
from pathlib import Path
from ..models import Word

_MODELS: dict = {}

class WhisperASR:
    def __init__(self, model: str = "", language: str = "en"):
        self.language = language
        self.model = model or "large-v3-turbo"

    def _load(self, name: str = ""):
        name = name or self.model
        if name not in _MODELS:
            from faster_whisper import WhisperModel
            _MODELS[name] = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
        return _MODELS[name]

    def transcribe(self, wav16k: Path, progress=None) -> list[Word]:
        segments, info = self._load().transcribe(str(wav16k), language=self.language, word_timestamps=True, vad_filter=True,
                                                 beam_size=5, condition_on_previous_text=False)
        words: list[Word] = []
        for seg in segments:
            for w in seg.words or []:
                if w.word.strip():
                    words.append(Word(text=w.word.strip(), start=round(w.start, 3), end=round(w.end, 3)))
            if progress and info.duration:
                progress(min(1.0, seg.end / info.duration))
        return words

WhisperEN = WhisperASR
