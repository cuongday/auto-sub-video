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

TTS_CACHE_PREFIX = "tts-cache/"
EXTS = (".mp3", ".wav")

def cache_dir() -> Path:
    from .. import config
    return config.WORK_DIR / "_tts-cache"

def cached_synthesize(engine: TTSEngine, text: str, voice: str, rate: float, ref_audio: Path | None,
                      local_dir: Path | None = None) -> Path:
    """Synthesize through a cache shared by all jobs: object storage tts-cache/<key>.<ext> is the source
    of truth, `local_dir` (default: scratch area) keeps a local copy for the processing tools."""
    from ..storage import get_store
    st = get_store()
    key = cache_key(engine.name, voice, rate, file_sha(ref_audio) or _custom_sha(voice), text)
    local_dir = Path(local_dir or cache_dir()); local_dir.mkdir(parents=True, exist_ok=True)
    with _key_lock(key):            # identical lines synthesized in parallel are produced once
        hit = next(iter(local_dir.glob(key + ".*")), None)
        if hit is not None and hit.suffix in EXTS:
            return hit
        for ext in EXTS:
            if st.get_file(TTS_CACHE_PREFIX + key + ext, local_dir / (key + ext)):
                return local_dir / (key + ext)
        tmp_dir = Path(tempfile.mkdtemp(dir=local_dir, prefix=".tmp-"))
        try:
            produced = engine.synthesize(text, tmp_dir / "out.wav", voice=voice, rate=rate, ref_audio=ref_audio)
            final = local_dir / (key + Path(produced).suffix)
            st.put_file(TTS_CACHE_PREFIX + final.name, Path(produced))
            Path(produced).replace(final)
            return final
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

def _custom_sha(voice: str) -> str:
    """Content tag of a named cloned voice, so re-recording it does not reuse old cached lines."""
    from ..voices import PREFIX
    if not voice.startswith(PREFIX):
        return ""
    from ..storage import get_store
    info = get_store().stat(f"voices/{voice[len(PREFIX):]}/ref.wav")
    return info.etag if info else ""

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

def _key_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())
