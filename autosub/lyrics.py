"""Spot ASR lines that are probably song lyrics (Demucs keeps singing in the vocal stem).

Measured on real Douyin clips (2026-10-16): a foreign-language interview has the voice stem 30-40 dB
above the music; an English song in a Chinese vlog sits level with the music (-6..+3 dB). Same-language
speech over loud music (a survival vlog) can also sit within 8 dB, so loudness alone is not enough:
a line is flagged only when it is mostly in a foreign script AND the voice is not clearly above the
music. Flagged lines stay in the table for the user to confirm or delete."""
import re
import numpy as np
from .models import Lang, Segment

FLAG = "lyrics"
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_LATIN = re.compile(r"[A-Za-z]")
MIN_FOREIGN = 0.6          # share of letters not in the video language
MAX_VOICE_OVER_MUSIC = 8.0 # dB: speech is well above this; singing sits at or below it

def foreign_ratio(text: str, lang: Lang) -> float:
    cjk, latin = len(_CJK.findall(text)), len(_LATIN.findall(text))
    total = cjk + latin
    if total == 0:
        return 0.0
    return (latin if lang == "zh" else cjk) / total

def _db(x: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if len(x) else 0.0
    return 20 * np.log10(max(rms, 1e-6))

def levels(voice: np.ndarray, music: np.ndarray, sr: int, segs: list[Segment]) -> list[tuple[float, float]]:
    """(voice dBFS, music dBFS) under each line."""
    out = []
    for s in segs:
        a, b = int(s.start * sr), max(int(s.start * sr) + 1, int(s.end * sr))
        out.append((_db(voice[a:b]), _db(music[a:b])))
    return out

def is_lyrics(text: str, voice_db: float, music_db: float, lang: Lang) -> bool:
    return foreign_ratio(text, lang) >= MIN_FOREIGN and voice_db - music_db < MAX_VOICE_OVER_MUSIC

def flag_lyrics(segs: list[Segment], lv: list[tuple[float, float]], lang: Lang) -> list[Segment]:
    if not segs or len(lv) != len(segs):
        return segs
    for s, (v, m) in zip(segs, lv):
        s.flags = [f for f in s.flags if f != FLAG]
        if is_lyrics(s.source, v, m, lang):
            s.flags.append(FLAG)
    return segs
