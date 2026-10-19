"""Reading pace of a TTS voice in syllables per minute (Vietnamese: one syllable per word)."""
import tempfile
from pathlib import Path
from .. import media
from ..storage import get_store, read_json, write_json
from ..timing import trim_silence
from ..tts.base import TTSEngine, _custom_sha, cache_key, cached_synthesize, file_sha

DEFAULT_SPM = 190
PACE_KEY = "review/pace.json"
PACE_SAMPLE = ("Ở phần trước, nhóm bạn trẻ tìm thấy tấm bản đồ cũ trong căn nhà bỏ hoang, "
               "và một chuyến đi đầy bí ẩn bắt đầu ngay từ đó.")
SR = 24000

def syllables(text: str) -> int:
    return sum(1 for w in text.split() if any(c.isalnum() for c in w))

def minutes_of(text: str, spm: float) -> float:
    return syllables(text) / spm

def measure_spm(engine: TTSEngine, voice: str, rate: float, ref_audio: Path | None) -> float:
    """Speak the sample once per voice/rate; cached in object storage. Any failure -> DEFAULT_SPM."""
    try:
        st = get_store()
        key = cache_key(engine.name, voice, rate, file_sha(ref_audio) or _custom_sha(voice), PACE_SAMPLE)
        cached = read_json(st, PACE_KEY, default={})
        if key in cached:
            return cached[key]
        with tempfile.TemporaryDirectory() as d:
            wav = cached_synthesize(engine, PACE_SAMPLE, voice, rate, ref_audio, local_dir=Path(d))
            seconds = len(trim_silence(media.decode_mono(wav, SR), SR)) / SR
        spm = round(syllables(PACE_SAMPLE) / (seconds / 60), 1)
        write_json(st, PACE_KEY, {**read_json(st, PACE_KEY, default={}), key: spm})
        return spm
    except Exception:  # noqa: BLE001  (a pace estimate never blocks the script)
        return DEFAULT_SPM
