"""Small ffmpeg/ffprobe helpers."""
import json
import subprocess
from pathlib import Path
import numpy as np
from . import proc
from .models import VideoInfo

def probe(path) -> VideoInfo:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Không đọc được video: {r.stderr.strip()[-300:]}")
    data = json.loads(r.stdout)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if v is None:
        raise RuntimeError("File không có luồng video")
    num, _, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "25/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 25.0
    dur = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    w, h = int(v["width"]), int(v["height"])
    rot = int((v.get("tags") or {}).get("rotate", 0) or 0)
    for sd in v.get("side_data_list") or []:
        rot = int(sd.get("rotation", rot) or rot)
    if abs(rot) % 180 == 90:
        w, h = h, w
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return VideoInfo(width=w, height=h, duration=round(dur, 3), fps=round(fps or 25.0, 3), has_audio=has_audio)

def _tmp(out: Path) -> Path:
    return out.with_name(out.stem + ".tmp" + out.suffix)

def _finish(tmp: Path, out: Path) -> Path:
    tmp.replace(out)
    return out

def extract_audio(src, out_wav: Path, duration: float | None = None, progress=None, cancel=None) -> Path:
    out_wav = Path(out_wav); t = _tmp(out_wav)
    proc.run_ffmpeg(["-i", str(src), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(t)],
                    duration=duration, progress=progress, cancel=cancel)
    return _finish(t, out_wav)

def silent_audio(out_wav: Path, duration: float, cancel=None) -> Path:
    out_wav = Path(out_wav); t = _tmp(out_wav)
    proc.run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{duration:.3f}",
                     "-c:a", "pcm_s16le", str(t)], cancel=cancel)
    return _finish(t, out_wav)

def to_16k_mono(src_wav, out_wav: Path, cancel=None) -> Path:
    out_wav = Path(out_wav); t = _tmp(out_wav)
    proc.run_ffmpeg(["-i", str(src_wav), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(t)], cancel=cancel)
    return _finish(t, out_wav)

def grab_frames(src, out_dir: Path, duration: float, n: int = 6) -> list[Path]:
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(n):
        t = duration * (i + 0.5) / n
        p = out_dir / f"f{i}.jpg"
        proc.run_ffmpeg(["-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", "-q:v", "3", str(p)])
        out.append(p)
    return out

def decode_mono(path, sr: int = 44100) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-ac", "1", "-ar", str(sr),
                        "-f", "f32le", "-"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"Không giải mã được audio {path}: {r.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(r.stdout, dtype=np.float32).copy()

def atempo(in_wav, out_wav: Path, factor: float, cancel=None) -> Path:
    """Speed up (factor>1) without changing pitch."""
    out_wav = Path(out_wav); t = _tmp(out_wav)
    chain, f = [], factor
    while f > 2.0:
        chain.append("atempo=2.0"); f /= 2.0
    while f < 0.5:
        chain.append("atempo=0.5"); f /= 0.5
    chain.append(f"atempo={f:.5f}")
    proc.run_ffmpeg(["-i", str(in_wav), "-filter:a", ",".join(chain), "-c:a", "pcm_s16le", str(t)], cancel=cancel)
    return _finish(t, out_wav)

def probe_audio_duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)
