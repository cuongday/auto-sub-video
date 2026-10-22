"""Whisper over a film that mixes two languages, e.g. a Vietnamese voice-over ("Thuyết minh") that leaves some scenes
in the original Chinese. Speech is cut into windows at pauses, each window's language is detected among a few
candidates, then each language is transcribed in one pass over its own windows (times stay those of the film)."""
from pathlib import Path
from ..models import Word
from .whisper_en import WhisperASR

SR = 16000
DETECT_MODEL = "small"   # tells Vietnamese from Chinese as well as large-v3-turbo on a dubbed film, ~3x faster
WINDOW_S = 28.0          # under Whisper's 30 s input: one detection sees a whole window
JOIN_GAP_S = 1.0         # speech closer than this stays in one window

def windows(speech: list[dict], sr: int = SR) -> list[tuple[int, int]]:
    """VAD speech chunks (samples) grouped into windows: joined across short pauses, never past WINDOW_S."""
    out: list[list[int]] = []
    for c in speech:
        if out and c["start"] - out[-1][1] < JOIN_GAP_S * sr and c["end"] - out[-1][0] <= WINDOW_S * sr:
            out[-1][1] = c["end"]
        else:
            out.append([c["start"], c["end"]])
    return [(a, z) for a, z in out]

def pick(probs: dict[str, float], langs: tuple[str, ...]) -> str:
    """The most likely candidate language (the first one when none is heard at all)."""
    return max(langs, key=lambda l: probs.get(l, 0.0))

class MixedWhisperASR(WhisperASR):
    def __init__(self, model: str = "", languages: tuple[str, ...] = ("vi", "zh")):
        super().__init__(model, languages[0])
        self.languages = languages

    def transcribe(self, wav16k: Path, progress=None) -> list[Word]:
        from faster_whisper import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        m = self._load()
        detector = self._load(DETECT_MODEL)
        audio = decode_audio(str(wav16k), sampling_rate=SR)
        wins = windows(get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500, speech_pad_ms=200)))
        if not wins:
            return []
        total = sum(z - a for a, z in wins) * 2       # detection, then transcription, over all speech
        done = 0
        by_lang: dict[str, list[tuple[int, int]]] = {}
        for a, z in wins:
            _, _, probs = detector.detect_language(audio=audio[a:z])
            by_lang.setdefault(pick(dict(probs), self.languages), []).append((a, z))
            done += z - a
            if progress:
                progress(min(1.0, done / total))
        words: list[Word] = []
        for lang, ws in by_lang.items():
            clips = [t for a, z in ws for t in (a / SR, z / SR)]
            segments, _ = m.transcribe(audio, language=lang, clip_timestamps=clips, word_timestamps=True,
                                       beam_size=5, condition_on_previous_text=False)
            for seg in segments:
                words += [Word(text=w.word.strip(), start=round(w.start, 3), end=round(w.end, 3))
                          for w in seg.words or [] if w.word.strip()]
            done += sum(z - a for a, z in ws)
            if progress:
                progress(min(1.0, done / total))
        return sorted(words, key=lambda w: w.start)
