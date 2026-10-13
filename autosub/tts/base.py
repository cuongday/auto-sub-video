import hashlib
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Protocol

class TTSError(Exception):
    pass

class TTSEngine(Protocol):
    name: str
    native_rate: bool          # engine can speak faster natively (better than atempo)
    def synthesize(self, text: str, out: Path, voice: str = "", rate: float = 1.0, ref_audio: Path | None = None) -> Path: ...
    def voices(self) -> list[dict]: ...

def file_sha(path: Path | None) -> str:
    if not path:
        return ""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]

def cache_key(engine: str, voice: str, rate: float, ref_sha: str, text: str) -> str:
    raw = "\x1f".join([engine, voice, f"{rate:.3f}", ref_sha, text])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

def cached_synthesize(engine: TTSEngine, text: str, voice: str, rate: float, ref_audio: Path | None,
                      cache_dir: Path) -> Path:
    """Synthesize into a shared cache (reused across jobs and re-renders)."""
    key = cache_key(engine.name, voice, rate, file_sha(ref_audio), text)
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    with _key_lock(key):            # identical lines synthesized in parallel are produced once
        hit = next(iter(cache_dir.glob(key + ".*")), None)
        if hit is not None:
            return hit
        tmp_dir = Path(tempfile.mkdtemp(dir=cache_dir, prefix=".tmp-"))
        try:
            produced = engine.synthesize(text, tmp_dir / "out.wav", voice=voice, rate=rate, ref_audio=ref_audio)
            final = cache_dir / (key + Path(produced).suffix)
            Path(produced).replace(final)
            return final
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

def _key_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())
