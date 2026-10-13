"""VieNeu-TTS v3 Turbo on CPU. One instance runs one inference at a time, so a small pool of
instances (each with cpu_count // workers ONNX threads) synthesizes lines in parallel."""
import os
import threading
from pathlib import Path
import numpy as np
import soundfile as sf
from .. import config
from .base import TTSError

_POOL: list = []
_CREATED = [0]
_COND = threading.Condition()
_CLONES: dict[tuple, object] = {}
_CLONE_LOCK = threading.Lock()

def _new_instance(threads: int = 0):
    try:
        from vieneu import Vieneu
    except ImportError as e:
        raise TTSError("Chưa cài VieNeu: make setup-full") from e
    return Vieneu(mode=config.VIENEU_MODE, threads=threads)

class _Borrow:
    def __enter__(self):
        with _COND:
            while not _POOL and _CREATED[0] >= max(1, config.VOICE_WORKERS):
                _COND.wait()
            if _POOL:
                self.tts = _POOL.pop()
                return self.tts
            _CREATED[0] += 1
        try:
            self.tts = _new_instance(max(1, (os.cpu_count() or 8) // max(1, config.VOICE_WORKERS)))
        except BaseException:
            with _COND:
                _CREATED[0] -= 1; _COND.notify()
            raise
        return self.tts

    def __exit__(self, *exc):
        with _COND:
            _POOL.append(self.tts); _COND.notify()

class VieneuTTS:
    name = "vieneu"
    native_rate = False
    _voices: list[dict] = []

    def _voice_for(self, tts, voice: str, ref_audio: Path | None):
        if ref_audio:
            key = (id(tts), str(ref_audio), Path(ref_audio).stat().st_mtime)
            with _CLONE_LOCK:
                if key not in _CLONES:
                    emb, codes = tts.encode_reference(str(ref_audio))
                    _CLONES[key] = {"speaker_emb": emb, "codes": codes}
                return _CLONES[key]
        if voice:
            if tts.resolve_voice_name(voice) is None:
                raise TTSError(f"Không có giọng VieNeu {voice!r}")
            return voice
        return None

    def synthesize(self, text: str, out: Path, voice: str = "", rate: float = 1.0, ref_audio=None) -> Path:
        with _Borrow() as tts:
            v = self._voice_for(tts, voice, ref_audio)
            pcm = np.asarray(tts.infer(text, voice=v) if v is not None else tts.infer(text), dtype=np.float32).reshape(-1)
            sr = tts.sample_rate
        if len(pcm) == 0:
            raise TTSError("VieNeu không trả về âm thanh")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        sf.write(out, pcm, sr, subtype="PCM_16")
        if abs(rate - 1.0) > 1e-3:
            from ..media import atempo
            tmp = Path(out).with_name("rate.wav")
            atempo(out, tmp, rate)
            tmp.replace(out)
        return Path(out)

    def voices(self) -> list[dict]:
        """Preset voices: [{id, label, gender, featured, default}], editors' picks first."""
        if not VieneuTTS._voices:
            with _Borrow() as tts:
                presets = tts._preset_voices
                default = tts._default_voice
                for label, vid in tts.list_preset_voices():
                    meta = presets.get(vid, {})
                    VieneuTTS._voices.append({
                        "id": vid, "label": label.lstrip("⭐ ").strip(), "gender": meta.get("gender", ""),
                        "featured": meta.get("featured") is not None, "default": vid == default})
        return VieneuTTS._voices
