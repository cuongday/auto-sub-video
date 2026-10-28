"""Make one TTS line fit the time it is allowed to use."""
from dataclasses import dataclass
from pathlib import Path
import soundfile as sf
from . import media
from .models import Segment
from .timing import MAX_SPEED, trim_silence
from .tts.base import TTSEngine, cached_synthesize

SR = 44100
TOLERANCE = 0.02

@dataclass
class FitResult:
    path: Path
    duration: float
    speed: float
    overflow: bool

def _load(path: Path):
    pcm = trim_silence(media.decode_mono(path, SR), SR)
    return pcm, len(pcm) / SR

def fit_segment(engine: TTSEngine, seg: Segment, slot: float, voice: str, base_rate: float,
                ref_audio: Path | None, out_wav: Path, cache_dir: Path | None = None, cancel=None) -> FitResult:
    out_wav = Path(out_wav); out_wav.parent.mkdir(parents=True, exist_ok=True)
    raw = cached_synthesize(engine, seg.vi, voice, base_rate, ref_audio, cache_dir)
    pcm, d0 = _load(raw)
    if d0 <= slot + TOLERANCE or d0 == 0:
        sf.write(out_wav, pcm, SR, subtype="PCM_16")
        return FitResult(out_wav, d0, 1.0, False)

    s = min(d0 / slot, MAX_SPEED)
    if engine.native_rate:
        raw2 = cached_synthesize(engine, seg.vi, voice, round(base_rate * s, 3), ref_audio, cache_dir)
        pcm, d1 = _load(raw2)
        tempo_left = MAX_SPEED / max(1.0, d0 / max(d1, 1e-6))
    else:
        d1, tempo_left = d0, MAX_SPEED
    sf.write(out_wav, pcm, SR, subtype="PCM_16")
    if d1 > slot + TOLERANCE:
        r = min(d1 / slot, tempo_left)
        if r > 1.0 + 1e-3:
            tmp = out_wav.with_name(out_wav.stem + ".tempo.wav")
            media.atempo(out_wav, tmp, r, cancel=cancel)
            tmp.replace(out_wav)
    final = sf.info(out_wav).duration
    return FitResult(out_wav, final, round(d0 / max(final, 1e-6), 3), final > slot + TOLERANCE)
