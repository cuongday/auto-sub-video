import asyncio
import random
import time
from pathlib import Path
from .. import config
from .base import TTSError

ATTEMPTS = 5

class EdgeTTS:
    name = "edge"
    native_rate = True

    def synthesize(self, text: str, out: Path, voice: str = "", rate: float = 1.0, ref_audio=None) -> Path:
        import edge_tts
        voice = voice or config.EDGE_VOICES[0][0]
        pct = round((rate - 1.0) * 100)
        mp3 = Path(out).with_suffix(".mp3")
        last: Exception | None = None
        # the service intermittently answers NoAudioReceived under parallel load: back off and retry
        for attempt in range(ATTEMPTS):
            try:
                asyncio.run(edge_tts.Communicate(text, voice, rate=f"{pct:+d}%").save(str(mp3)))
                if mp3.exists() and mp3.stat().st_size > 0:
                    return mp3
                last = TTSError("edge-tts không trả về âm thanh")
            except Exception as e:  # noqa: BLE001  (network errors, NoAudioReceived...)
                last = e
            if attempt < ATTEMPTS - 1:
                time.sleep(2 ** attempt + random.uniform(0, 1))
        raise TTSError(f"edge-tts lỗi: {last}")

    def voices(self) -> list[dict]:
        return [{"id": v, "label": label} for v, label in config.EDGE_VOICES]
