"""VieNeu-TTS v3 Turbo on CPU (ONNX Runtime) or an NVIDIA GPU (PyTorch). One instance runs one inference
at a time, so a small pool of instances synthesizes lines in parallel: on CPU each gets cpu_count // workers
ONNX threads; on GPU a couple of instances share the card. Changing the device empties the pool."""
import os
import threading
import time
from pathlib import Path
import numpy as np
import soundfile as sf
from .. import config, gpu
from .base import TTSError

_POOL: list = []
_CREATED = [0]
_COND = threading.Condition()
_DEVICE = ["", ""]          # [device the pool was built for ("cpu" | "cuda"), fallback note]
_REQ: list = ["", 0.0]      # [requested device, read at] — the app setting, re-read every few seconds
_REQ_TTL = 5.0
_CLONES: dict[tuple, object] = {}
_CLONE_LOCK = threading.Lock()

def requested_device() -> str:
    """The web setting wins over VIENEU_DEVICE from .env."""
    if _REQ[0] and time.time() - _REQ[1] < _REQ_TTL:
        return _REQ[0]
    try:
        from ..store import load_app_settings
        v = load_app_settings().get("vieneu_device")
    except Exception:  # noqa: BLE001  (storage down: use the env default)
        v = None
    _REQ[:] = [v if v in gpu.DEVICES else config.VIENEU_DEVICE, time.time()]
    return _REQ[0]

def current_device() -> tuple[str, str]:
    """('cpu' | 'cuda', note) that new VieNeu work runs on."""
    return gpu.resolve(requested_device())

def workers() -> int:
    return max(1, config.VIENEU_GPU_WORKERS if current_device()[0] == "cuda" else config.VOICE_WORKERS)

def _new_instance(device: str, threads: int = 0):
    try:
        from vieneu import Vieneu
    except ImportError as e:
        raise TTSError("Chưa cài VieNeu: make setup-full") from e
    if device == "cuda":
        try:
            return Vieneu(mode=config.VIENEU_MODE, device="cuda", backend="pytorch")
        except Exception as e:  # noqa: BLE001
            raise TTSError(f"Không chạy được VieNeu trên GPU ({e}). Chọn “Chạy trên: CPU” ở mục Thuyết minh") from e
    return Vieneu(mode=config.VIENEU_MODE, device="cpu", backend="onnx", threads=threads)

def _switch_if_needed(device: str, note: str) -> None:
    """Called with _COND held: drop idle instances built for another device."""
    if _DEVICE[0] != device:
        _POOL.clear()
        _CREATED[0] = 0
        with _CLONE_LOCK:
            _CLONES.clear()
        _DEVICE[0] = device
    _DEVICE[1] = note

class _Borrow:
    def __enter__(self):
        device, note = current_device()
        limit = workers()
        with _COND:
            _switch_if_needed(device, note)
            while not _POOL and _CREATED[0] >= limit:
                _COND.wait()
            if _POOL:
                self.tts = _POOL.pop()
                self.device = device
                return self.tts
            _CREATED[0] += 1
        self.device = device
        try:
            self.tts = _new_instance(device, max(1, (os.cpu_count() or 8) // max(1, config.VOICE_WORKERS)))
        except BaseException:
            with _COND:
                _CREATED[0] -= 1; _COND.notify()
            raise
        return self.tts

    def __exit__(self, *exc):
        with _COND:
            if _DEVICE[0] == self.device:       # an instance from before a device switch is dropped
                _POOL.append(self.tts)
            else:
                _CREATED[0] = max(0, _CREATED[0] - 1)
            _COND.notify()

def reset_pool() -> None:
    """Forget every idle instance (e.g. after the user switches CPU/GPU)."""
    _REQ[:] = ["", 0.0]
    with _COND:
        _POOL.clear(); _CREATED[0] = 0; _DEVICE[0] = ""
        with _CLONE_LOCK:
            _CLONES.clear()
        _COND.notify_all()

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
        from .. import voices as custom
        if custom.is_custom(voice) and not ref_audio:      # named cloned voice stored in MinIO
            ref_audio, voice = custom.ref_path(voice, Path(out).parent), ""
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
        """Cloned voices first, then presets: [{id, label, gender, featured, default, custom}]."""
        from .. import voices as custom
        mine = [{"id": v.id, "label": f"{v.name} — giọng nhân bản" + (f" · {v.note}" if v.note else ""),
                 "gender": v.gender, "featured": False, "default": False, "custom": True}
                for v in custom.list_voices()]
        return mine + self._presets()

    def _presets(self) -> list[dict]:
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
