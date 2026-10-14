"""Named cloned voices for VieNeu, shared by every job.

Each voice is stored in MinIO as voices/<name>/ref.wav (a cleaned 3-15 s reference clip, mono 24 kHz)
plus voices/<name>/meta.json. Jobs refer to it as tts_voice = "custom:<name>"."""
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
import soundfile as sf
from . import media, proc
from .storage import get_store, read_json, write_json

PREFIX = "custom:"
MIN_SECONDS, MAX_SECONDS = 3.0, 15.0
_NAME = re.compile(r"^[\w][\w .\-]{0,59}$")

class VoiceError(Exception):
    pass

@dataclass
class CustomVoice:
    name: str
    gender: str = ""
    note: str = ""
    duration: float = 0.0
    created: float = 0.0

    @property
    def id(self) -> str:
        return PREFIX + self.name

def is_custom(voice: str) -> bool:
    return bool(voice) and voice.startswith(PREFIX)

def _key(name: str, f: str) -> str:
    return f"voices/{name}/{f}"

def _check_name(name: str) -> str:
    name = name.strip()
    if not _NAME.match(name):
        raise VoiceError("Tên giọng chỉ gồm chữ, số, khoảng trắng, dấu chấm, gạch ngang (tối đa 60 ký tự)")
    return name

def create(name: str, audio: Path, *, gender: str = "", note: str = "", start: float = 0.0,
           length: float | None = None, overwrite: bool = False) -> CustomVoice:
    """Normalize `audio` (any format ffmpeg reads) into a reference clip and store it under `name`."""
    name = _check_name(name)
    st = get_store()
    if not overwrite and st.stat(_key(name, "meta.json")) is not None:
        raise VoiceError(f"Đã có giọng tên {name!r}")
    from . import config
    tmp_dir = config.WORK_DIR / "_voices"; tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / f"voice-{int(time.time() * 1000)}.wav"      # the source may sit on a read-only mount
    want = min(length or MAX_SECONDS, MAX_SECONDS)
    try:
        # mono 24 kHz, trim leading/trailing silence, cap the length VieNeu uses for cloning
        proc.run_ffmpeg(["-ss", f"{max(0.0, start):.3f}", "-i", str(audio), "-t", f"{want:.3f}", "-ac", "1", "-ar", "24000",
                         "-af", "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
                                "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,areverse",
                         "-c:a", "pcm_s16le", str(out)])
        dur = sf.info(out).duration
        if dur < MIN_SECONDS:
            raise VoiceError(f"Đoạn giọng mẫu chỉ có {dur:.1f} giây sau khi cắt khoảng lặng, cần ít nhất {MIN_SECONDS:.0f} giây")
        v = CustomVoice(name=name, gender=gender, note=note, duration=round(dur, 2), created=time.time())
        st.put_file(_key(name, "ref.wav"), out)
        write_json(st, _key(name, "meta.json"), asdict(v))
        return v
    finally:
        out.unlink(missing_ok=True)

def list_voices() -> list[CustomVoice]:
    st = get_store()
    out = []
    for o in st.list("voices/"):
        if o.key.endswith("/meta.json"):
            data = read_json(st, o.key)
            if data:
                out.append(CustomVoice(**data))
    return sorted(out, key=lambda v: v.name.lower())

def get(name: str) -> CustomVoice | None:
    data = read_json(get_store(), _key(name, "meta.json"))
    return CustomVoice(**data) if data else None

def delete(name: str) -> None:
    get_store().delete_prefix(f"voices/{_check_name(name)}/")

def ref_path(voice_id: str, cache_dir: Path) -> Path:
    """Local copy of the reference clip of `custom:<name>` (downloaded once per content)."""
    name = voice_id[len(PREFIX):]
    st = get_store()
    info = st.stat(_key(name, "ref.wav"))
    if info is None:
        raise VoiceError(f"Không có giọng nhân bản {name!r}")
    p = Path(cache_dir) / f"{name}-{info.etag}.wav"
    if not p.exists():
        st.get_file(_key(name, "ref.wav"), p)
    return p
